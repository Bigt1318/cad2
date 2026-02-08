"""
FORD-CAD Reminders — Database Models & Query Helpers
"""
import sqlite3
import json
import datetime
from typing import Optional, List, Dict

DB_PATH = "cad.db"


def _get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _ts() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_reminder_schema():
    """Create reminder tables if they don't exist."""
    conn = _get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS reminder_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            rule_type TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            config_json TEXT NOT NULL,
            notify_targets TEXT,
            created_by TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS reminder_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_id INTEGER,
            timestamp TEXT NOT NULL,
            incident_id INTEGER,
            unit_id TEXT,
            message TEXT,
            acknowledged_by TEXT,
            acknowledged_at TEXT
        )
    """)

    conn.commit()

    # Seed default rules if none exist
    count = c.execute("SELECT COUNT(*) FROM reminder_rules").fetchone()[0]
    if count == 0:
        _seed_default_rules(c)
        conn.commit()

    conn.close()


def _seed_default_rules(cursor):
    """Insert default reminder rules."""
    ts = _ts()
    defaults = [
        {
            "name": "On-Scene 30min Warning",
            "rule_type": "on_scene_timer",
            "config_json": json.dumps({"threshold_minutes": 30, "severity": "warning"}),
            "notify_targets": json.dumps(["unit"]),
        },
        {
            "name": "On-Scene 45min Alert",
            "rule_type": "on_scene_timer",
            "config_json": json.dumps({"threshold_minutes": 45, "severity": "alert"}),
            "notify_targets": json.dumps(["unit", "battalion"]),
        },
        {
            "name": "Repeated Alarm Same Location 24h",
            "rule_type": "repeated_alarm",
            "config_json": json.dumps({"window_hours": 24, "min_count": 2}),
            "notify_targets": json.dumps(["shift_commander"]),
        },
    ]
    for rule in defaults:
        cursor.execute("""
            INSERT INTO reminder_rules (name, rule_type, enabled, config_json, notify_targets, created_by, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?, 'SYSTEM', ?, ?)
        """, (rule["name"], rule["rule_type"], rule["config_json"], rule["notify_targets"], ts, ts))


# --- CRUD for rules ---

def get_rules(enabled_only: bool = False) -> List[Dict]:
    conn = _get_conn()
    c = conn.cursor()
    sql = "SELECT * FROM reminder_rules"
    if enabled_only:
        sql += " WHERE enabled = 1"
    sql += " ORDER BY id"
    rows = c.execute(sql).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_rule(rule_id: int) -> Optional[Dict]:
    conn = _get_conn()
    c = conn.cursor()
    row = c.execute("SELECT * FROM reminder_rules WHERE id = ?", (rule_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_rule(name: str, rule_type: str, config: dict, notify_targets: list, created_by: str) -> int:
    conn = _get_conn()
    c = conn.cursor()
    ts = _ts()
    c.execute("""
        INSERT INTO reminder_rules (name, rule_type, enabled, config_json, notify_targets, created_by, created_at, updated_at)
        VALUES (?, ?, 1, ?, ?, ?, ?, ?)
    """, (name, rule_type, json.dumps(config), json.dumps(notify_targets), created_by, ts, ts))
    rule_id = c.lastrowid
    conn.commit()
    conn.close()
    return rule_id


def update_rule(rule_id: int, **kwargs) -> bool:
    conn = _get_conn()
    c = conn.cursor()
    sets = []
    params = []
    for key in ("name", "rule_type", "enabled"):
        if key in kwargs:
            sets.append(f"{key} = ?")
            params.append(kwargs[key])
    if "config" in kwargs:
        sets.append("config_json = ?")
        params.append(json.dumps(kwargs["config"]))
    if "notify_targets" in kwargs:
        sets.append("notify_targets = ?")
        params.append(json.dumps(kwargs["notify_targets"]))
    sets.append("updated_at = ?")
    params.append(_ts())
    params.append(rule_id)
    c.execute(f"UPDATE reminder_rules SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()
    conn.close()
    return True


def delete_rule(rule_id: int) -> bool:
    conn = _get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM reminder_rules WHERE id = ?", (rule_id,))
    conn.commit()
    conn.close()
    return True


# --- Reminder Log ---

def log_reminder(rule_id: int, incident_id: Optional[int], unit_id: Optional[str], message: str) -> int:
    conn = _get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO reminder_log (rule_id, timestamp, incident_id, unit_id, message)
        VALUES (?, ?, ?, ?, ?)
    """, (rule_id, _ts(), incident_id, unit_id, message))
    log_id = c.lastrowid
    conn.commit()
    conn.close()
    return log_id


def get_active_reminders(limit: int = 50) -> List[Dict]:
    conn = _get_conn()
    c = conn.cursor()
    rows = c.execute("""
        SELECT rl.*, rr.name as rule_name, rr.rule_type
        FROM reminder_log rl
        LEFT JOIN reminder_rules rr ON rl.rule_id = rr.id
        WHERE rl.acknowledged_at IS NULL
        ORDER BY rl.timestamp DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def acknowledge_reminder(reminder_id: int, user: str) -> bool:
    conn = _get_conn()
    c = conn.cursor()
    c.execute("""
        UPDATE reminder_log SET acknowledged_by = ?, acknowledged_at = ? WHERE id = ?
    """, (user, _ts(), reminder_id))
    conn.commit()
    conn.close()
    return True
