"""
FORD-CAD Playbooks — Database Models & CRUD
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


def init_playbook_schema():
    """Create playbook tables if they don't exist."""
    conn = _get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS playbooks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            enabled INTEGER DEFAULT 1,
            priority INTEGER DEFAULT 0,
            trigger_type TEXT NOT NULL,
            conditions_json TEXT NOT NULL,
            actions_json TEXT NOT NULL,
            execution_mode TEXT DEFAULT 'suggest',
            max_fires_per_incident INTEGER DEFAULT 1,
            cooldown_seconds INTEGER DEFAULT 0,
            created_by TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS playbook_executions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            playbook_id INTEGER,
            timestamp TEXT NOT NULL,
            incident_id INTEGER,
            unit_id TEXT,
            result TEXT,
            actions_taken TEXT,
            executed_by TEXT,
            details TEXT
        )
    """)

    conn.commit()

    # Seed defaults if empty
    count = c.execute("SELECT COUNT(*) FROM playbooks").fetchone()[0]
    if count == 0:
        _seed_default_playbooks(c)
        conn.commit()

    conn.close()


def _seed_default_playbooks(cursor):
    """Insert default playbooks."""
    ts = _ts()
    defaults = [
        {
            "name": "Structure Fire — Suggest Battalion Chief",
            "description": "When a structure fire incident is created, suggest dispatching Battalion Chief",
            "trigger_type": "INCIDENT_CREATED",
            "conditions_json": json.dumps([
                {"field": "incident_type", "op": "contains", "value": "STRUCTURE FIRE"}
            ]),
            "actions_json": json.dumps([
                {"action": "suggest_dispatch", "unit_pattern": "BATT*", "message": "Structure fire — suggest dispatching Battalion Chief"}
            ]),
            "execution_mode": "suggest",
        },
        {
            "name": "Medical Transport — Require Disposition",
            "description": "Units transporting to medical require disposition before clearing",
            "trigger_type": "TRANSPORTING",
            "conditions_json": json.dumps([
                {"field": "event_type", "op": "equals", "value": "TRANSPORTING"}
            ]),
            "actions_json": json.dumps([
                {"action": "notify", "message": "Unit transporting — disposition required before clearing"}
            ]),
            "execution_mode": "auto",
        },
        {
            "name": "Extended Scene >45min — Notify Supervisor",
            "description": "When a unit has been on scene for more than 45 minutes, notify supervisor",
            "trigger_type": "REMINDER_ALERT",
            "conditions_json": json.dumps([
                {"field": "summary", "op": "contains", "value": "45"}
            ]),
            "actions_json": json.dumps([
                {"action": "notify", "message": "Extended scene >45min — supervisor notified", "targets": ["battalion"]}
            ]),
            "execution_mode": "auto",
        },
    ]
    for pb in defaults:
        cursor.execute("""
            INSERT INTO playbooks (name, description, enabled, priority, trigger_type, conditions_json, actions_json,
                                   execution_mode, max_fires_per_incident, cooldown_seconds, created_by, created_at, updated_at)
            VALUES (?, ?, 1, 0, ?, ?, ?, ?, 1, 300, 'SYSTEM', ?, ?)
        """, (pb["name"], pb["description"], pb["trigger_type"], pb["conditions_json"],
              pb["actions_json"], pb["execution_mode"], ts, ts))


# --- CRUD ---

def get_playbooks(enabled_only: bool = False) -> List[Dict]:
    conn = _get_conn()
    sql = "SELECT * FROM playbooks"
    if enabled_only:
        sql += " WHERE enabled = 1"
    sql += " ORDER BY priority DESC, id"
    rows = conn.execute(sql).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_playbook(pb_id: int) -> Optional[Dict]:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM playbooks WHERE id = ?", (pb_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_playbook(data: Dict) -> int:
    conn = _get_conn()
    c = conn.cursor()
    ts = _ts()
    c.execute("""
        INSERT INTO playbooks (name, description, enabled, priority, trigger_type, conditions_json, actions_json,
                               execution_mode, max_fires_per_incident, cooldown_seconds, created_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("name", "Untitled"),
        data.get("description", ""),
        data.get("enabled", 1),
        data.get("priority", 0),
        data.get("trigger_type", ""),
        json.dumps(data.get("conditions", [])),
        json.dumps(data.get("actions", [])),
        data.get("execution_mode", "suggest"),
        data.get("max_fires_per_incident", 1),
        data.get("cooldown_seconds", 0),
        data.get("created_by", "admin"),
        ts, ts,
    ))
    pb_id = c.lastrowid
    conn.commit()
    conn.close()
    return pb_id


def update_playbook(pb_id: int, data: Dict) -> bool:
    conn = _get_conn()
    c = conn.cursor()
    sets = []
    params = []
    for key in ("name", "description", "enabled", "priority", "trigger_type", "execution_mode",
                "max_fires_per_incident", "cooldown_seconds"):
        if key in data:
            sets.append(f"{key} = ?")
            params.append(data[key])
    if "conditions" in data:
        sets.append("conditions_json = ?")
        params.append(json.dumps(data["conditions"]))
    if "actions" in data:
        sets.append("actions_json = ?")
        params.append(json.dumps(data["actions"]))
    sets.append("updated_at = ?")
    params.append(_ts())
    params.append(pb_id)
    c.execute(f"UPDATE playbooks SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()
    conn.close()
    return True


def delete_playbook(pb_id: int) -> bool:
    conn = _get_conn()
    conn.execute("DELETE FROM playbooks WHERE id = ?", (pb_id,))
    conn.commit()
    conn.close()
    return True


def log_execution(playbook_id: int, incident_id: Optional[int], unit_id: Optional[str],
                  result: str, actions_taken: str, executed_by: str = "system", details: str = "") -> int:
    conn = _get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO playbook_executions (playbook_id, timestamp, incident_id, unit_id, result, actions_taken, executed_by, details)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (playbook_id, _ts(), incident_id, unit_id, result, actions_taken, executed_by, details))
    exec_id = c.lastrowid
    conn.commit()
    conn.close()
    return exec_id


def get_executions(playbook_id: Optional[int] = None, incident_id: Optional[int] = None, limit: int = 50) -> List[Dict]:
    conn = _get_conn()
    conditions = []
    params = []
    if playbook_id:
        conditions.append("pe.playbook_id = ?")
        params.append(playbook_id)
    if incident_id:
        conditions.append("pe.incident_id = ?")
        params.append(incident_id)
    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = conn.execute(f"""
        SELECT pe.*, p.name as playbook_name
        FROM playbook_executions pe
        LEFT JOIN playbooks p ON pe.playbook_id = p.id
        {where}
        ORDER BY pe.timestamp DESC LIMIT ?
    """, params + [limit]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_fires_for_incident(playbook_id: int, incident_id: int) -> int:
    """Count how many times a playbook has fired for a specific incident."""
    conn = _get_conn()
    row = conn.execute("""
        SELECT COUNT(*) as cnt FROM playbook_executions
        WHERE playbook_id = ? AND incident_id = ?
    """, (playbook_id, incident_id)).fetchone()
    conn.close()
    return row["cnt"] if row else 0
