# ============================================================================
# FORD CAD — Call History Query Layer
# ============================================================================
# Unified event queries: Incidents + DailyLog via UNION ALL,
# with server-side filtering and pagination.
# ============================================================================

import sqlite3
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("history.queries")

DB_PATH = Path(__file__).resolve().parent.parent.parent / "cad.db"


def _get_conn():
    conn = sqlite3.connect(str(DB_PATH), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# ============================================================================
# Unified event list (Incidents + DailyLog)
# ============================================================================

def fetch_unified_events(
    filters: Optional[Dict[str, Any]] = None,
    page: int = 1,
    per_page: int = 50,
) -> Dict[str, Any]:
    """Return paginated, filtered events from Incidents + DailyLog.

    Returns {"events": [...], "total": int, "page": int, "per_page": int, "pages": int}
    """
    if filters is None:
        filters = {}

    mode = filters.get("mode", "all")  # all | incidents | dailylog
    date_start = filters.get("date_start")
    date_end = filters.get("date_end")
    shift = filters.get("shift")
    search_text = filters.get("search", "").strip()
    event_type = filters.get("event_type")
    disposition = filters.get("disposition")
    unit_id = filters.get("unit_id")
    calltaker = filters.get("calltaker")
    has_narrative = filters.get("has_narrative")
    issue_found = filters.get("issue_found")

    parts = []
    count_parts = []
    params: List[Any] = []
    count_params: List[Any] = []

    # ----- Incidents sub-query -----
    if mode in ("all", "incidents"):
        inc_where = ["i.is_draft = 0", "i.type != 'DAILY LOG'"]
        inc_params: List[Any] = []

        if date_start:
            inc_where.append("i.created >= ?")
            inc_params.append(date_start)
        if date_end:
            inc_where.append("i.created <= ?")
            inc_params.append(date_end + " 23:59:59" if len(date_end) == 10 else date_end)
        if shift:
            inc_where.append("i.shift = ?")
            inc_params.append(shift)
        if event_type:
            inc_where.append("i.type = ?")
            inc_params.append(event_type)
        if disposition:
            inc_where.append("i.final_disposition = ?")
            inc_params.append(disposition)
        if issue_found:
            inc_where.append("i.issue_found = 1")
        if has_narrative:
            inc_where.append("i.narrative IS NOT NULL AND i.narrative != ''")
        if search_text:
            inc_where.append(
                "(i.location LIKE ? OR i.incident_number LIKE ? OR i.caller_name LIKE ? "
                "OR i.narrative LIKE ? OR i.type LIKE ? OR i.address LIKE ?)"
            )
            like = f"%{search_text}%"
            inc_params.extend([like] * 6)
        if unit_id:
            inc_where.append(
                "i.incident_id IN (SELECT incident_id FROM UnitAssignments WHERE unit_id = ?)"
            )
            inc_params.append(unit_id)
        if calltaker:
            inc_where.append(
                "i.incident_id IN (SELECT DISTINCT incident_id FROM Narrative WHERE user LIKE ?)"
            )
            inc_params.append(f"%{calltaker}%")

        where_clause = " AND ".join(inc_where)

        inc_sql = f"""
            SELECT
                'incident' AS source,
                i.incident_id AS event_id,
                i.incident_number AS ref_number,
                i.run_number,
                i.type AS event_type,
                COALESCE(i.location, i.address, '') AS location,
                i.status,
                i.caller_name,
                i.created AS timestamp,
                i.issue_found,
                i.shift,
                COALESCE(i.narrative, '') AS summary,
                NULL AS daily_log_category,
                NULL AS dl_unit_id,
                NULL AS dl_user,
                i.final_disposition,
                i.priority,
                i.closed_at
            FROM Incidents i
            WHERE {where_clause}
        """
        parts.append(inc_sql)
        params.extend(inc_params)

        inc_count = f"SELECT COUNT(*) FROM Incidents i WHERE {where_clause}"
        count_parts.append(inc_count)
        count_params.extend(inc_params)

    # ----- DailyLog sub-query -----
    if mode in ("all", "dailylog"):
        dl_where = ["1=1"]
        dl_params: List[Any] = []

        if date_start:
            dl_where.append("dl.timestamp >= ?")
            dl_params.append(date_start)
        if date_end:
            dl_where.append("dl.timestamp <= ?")
            dl_params.append(date_end + " 23:59:59" if len(date_end) == 10 else date_end)
        if event_type:
            dl_where.append("(dl.event_type = ? OR dl.action = ?)")
            dl_params.extend([event_type, event_type])
        if issue_found:
            dl_where.append("dl.issue_found = 1")
        if search_text:
            like = f"%{search_text}%"
            dl_where.append(
                "(dl.details LIKE ? OR dl.action LIKE ? OR dl.event_type LIKE ? "
                "OR dl.unit_id LIKE ? OR dl.user LIKE ?)"
            )
            dl_params.extend([like] * 5)
        if unit_id:
            dl_where.append("dl.unit_id = ?")
            dl_params.append(unit_id)
        if calltaker:
            dl_where.append("dl.user LIKE ?")
            dl_params.append(f"%{calltaker}%")

        where_clause = " AND ".join(dl_where)

        dl_sql = f"""
            SELECT
                'dailylog' AS source,
                dl.id AS event_id,
                CAST(dl.id AS TEXT) AS ref_number,
                NULL AS run_number,
                COALESCE(dl.event_type, dl.action, 'LOG') AS event_type,
                '' AS location,
                'LOGGED' AS status,
                '' AS caller_name,
                dl.timestamp,
                dl.issue_found,
                NULL AS shift,
                COALESCE(dl.details, '') AS summary,
                COALESCE(dl.event_type, dl.action) AS daily_log_category,
                dl.unit_id AS dl_unit_id,
                dl.user AS dl_user,
                NULL AS final_disposition,
                NULL AS priority,
                NULL AS closed_at
            FROM DailyLog dl
            WHERE {where_clause}
        """
        parts.append(dl_sql)
        params.extend(dl_params)

        dl_count = f"SELECT COUNT(*) FROM DailyLog dl WHERE {where_clause}"
        count_parts.append(dl_count)
        count_params.extend(dl_params)

    if not parts:
        return {"events": [], "total": 0, "page": page, "per_page": per_page, "pages": 0}

    # Sort logic
    sort_key = filters.get("sort", "time-desc")
    sort_map = {
        "time-desc": "timestamp DESC",
        "time-asc": "timestamp ASC",
        "incident-desc": "CAST(COALESCE(NULLIF(ref_number,''), '0') AS INTEGER) DESC, timestamp DESC",
        "incident-asc": "CAST(COALESCE(NULLIF(ref_number,''), '0') AS INTEGER) ASC, timestamp ASC",
        "dl-desc": "ref_number DESC, timestamp DESC",
        "dl-asc": "ref_number ASC, timestamp ASC",
    }
    order_clause = sort_map.get(sort_key, "timestamp DESC")

    union_sql = " UNION ALL ".join(parts)
    full_sql = f"""
        SELECT * FROM ({union_sql})
        ORDER BY {order_clause}
        LIMIT ? OFFSET ?
    """
    offset = (page - 1) * per_page
    params.extend([per_page, offset])

    # Total count
    if len(count_parts) == 1:
        total_sql = count_parts[0]
    else:
        total_sql = " + ".join(f"({cp})" for cp in count_parts)
        total_sql = f"SELECT {total_sql}"

    conn = _get_conn()
    try:
        c = conn.cursor()
        total = c.execute(total_sql, count_params).fetchone()[0]
        rows = c.execute(full_sql, params).fetchall()
        events = [dict(r) for r in rows]
    finally:
        conn.close()

    pages = max(1, (total + per_page - 1) // per_page)
    return {
        "events": events,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": pages,
    }


# ============================================================================
# Incident detail (full data)
# ============================================================================

def fetch_incident_detail(incident_id: int) -> Optional[Dict[str, Any]]:
    """Return full incident data including narrative, timeline, units."""
    conn = _get_conn()
    try:
        c = conn.cursor()

        inc = c.execute("""
            SELECT *,
                SUBSTR(COALESCE(created,''), 1, 10) AS incident_date,
                SUBSTR(COALESCE(created,''), 12, 5) AS incident_time
            FROM Incidents
            WHERE incident_id = ?
        """, (incident_id,)).fetchone()

        if not inc:
            return None

        incident = dict(inc)

        # Narrative entries
        narrative = c.execute("""
            SELECT id, timestamp, user, text, entry_type, unit_id
            FROM Narrative
            WHERE incident_id = ?
            ORDER BY timestamp ASC
        """, (incident_id,)).fetchall()
        incident["narrative_entries"] = [dict(n) for n in narrative]

        # Unit assignments
        units = c.execute("""
            SELECT *
            FROM UnitAssignments
            WHERE incident_id = ?
            ORDER BY assigned ASC
        """, (incident_id,)).fetchall()
        incident["units"] = [dict(u) for u in units]

        # History/timeline
        history = c.execute("""
            SELECT id, timestamp, user, event_type, unit_id, details
            FROM IncidentHistory
            WHERE incident_id = ?
            ORDER BY timestamp ASC, id ASC
        """, (incident_id,)).fetchall()
        incident["history"] = [dict(h) for h in history]

        return incident
    finally:
        conn.close()


def fetch_unit_assignments(incident_id: int) -> List[Dict[str, Any]]:
    """Return unit-level timestamps from UnitAssignments."""
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT *
            FROM UnitAssignments
            WHERE incident_id = ?
            ORDER BY assigned ASC
        """, (incident_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ============================================================================
# Saved views
# ============================================================================

def get_saved_views() -> List[Dict[str, Any]]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM history_saved_views ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def create_saved_view(name: str, filters_json: str, created_by: str) -> int:
    conn = _get_conn()
    try:
        from datetime import datetime
        c = conn.cursor()
        c.execute(
            "INSERT INTO history_saved_views (name, filters_json, created_by, created_at) VALUES (?,?,?,?)",
            (name, filters_json, created_by, datetime.now().isoformat()),
        )
        conn.commit()
        return c.lastrowid
    finally:
        conn.close()


def delete_saved_view(view_id: int) -> bool:
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM history_saved_views WHERE id = ?", (view_id,))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


# ============================================================================
# Delivery logging
# ============================================================================

def log_delivery(
    incident_id: int,
    channel: str,
    destination: str,
    payload_json: str,
    status: str,
    provider_id: Optional[str] = None,
    error_text: Optional[str] = None,
) -> int:
    conn = _get_conn()
    try:
        from datetime import datetime
        c = conn.cursor()
        c.execute(
            """INSERT INTO incident_deliveries
               (incident_id, channel, destination, payload_json, status, provider_id, error_text, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (incident_id, channel, destination, payload_json, status, provider_id, error_text,
             datetime.now().isoformat()),
        )
        conn.commit()
        return c.lastrowid
    finally:
        conn.close()


def log_export(incident_id: int, fmt: str, artifact_path: str) -> int:
    conn = _get_conn()
    try:
        from datetime import datetime
        c = conn.cursor()
        c.execute(
            "INSERT INTO incident_exports (incident_id, format, artifact_path, created_at) VALUES (?,?,?,?)",
            (incident_id, fmt, artifact_path, datetime.now().isoformat()),
        )
        conn.commit()
        return c.lastrowid
    finally:
        conn.close()


# ============================================================================
# Distinct values for filter dropdowns
# ============================================================================

def get_distinct_values() -> Dict[str, List[str]]:
    """Return distinct event_types, dispositions, units, shifts for filter dropdowns."""
    conn = _get_conn()
    try:
        c = conn.cursor()

        types = [r[0] for r in c.execute(
            "SELECT DISTINCT type FROM Incidents WHERE type IS NOT NULL AND type != '' ORDER BY type"
        ).fetchall()]

        dispositions = [r[0] for r in c.execute(
            "SELECT DISTINCT final_disposition FROM Incidents WHERE final_disposition IS NOT NULL AND final_disposition != '' ORDER BY final_disposition"
        ).fetchall()]

        units = [r[0] for r in c.execute(
            "SELECT DISTINCT unit_id FROM UnitAssignments WHERE unit_id IS NOT NULL AND unit_id != '' ORDER BY unit_id"
        ).fetchall()]

        shifts = [r[0] for r in c.execute(
            "SELECT DISTINCT shift FROM Incidents WHERE shift IS NOT NULL AND shift != '' ORDER BY shift"
        ).fetchall()]

        return {
            "event_types": types,
            "dispositions": dispositions,
            "units": units,
            "shifts": shifts,
        }
    except Exception as e:
        logger.error("get_distinct_values failed: %s", e)
        return {"event_types": [], "dispositions": [], "units": [], "shifts": []}
    finally:
        conn.close()
