"""
FORD-CAD Reminders — Check Engine

Runs periodic checks for on-scene timers, repeated alarms, and shift handoffs.
"""
import sqlite3
import json
import datetime
import logging
from typing import List, Dict, Optional

from .models import _get_conn, _ts, get_rules, log_reminder

logger = logging.getLogger(__name__)


def check_on_scene_timers():
    """
    Check for units on scene beyond configured thresholds.
    Queries UnitAssignments WHERE arrived IS NOT NULL AND cleared IS NULL.
    """
    try:
        rules = [r for r in get_rules(enabled_only=True) if r["rule_type"] == "on_scene_timer"]
        if not rules:
            return

        conn = _get_conn()
        c = conn.cursor()

        # Get active arrived units
        rows = c.execute("""
            SELECT ua.incident_id, ua.unit_id, ua.arrived, i.incident_number, i.type
            FROM UnitAssignments ua
            LEFT JOIN Incidents i ON ua.incident_id = i.incident_id
            WHERE ua.arrived IS NOT NULL
              AND ua.cleared IS NULL
        """).fetchall()

        conn.close()
        now = datetime.datetime.now()

        for rule in rules:
            config = json.loads(rule["config_json"]) if isinstance(rule["config_json"], str) else rule["config_json"]
            threshold_min = config.get("threshold_minutes", 30)
            severity = config.get("severity", "warning")

            for row in rows:
                arrived_str = row["arrived"]
                if not arrived_str:
                    continue

                try:
                    arrived_dt = datetime.datetime.strptime(arrived_str, "%Y-%m-%d %H:%M:%S")
                except (ValueError, TypeError):
                    continue

                on_scene_minutes = (now - arrived_dt).total_seconds() / 60.0

                if on_scene_minutes >= threshold_min:
                    # Check if we already logged this rule+unit recently (avoid spam)
                    if not _recently_reminded(rule["id"], row["incident_id"], row["unit_id"], minutes=threshold_min):
                        msg = (f"Unit {row['unit_id']} on scene {int(on_scene_minutes)} min "
                               f"(threshold: {threshold_min}min) — Inc #{row['incident_number'] or row['incident_id']}")
                        log_id = log_reminder(rule["id"], row["incident_id"], row["unit_id"], msg)
                        _notify(msg, severity, row["incident_id"], row["unit_id"], rule)

    except Exception as e:
        logger.error(f"[Reminders] on_scene_timer check failed: {e}")


def check_repeated_alarms():
    """
    Check for repeated incidents at the same normalized location within a time window.
    """
    try:
        rules = [r for r in get_rules(enabled_only=True) if r["rule_type"] == "repeated_alarm"]
        if not rules:
            return

        conn = _get_conn()
        c = conn.cursor()

        for rule in rules:
            config = json.loads(rule["config_json"]) if isinstance(rule["config_json"], str) else rule["config_json"]
            window_hours = config.get("window_hours", 24)
            min_count = config.get("min_count", 2)

            since = (datetime.datetime.now() - datetime.timedelta(hours=window_hours)).strftime("%Y-%m-%d %H:%M:%S")

            # Group by normalized location (UPPER + TRIM)
            rows = c.execute("""
                SELECT UPPER(TRIM(location)) as norm_loc, COUNT(*) as cnt,
                       GROUP_CONCAT(incident_number, ', ') as inc_nums
                FROM Incidents
                WHERE created >= ?
                  AND location IS NOT NULL AND TRIM(location) != ''
                GROUP BY norm_loc
                HAVING cnt >= ?
            """, (since, min_count)).fetchall()

            for row in rows:
                loc = row["norm_loc"]
                if not _recently_reminded_location(rule["id"], loc, minutes=60):
                    msg = f"Repeated alarm: {row['cnt']} incidents at {loc} in {window_hours}h — Inc# {row['inc_nums']}"
                    log_reminder(rule["id"], None, None, msg)
                    _notify(msg, "warning", None, None, rule)

        conn.close()

    except Exception as e:
        logger.error(f"[Reminders] repeated_alarm check failed: {e}")


def generate_shift_handoff_summary() -> Optional[str]:
    """
    Compile summary of active incidents, held calls, and recent transports
    for incoming shift.
    """
    try:
        conn = _get_conn()
        c = conn.cursor()

        # Active incidents
        active = c.execute("""
            SELECT incident_id, incident_number, type, location, status
            FROM Incidents
            WHERE status IN ('OPEN', 'ACTIVE')
            ORDER BY created DESC
        """).fetchall()

        # Held calls
        held = c.execute("""
            SELECT incident_id, incident_number, type, location, held_reason
            FROM Incidents
            WHERE status = 'HELD'
            ORDER BY created DESC
        """).fetchall()

        # Recent transports (last 12h)
        twelve_ago = (datetime.datetime.now() - datetime.timedelta(hours=12)).strftime("%Y-%m-%d %H:%M:%S")
        transports = c.execute("""
            SELECT ua.unit_id, ua.incident_id, i.incident_number, i.type, i.location
            FROM UnitAssignments ua
            LEFT JOIN Incidents i ON ua.incident_id = i.incident_id
            WHERE ua.transporting IS NOT NULL
              AND ua.transporting >= ?
            ORDER BY ua.transporting DESC
        """, (twelve_ago,)).fetchall()

        conn.close()

        lines = ["=== SHIFT HANDOFF SUMMARY ===", f"Generated: {_ts()}", ""]

        if active:
            lines.append(f"ACTIVE INCIDENTS ({len(active)}):")
            for r in active:
                lines.append(f"  #{r['incident_number'] or r['incident_id']} - {r['type']} at {r['location']} [{r['status']}]")
            lines.append("")

        if held:
            lines.append(f"HELD CALLS ({len(held)}):")
            for r in held:
                lines.append(f"  #{r['incident_number'] or r['incident_id']} - {r['type']} at {r['location']} | Reason: {r['held_reason'] or 'N/A'}")
            lines.append("")

        if transports:
            lines.append(f"RECENT TRANSPORTS ({len(transports)}):")
            for r in transports:
                lines.append(f"  {r['unit_id']} → #{r['incident_number'] or r['incident_id']} - {r['type']} at {r['location']}")
            lines.append("")

        if not active and not held and not transports:
            lines.append("All clear — no active incidents, holds, or recent transports.")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"[Reminders] shift handoff summary failed: {e}")
        return None


def _recently_reminded(rule_id: int, incident_id: int, unit_id: str, minutes: int = 30) -> bool:
    """Check if we already sent a reminder for this rule+incident+unit recently."""
    try:
        conn = _get_conn()
        c = conn.cursor()
        since = (datetime.datetime.now() - datetime.timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
        row = c.execute("""
            SELECT 1 FROM reminder_log
            WHERE rule_id = ? AND incident_id = ? AND unit_id = ? AND timestamp >= ?
            LIMIT 1
        """, (rule_id, incident_id, unit_id, since)).fetchone()
        conn.close()
        return bool(row)
    except Exception:
        return False


def _recently_reminded_location(rule_id: int, location: str, minutes: int = 60) -> bool:
    """Check if we already sent a reminder for this rule+location recently."""
    try:
        conn = _get_conn()
        c = conn.cursor()
        since = (datetime.datetime.now() - datetime.timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
        row = c.execute("""
            SELECT 1 FROM reminder_log
            WHERE rule_id = ? AND message LIKE ? AND timestamp >= ?
            LIMIT 1
        """, (rule_id, f"%{location}%", since)).fetchone()
        conn.close()
        return bool(row)
    except Exception:
        return False


def _notify(message: str, severity: str, incident_id: Optional[int], unit_id: Optional[str], rule: dict):
    """Send notification via WebSocket broadcast and event stream."""
    try:
        from app.messaging.websocket import get_broadcaster
        import asyncio

        payload = {
            "message": message,
            "severity": severity,
            "incident_id": incident_id,
            "unit_id": unit_id,
            "rule_name": rule.get("name", ""),
            "rule_type": rule.get("rule_type", ""),
        }

        broadcaster = get_broadcaster()
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(broadcaster.broadcast("reminder", payload))
        except RuntimeError:
            pass
    except Exception:
        pass

    # Also emit to event stream
    try:
        from app.eventstream.emitter import emit_event
        emit_event(
            f"REMINDER_{severity.upper()}",
            incident_id=incident_id,
            unit_id=unit_id,
            summary=message,
            severity=severity,
            category="system",
        )
    except Exception:
        pass
