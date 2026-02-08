"""
FORD-CAD Event Stream — Database Models & Query Helpers
"""
import sqlite3
import json
from typing import Optional, List, Dict

DB_PATH = "cad.db"


def _get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_eventstream_schema():
    """Create event_stream table if it doesn't exist."""
    conn = _get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS event_stream (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            category TEXT DEFAULT 'system',
            severity TEXT DEFAULT 'info',
            incident_id INTEGER,
            unit_id TEXT,
            user TEXT,
            summary TEXT,
            details_json TEXT,
            shift TEXT,
            acknowledged INTEGER DEFAULT 0
        )
    """)
    # Indexes for fast queries
    for col in ("timestamp", "incident_id", "unit_id", "event_type", "category"):
        try:
            c.execute(f"CREATE INDEX IF NOT EXISTS idx_es_{col} ON event_stream ({col})")
        except Exception:
            pass
    conn.commit()
    conn.close()


def insert_event(
    timestamp: str,
    event_type: str,
    category: str = "system",
    severity: str = "info",
    incident_id: Optional[int] = None,
    unit_id: Optional[str] = None,
    user: Optional[str] = None,
    summary: Optional[str] = None,
    details: Optional[Dict] = None,
    shift: Optional[str] = None,
) -> int:
    """Insert an event and return its ID."""
    conn = _get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO event_stream
            (timestamp, event_type, category, severity, incident_id, unit_id, user, summary, details_json, shift)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        timestamp, event_type, category, severity,
        incident_id, unit_id, user, summary,
        json.dumps(details) if details else None,
        shift,
    ))
    event_id = c.lastrowid
    conn.commit()
    conn.close()
    return event_id


def query_events(
    limit: int = 50,
    offset: int = 0,
    category: Optional[str] = None,
    event_type: Optional[str] = None,
    incident_id: Optional[int] = None,
    unit_id: Optional[str] = None,
    severity: Optional[str] = None,
    since: Optional[str] = None,
    shift: Optional[str] = None,
) -> List[Dict]:
    """Query events with filters, newest first."""
    conn = _get_conn()
    c = conn.cursor()

    conditions = []
    params = []

    if category:
        conditions.append("category = ?")
        params.append(category)
    if event_type:
        conditions.append("event_type = ?")
        params.append(event_type)
    if incident_id is not None:
        conditions.append("incident_id = ?")
        params.append(incident_id)
    if unit_id:
        conditions.append("unit_id = ?")
        params.append(unit_id)
    if severity:
        conditions.append("severity = ?")
        params.append(severity)
    if since:
        conditions.append("timestamp >= ?")
        params.append(since)
    if shift:
        conditions.append("shift = ?")
        params.append(shift)

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    rows = c.execute(
        f"SELECT * FROM event_stream{where} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [limit, offset]
    ).fetchall()

    conn.close()
    return [dict(r) for r in rows]


def count_events(**filters) -> int:
    """Count events matching filters."""
    conn = _get_conn()
    c = conn.cursor()

    conditions = []
    params = []
    for key in ("category", "event_type", "incident_id", "unit_id", "severity", "shift"):
        val = filters.get(key)
        if val is not None:
            conditions.append(f"{key} = ?")
            params.append(val)

    since = filters.get("since")
    if since:
        conditions.append("timestamp >= ?")
        params.append(since)

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    row = c.execute(f"SELECT COUNT(*) as cnt FROM event_stream{where}", params).fetchone()
    conn.close()
    return row["cnt"] if row else 0


def get_event_stats(since: Optional[str] = None) -> Dict:
    """Aggregate counts by category and event_type."""
    conn = _get_conn()
    c = conn.cursor()

    time_filter = ""
    params = []
    if since:
        time_filter = " WHERE timestamp >= ?"
        params.append(since)

    by_category = {}
    for row in c.execute(
        f"SELECT category, COUNT(*) as cnt FROM event_stream{time_filter} GROUP BY category",
        params
    ).fetchall():
        by_category[row["category"]] = row["cnt"]

    by_type = {}
    for row in c.execute(
        f"SELECT event_type, COUNT(*) as cnt FROM event_stream{time_filter} GROUP BY event_type ORDER BY cnt DESC LIMIT 20",
        params
    ).fetchall():
        by_type[row["event_type"]] = row["cnt"]

    total = sum(by_category.values())

    conn.close()
    return {"total": total, "by_category": by_category, "by_type": by_type}
