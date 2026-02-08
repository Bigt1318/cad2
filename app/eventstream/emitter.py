"""
FORD-CAD Event Stream — Core Emitter

emit_event() is the single entry point for recording operational events.
It writes to the DB and broadcasts via WebSocket. Wrapped in try/except
so it NEVER breaks the caller's flow.
"""
import datetime
import json
import asyncio
import logging
from typing import Optional, Dict

from .models import insert_event, init_eventstream_schema

logger = logging.getLogger(__name__)

# Track whether schema has been initialized
_schema_ready = False


def _ensure_schema():
    global _schema_ready
    if not _schema_ready:
        init_eventstream_schema()
        _schema_ready = True


def _ts() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _current_shift() -> str:
    """Determine current shift based on time of day (Ford 3-shift pattern)."""
    hour = datetime.datetime.now().hour
    if 7 <= hour < 15:
        return "A"
    elif 15 <= hour < 23:
        return "B"
    else:
        return "C"


def _severity_for_event(event_type: str) -> str:
    """Default severity based on event type."""
    critical = {"EMERGENCY", "MAYDAY"}
    alert = {"INCIDENT_HELD", "ON_SCENE_ALERT"}
    warning = {"ON_SCENE_WARNING", "REPEATED_ALARM"}
    if event_type in critical:
        return "critical"
    if event_type in alert:
        return "alert"
    if event_type in warning:
        return "warning"
    return "info"


def _category_for_event(event_type: str) -> str:
    """Default category based on event type."""
    if event_type.startswith("INCIDENT_") or event_type in ("INCIDENT_HELD", "INCIDENT_UNHOLD"):
        return "incident"
    if event_type.startswith("UNIT_") or event_type in (
        "DISPATCHED", "ENROUTE", "ARRIVED", "TRANSPORTING",
        "AT_MEDICAL", "CLEARED", "EMERGENCY"
    ):
        return "unit"
    if event_type.startswith("NARRATIVE_"):
        return "narrative"
    if event_type.startswith("REMINDER_") or event_type.startswith("ON_SCENE_"):
        return "system"
    if event_type.startswith("CHAT_") or event_type.startswith("MESSAGE_"):
        return "chat"
    if event_type.startswith("DAILYLOG"):
        return "dailylog"
    return "system"


def emit_event(
    event_type: str,
    incident_id: Optional[int] = None,
    unit_id: Optional[str] = None,
    user: Optional[str] = None,
    summary: Optional[str] = None,
    details: Optional[Dict] = None,
    category: Optional[str] = None,
    severity: Optional[str] = None,
    shift: Optional[str] = None,
) -> Optional[int]:
    """
    Record an operational event to the event stream.

    This is ADDITIVE — it never replaces masterlog(), incident_history(), or dailylog_event().
    Wrapped in try/except so it never breaks the calling function.

    Returns the event ID on success, None on failure.
    """
    try:
        _ensure_schema()

        timestamp = _ts()
        cat = category or _category_for_event(event_type)
        sev = severity or _severity_for_event(event_type)
        sh = shift or _current_shift()

        event_id = insert_event(
            timestamp=timestamp,
            event_type=event_type,
            category=cat,
            severity=sev,
            incident_id=incident_id,
            unit_id=unit_id,
            user=user,
            summary=summary,
            details=details,
            shift=sh,
        )

        # Broadcast via WebSocket (non-blocking)
        _broadcast_event(event_id, timestamp, event_type, cat, sev, incident_id, unit_id, user, summary, sh)

        # Evaluate playbooks (non-blocking, never breaks caller)
        try:
            from app.playbooks.engine import evaluate_playbooks
            context = {
                "event_type": event_type, "incident_id": incident_id,
                "unit_id": unit_id, "user": user, "summary": summary or "",
                "category": cat, "severity": sev, "shift": sh,
            }
            evaluate_playbooks(event_type, context)
        except Exception:
            pass

        return event_id

    except Exception as e:
        logger.error(f"[EventStream] emit_event failed: {e}")
        return None


def _broadcast_event(
    event_id, timestamp, event_type, category, severity,
    incident_id, unit_id, user, summary, shift
):
    """Broadcast event via WebSocket to all connected clients."""
    try:
        from app.messaging.websocket import get_broadcaster
        broadcaster = get_broadcaster()

        payload = {
            "id": event_id,
            "timestamp": timestamp,
            "event_type": event_type,
            "category": category,
            "severity": severity,
            "incident_id": incident_id,
            "unit_id": unit_id,
            "user": user,
            "summary": summary,
            "shift": shift,
        }

        # Schedule async broadcast from sync context
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(broadcaster.broadcast("event_stream", payload))
        except RuntimeError:
            # No running loop — skip broadcast (DB write still succeeded)
            pass

    except Exception as e:
        logger.debug(f"[EventStream] broadcast skipped: {e}")
