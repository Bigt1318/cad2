# ============================================================================
# FORD CAD - Report Generation Engine (v3)
# ============================================================================
# Template-driven report generation with data extraction, rendering,
# artifact persistence, and delivery orchestration.
#
# Template Registry
# -----------------
# Each template_key maps to a data-extraction function that queries cad.db
# and returns a standardized result dict.  Built-in keys:
#
#   blotter              - Chronological DailyLog + Incidents
#   incident_summary     - Full incident detail (units, narrative, timeline)
#   unit_response_stats  - Response-time metrics per unit
#   calltaker_stats      - Calltaker performance metrics
#   shift_workload       - Workload distribution across shifts
#   response_compliance  - Pass / fail against response thresholds
#   custom:*             - Custom templates from the builder (stored config)
# ============================================================================

import json
import logging
import sqlite3
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from .models import (
    RunRepository,
    ReportRun,
    DeliveryRepository,
    ReportDelivery,
    AuditRepository,
    TemplateRepository,
    get_db,
    make_download_token,
    ensure_artifact_dir,
)
from .config import get_config, get_local_now, format_time_for_display, get_timezone
from .delivery import EmailDelivery, SMSDelivery, WebhookDelivery

# Try to import the renderer; it may not exist yet.
try:
    from .renderer import ReportRenderer
except ImportError:
    ReportRenderer = None  # type: ignore[misc,assignment]

# Import shift logic
try:
    from shift_logic import get_current_shift, BATTALION_CHIEFS
except ImportError:
    BATTALION_CHIEFS: Dict[str, Any] = {}

    def get_current_shift(dt=None) -> str:  # type: ignore[misc]
        if dt is None:
            dt = datetime.now()
        return "A" if 6 <= dt.hour < 18 else "B"

logger = logging.getLogger("reporting.engine")

EASTERN = ZoneInfo("America/New_York")
DB_PATH = Path("cad.db")

# ============================================================================
# Timestamp helpers
# ============================================================================

_ISO_FORMATS = [
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
]


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-ish timestamp string into a naive datetime, or None."""
    if not value:
        return None
    for fmt in _ISO_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def _minutes_between(start_str: Optional[str], end_str: Optional[str]) -> Optional[float]:
    """Return the number of minutes between two ISO timestamp strings.

    Returns None when either value is missing or unparseable.
    """
    start = _parse_ts(start_str)
    end = _parse_ts(end_str)
    if start is None or end is None:
        return None
    delta = (end - start).total_seconds() / 60.0
    # Negative deltas are not meaningful for response-time calculations.
    return round(delta, 2) if delta >= 0 else None


def _safe_avg(values: List[float]) -> Optional[float]:
    """Average of a list of floats, ignoring None.  Returns None if empty."""
    cleaned = [v for v in values if v is not None]
    if not cleaned:
        return None
    return round(sum(cleaned) / len(cleaned), 2)


def _safe_median(values: List[float]) -> Optional[float]:
    """Median of a list of floats, ignoring None."""
    cleaned = sorted(v for v in values if v is not None)
    if not cleaned:
        return None
    n = len(cleaned)
    mid = n // 2
    if n % 2 == 0:
        return round((cleaned[mid - 1] + cleaned[mid]) / 2.0, 2)
    return round(cleaned[mid], 2)


def _safe_percentile(values: List[float], pct: float = 90.0) -> Optional[float]:
    """Return the *pct*-th percentile.  None when empty."""
    cleaned = sorted(v for v in values if v is not None)
    if not cleaned:
        return None
    idx = int(len(cleaned) * pct / 100.0)
    idx = min(idx, len(cleaned) - 1)
    return round(cleaned[idx], 2)


# ============================================================================
# Shift / date-range resolution
# ============================================================================

def _resolve_shift_range(
    date_start: Optional[str],
    date_end: Optional[str],
    shift: Optional[str],
) -> Tuple[str, str, Optional[str]]:
    """Resolve filter parameters into (start_iso, end_iso, shift_label).

    Rules
    -----
    * If *date_start* **and** *date_end* are supplied they are used verbatim.
    * If only *shift* is supplied (or nothing at all) the engine computes the
      current shift period.
    * Day shift:  06:00 -- 18:00 same day.
    * Night shift: 18:00 -- 06:00 next day.
    """
    if date_start and date_end:
        return date_start, date_end, shift

    now = get_local_now()
    if shift is None:
        shift = get_current_shift(now)

    current_date = now.date()
    hour = now.hour

    is_day = 6 <= hour < 18

    if is_day:
        start_dt = datetime.combine(current_date, datetime.min.time().replace(hour=6))
        end_dt = datetime.combine(current_date, datetime.min.time().replace(hour=18))
    else:
        if hour < 6:
            # Early morning -- shift started previous evening.
            start_dt = datetime.combine(
                current_date - timedelta(days=1), datetime.min.time().replace(hour=18)
            )
            end_dt = datetime.combine(current_date, datetime.min.time().replace(hour=6))
        else:
            # Evening -- shift ends next morning.
            start_dt = datetime.combine(current_date, datetime.min.time().replace(hour=18))
            end_dt = datetime.combine(
                current_date + timedelta(days=1), datetime.min.time().replace(hour=6)
            )

    fmt = "%Y-%m-%d %H:%M:%S"
    return start_dt.strftime(fmt), end_dt.strftime(fmt), shift


# ============================================================================
# Database helper
# ============================================================================

def _get_conn() -> sqlite3.Connection:
    """Return a new connection with row-factory enabled."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _rows_to_dicts(rows) -> List[Dict[str, Any]]:
    """Convert sqlite3.Row objects to plain dicts."""
    return [dict(r) for r in rows]


def _build_where(
    base_clauses: List[str],
    params: List[Any],
    filters: Dict[str, Any],
    *,
    ts_col: str = "created",
    start_key: str = "date_start",
    end_key: str = "date_end",
) -> Tuple[str, List[Any]]:
    """Append common filter clauses.  Mutates *base_clauses* and *params*."""
    if filters.get(start_key):
        base_clauses.append(f"{ts_col} >= ?")
        params.append(filters[start_key])
    if filters.get(end_key):
        base_clauses.append(f"{ts_col} < ?")
        params.append(filters[end_key])
    if filters.get("shift"):
        base_clauses.append("shift = ?")
        params.append(filters["shift"])
    if filters.get("status"):
        base_clauses.append("status = ?")
        params.append(filters["status"])
    if filters.get("incident_type"):
        base_clauses.append("type = ?")
        params.append(filters["incident_type"])

    where = " AND ".join(base_clauses) if base_clauses else "1=1"
    return where, params


# ============================================================================
# Template data-extraction functions
# ============================================================================

def _extract_blotter(filters: Dict[str, Any]) -> Dict[str, Any]:
    """Blotter / Daily Log -- chronological list of events."""

    start, end, shift = _resolve_shift_range(
        filters.get("date_start"), filters.get("date_end"), filters.get("shift")
    )
    filters = {**filters, "date_start": start, "date_end": end, "shift": shift}

    conn = _get_conn()

    # --- Daily log entries ---------------------------------------------------
    dl_clauses: List[str] = []
    dl_params: List[Any] = []

    if filters.get("date_start"):
        dl_clauses.append("dl.timestamp >= ?")
        dl_params.append(filters["date_start"])
    if filters.get("date_end"):
        dl_clauses.append("dl.timestamp < ?")
        dl_params.append(filters["date_end"])
    if filters.get("event_type"):
        dl_clauses.append("dl.event_type = ?")
        dl_params.append(filters["event_type"])
    if filters.get("units"):
        placeholders = ",".join("?" * len(filters["units"]))
        dl_clauses.append(f"dl.unit_id IN ({placeholders})")
        dl_params.extend(filters["units"])
    if filters.get("calltaker"):
        dl_clauses.append("dl.user = ?")
        dl_params.append(filters["calltaker"])

    dl_where = " AND ".join(dl_clauses) if dl_clauses else "1=1"

    daily_log = _rows_to_dicts(
        conn.execute(
            f"""
            SELECT dl.id, dl.timestamp, dl.user, dl.incident_id, dl.unit_id,
                   dl.action, dl.event_type, dl.details, dl.issue_found
            FROM DailyLog dl
            WHERE {dl_where}
            ORDER BY dl.timestamp ASC
            """,
            dl_params,
        ).fetchall()
    )

    # --- Incidents in range --------------------------------------------------
    inc_clauses: List[str] = []
    inc_params: List[Any] = []

    if filters.get("date_start"):
        inc_clauses.append("i.created >= ?")
        inc_params.append(filters["date_start"])
    if filters.get("date_end"):
        inc_clauses.append("i.created < ?")
        inc_params.append(filters["date_end"])
    if filters.get("shift"):
        inc_clauses.append("i.shift = ?")
        inc_params.append(filters["shift"])
    if filters.get("status"):
        inc_clauses.append("i.status = ?")
        inc_params.append(filters["status"])
    if filters.get("incident_type"):
        inc_clauses.append("i.type = ?")
        inc_params.append(filters["incident_type"])

    inc_where = " AND ".join(inc_clauses) if inc_clauses else "1=1"

    incidents = _rows_to_dicts(
        conn.execute(
            f"""
            SELECT i.incident_id, i.incident_number, i.type, i.location,
                   i.caller_name, i.status, i.priority, i.final_disposition,
                   i.issue_found, i.created, i.updated, i.closed_at, i.shift
            FROM Incidents i
            WHERE {inc_where}
            ORDER BY i.created ASC
            """,
            inc_params,
        ).fetchall()
    )

    conn.close()

    # --- Flag issues ---------------------------------------------------------
    issues_found: List[Dict[str, Any]] = []
    for entry in daily_log:
        if entry.get("issue_found") == 1:
            issues_found.append({
                "source": "daily_log",
                "id": entry["id"],
                "timestamp": entry.get("timestamp"),
                "description": (entry.get("details") or "")[:120],
            })
    for inc in incidents:
        if inc.get("issue_found") == 1:
            issues_found.append({
                "source": "incident",
                "id": inc["incident_id"],
                "number": inc.get("incident_number"),
                "timestamp": inc.get("created"),
                "description": f"{inc.get('type', '')} at {inc.get('location', '')}",
            })

    # --- Stats ---------------------------------------------------------------
    stats = {
        "daily_log_count": len(daily_log),
        "incident_count": len(incidents),
        "issues_count": len(issues_found),
        "open_incidents": sum(1 for i in incidents if i.get("status") not in ("CLOSED", "CANCELLED")),
        "closed_incidents": sum(1 for i in incidents if i.get("status") == "CLOSED"),
    }

    bc_info = BATTALION_CHIEFS.get(shift, {}) if shift else {}

    return {
        "rows": daily_log + [
            {
                "id": f"inc-{inc['incident_id']}",
                "timestamp": inc.get("created"),
                "user": inc.get("caller_name"),
                "incident_id": inc["incident_id"],
                "unit_id": None,
                "action": "INCIDENT",
                "event_type": inc.get("type"),
                "details": f"[{inc.get('status','')}] {inc.get('type','')} at {inc.get('location','')}",
                "issue_found": inc.get("issue_found", 0),
            }
            for inc in incidents
        ],
        "stats": stats,
        "metadata": {
            "title": f"Blotter / Daily Log - {shift or 'All'} Shift",
            "template_key": "blotter",
            "date_range": [start, end],
            "shift": shift,
            "generated_at": format_time_for_display(),
            "timezone": str(get_timezone()),
            "battalion_chief": bc_info.get("name", ""),
        },
        "incidents": incidents,
        "daily_log": daily_log,
        "issues_found": issues_found,
    }


def _extract_incident_summary(filters: Dict[str, Any]) -> Dict[str, Any]:
    """Incident Summary -- full details with units, narrative, timeline."""

    start, end, shift = _resolve_shift_range(
        filters.get("date_start"), filters.get("date_end"), filters.get("shift")
    )
    filters = {**filters, "date_start": start, "date_end": end, "shift": shift}
    mode = filters.get("mode", "detailed")

    conn = _get_conn()

    # --- Incidents -----------------------------------------------------------
    clauses: List[str] = []
    params: List[Any] = []

    if filters.get("date_start"):
        clauses.append("i.created >= ?")
        params.append(filters["date_start"])
    if filters.get("date_end"):
        clauses.append("i.created < ?")
        params.append(filters["date_end"])
    if filters.get("shift"):
        clauses.append("i.shift = ?")
        params.append(filters["shift"])
    if filters.get("status"):
        clauses.append("i.status = ?")
        params.append(filters["status"])
    if filters.get("incident_type"):
        clauses.append("i.type = ?")
        params.append(filters["incident_type"])

    where = " AND ".join(clauses) if clauses else "1=1"

    incidents = _rows_to_dicts(
        conn.execute(
            f"""
            SELECT i.incident_id, i.incident_number, i.run_number, i.type,
                   i.location, i.address, i.node, i.pole,
                   i.caller_name, i.caller_phone, i.narrative,
                   i.status, i.priority, i.final_disposition,
                   i.issue_found, i.created, i.updated, i.closed_at,
                   i.shift, i.determinant_code
            FROM Incidents i
            WHERE {where}
            ORDER BY i.created ASC
            """,
            params,
        ).fetchall()
    )

    if not incidents:
        conn.close()
        return {
            "rows": [],
            "stats": {"total_incidents": 0},
            "metadata": {
                "title": "Incident Summary (no incidents found)",
                "template_key": "incident_summary",
                "date_range": [start, end],
                "shift": shift,
                "generated_at": format_time_for_display(),
                "timezone": str(get_timezone()),
            },
            "incidents": [],
            "daily_log": [],
            "issues_found": [],
        }

    incident_ids = [inc["incident_id"] for inc in incidents]
    placeholders = ",".join("?" * len(incident_ids))

    # --- Unit Assignments for each incident ----------------------------------
    assignments = _rows_to_dicts(
        conn.execute(
            f"""
            SELECT ua.incident_id, ua.unit_id, ua.commanding_unit,
                   ua.assigned, ua.dispatched, ua.enroute, ua.arrived,
                   ua.transporting, ua.at_medical, ua.cleared,
                   ua.disposition, ua.disposition_remark
            FROM UnitAssignments ua
            WHERE ua.incident_id IN ({placeholders})
            ORDER BY ua.dispatched ASC
            """,
            incident_ids,
        ).fetchall()
    )

    ua_map: Dict[int, List[Dict]] = {}
    for ua in assignments:
        ua_map.setdefault(ua["incident_id"], []).append(ua)

    # --- Narrative entries ----------------------------------------------------
    narratives = _rows_to_dicts(
        conn.execute(
            f"""
            SELECT n.incident_id, n.timestamp, n.entry_type, n.text,
                   n.user, n.unit_id
            FROM Narrative n
            WHERE n.incident_id IN ({placeholders})
            ORDER BY n.timestamp ASC
            """,
            incident_ids,
        ).fetchall()
    )

    narr_map: Dict[int, List[Dict]] = {}
    for n in narratives:
        narr_map.setdefault(n["incident_id"], []).append(n)

    # --- IncidentHistory (timeline) ------------------------------------------
    timeline = _rows_to_dicts(
        conn.execute(
            f"""
            SELECT ih.incident_id, ih.timestamp, ih.user, ih.event_type,
                   ih.unit_id, ih.details
            FROM IncidentHistory ih
            WHERE ih.incident_id IN ({placeholders})
            ORDER BY ih.timestamp ASC
            """,
            incident_ids,
        ).fetchall()
    )

    tl_map: Dict[int, List[Dict]] = {}
    for t in timeline:
        tl_map.setdefault(t["incident_id"], []).append(t)

    conn.close()

    # --- Assemble incidents with sub-records ---------------------------------
    issues_found: List[Dict[str, Any]] = []
    rows: List[Dict[str, Any]] = []

    for inc in incidents:
        iid = inc["incident_id"]
        inc["units"] = ua_map.get(iid, [])
        inc["narrative_entries"] = narr_map.get(iid, [])
        inc["timeline"] = tl_map.get(iid, [])

        # Calculate response-time metrics for each unit on this incident
        for ua in inc["units"]:
            ua["time_to_dispatch_min"] = _minutes_between(inc.get("created"), ua.get("dispatched"))
            ua["time_to_enroute_min"] = _minutes_between(ua.get("dispatched"), ua.get("enroute"))
            ua["time_to_arrive_min"] = _minutes_between(ua.get("dispatched"), ua.get("arrived"))
            ua["total_response_min"] = _minutes_between(inc.get("created"), ua.get("arrived"))
            ua["on_scene_min"] = _minutes_between(ua.get("arrived"), ua.get("cleared"))

        if inc.get("issue_found") == 1:
            issues_found.append({
                "source": "incident",
                "id": iid,
                "number": inc.get("incident_number"),
                "timestamp": inc.get("created"),
                "description": f"{inc.get('type', '')} at {inc.get('location', '')}",
            })

        # Build condensed row for tabular output
        row: Dict[str, Any] = {
            "incident_id": iid,
            "incident_number": inc.get("incident_number"),
            "type": inc.get("type"),
            "location": inc.get("location"),
            "status": inc.get("status"),
            "priority": inc.get("priority"),
            "created": inc.get("created"),
            "closed_at": inc.get("closed_at"),
            "disposition": inc.get("final_disposition"),
            "units_count": len(inc["units"]),
            "issue_found": inc.get("issue_found", 0),
        }
        if mode == "detailed":
            row["units"] = inc["units"]
            row["narrative_entries"] = inc["narrative_entries"]
            row["timeline"] = inc["timeline"]
        rows.append(row)

    # --- Stats ---------------------------------------------------------------
    stats = {
        "total_incidents": len(incidents),
        "open_incidents": sum(1 for i in incidents if i.get("status") not in ("CLOSED", "CANCELLED")),
        "closed_incidents": sum(1 for i in incidents if i.get("status") == "CLOSED"),
        "cancelled_incidents": sum(1 for i in incidents if i.get("status") == "CANCELLED"),
        "issues_count": len(issues_found),
        "incidents_by_type": {},
        "incidents_by_priority": {},
    }

    for inc in incidents:
        t = inc.get("type") or "UNKNOWN"
        stats["incidents_by_type"][t] = stats["incidents_by_type"].get(t, 0) + 1
        p = str(inc.get("priority") or "N/A")
        stats["incidents_by_priority"][p] = stats["incidents_by_priority"].get(p, 0) + 1

    return {
        "rows": rows,
        "stats": stats,
        "metadata": {
            "title": f"Incident Summary - {shift or 'All'} Shift",
            "template_key": "incident_summary",
            "date_range": [start, end],
            "shift": shift,
            "generated_at": format_time_for_display(),
            "timezone": str(get_timezone()),
        },
        "incidents": incidents,
        "daily_log": [],
        "issues_found": issues_found,
    }


def _extract_unit_response_stats(filters: Dict[str, Any]) -> Dict[str, Any]:
    """Unit Response Stats -- response-time metrics grouped by unit."""

    start, end, shift = _resolve_shift_range(
        filters.get("date_start"), filters.get("date_end"), filters.get("shift")
    )
    filters = {**filters, "date_start": start, "date_end": end, "shift": shift}

    conn = _get_conn()

    # Get all unit assignments within the date range by joining to Incidents.
    clauses: List[str] = []
    params: List[Any] = []

    if filters.get("date_start"):
        clauses.append("i.created >= ?")
        params.append(filters["date_start"])
    if filters.get("date_end"):
        clauses.append("i.created < ?")
        params.append(filters["date_end"])
    if filters.get("shift"):
        clauses.append("i.shift = ?")
        params.append(filters["shift"])
    if filters.get("units"):
        ph = ",".join("?" * len(filters["units"]))
        clauses.append(f"ua.unit_id IN ({ph})")
        params.extend(filters["units"])

    where = " AND ".join(clauses) if clauses else "1=1"

    rows_raw = _rows_to_dicts(
        conn.execute(
            f"""
            SELECT ua.unit_id, ua.dispatched, ua.enroute, ua.arrived,
                   ua.transporting, ua.cleared, ua.disposition,
                   ua.commanding_unit,
                   i.incident_id, i.created AS incident_created,
                   i.type AS incident_type, i.status AS incident_status
            FROM UnitAssignments ua
            JOIN Incidents i ON ua.incident_id = i.incident_id
            WHERE {where}
            ORDER BY ua.unit_id, ua.dispatched
            """,
            params,
        ).fetchall()
    )

    # Fetch unit metadata
    unit_meta: Dict[str, Dict] = {}
    for u in _rows_to_dicts(conn.execute("SELECT unit_id, name, unit_type FROM Units").fetchall()):
        unit_meta[u["unit_id"]] = u

    conn.close()

    # --- Aggregate per unit --------------------------------------------------
    unit_buckets: Dict[str, List[Dict]] = {}
    for r in rows_raw:
        unit_buckets.setdefault(r["unit_id"], []).append(r)

    rows: List[Dict[str, Any]] = []
    all_response_times: List[float] = []

    for unit_id in sorted(unit_buckets.keys()):
        entries = unit_buckets[unit_id]
        meta = unit_meta.get(unit_id, {})

        dispatch_times = [_minutes_between(e["incident_created"], e["dispatched"]) for e in entries]
        enroute_times = [_minutes_between(e["dispatched"], e["enroute"]) for e in entries]
        travel_times = [_minutes_between(e["enroute"], e["arrived"]) for e in entries]
        total_response = [_minutes_between(e["incident_created"], e["arrived"]) for e in entries]
        on_scene_times = [_minutes_between(e["arrived"], e["cleared"]) for e in entries]

        all_response_times.extend(t for t in total_response if t is not None)

        row = {
            "unit_id": unit_id,
            "unit_name": meta.get("name", unit_id),
            "unit_type": meta.get("unit_type", ""),
            "total_responses": len(entries),
            "dispatch_time_avg": _safe_avg(dispatch_times),
            "dispatch_time_median": _safe_median(dispatch_times),
            "enroute_time_avg": _safe_avg(enroute_times),
            "enroute_time_median": _safe_median(enroute_times),
            "travel_time_avg": _safe_avg(travel_times),
            "travel_time_median": _safe_median(travel_times),
            "total_response_avg": _safe_avg(total_response),
            "total_response_median": _safe_median(total_response),
            "total_response_90pct": _safe_percentile(total_response, 90),
            "on_scene_avg": _safe_avg(on_scene_times),
            "on_scene_median": _safe_median(on_scene_times),
            "commanding_count": sum(1 for e in entries if e.get("commanding_unit")),
        }
        rows.append(row)

    stats = {
        "units_active": len(rows),
        "total_responses": sum(r["total_responses"] for r in rows),
        "overall_response_avg": _safe_avg(all_response_times),
        "overall_response_median": _safe_median(all_response_times),
        "overall_response_90pct": _safe_percentile(all_response_times, 90),
    }

    return {
        "rows": rows,
        "stats": stats,
        "metadata": {
            "title": "Unit Response Statistics",
            "template_key": "unit_response_stats",
            "date_range": [start, end],
            "shift": shift,
            "generated_at": format_time_for_display(),
            "timezone": str(get_timezone()),
        },
        "incidents": [],
        "daily_log": [],
        "issues_found": [],
    }


def _extract_calltaker_stats(filters: Dict[str, Any]) -> Dict[str, Any]:
    """Calltaker Stats -- performance metrics grouped by calltaker (user)."""

    start, end, shift = _resolve_shift_range(
        filters.get("date_start"), filters.get("date_end"), filters.get("shift")
    )
    filters = {**filters, "date_start": start, "date_end": end, "shift": shift}

    conn = _get_conn()

    # --- Daily log activity per user -----------------------------------------
    dl_clauses: List[str] = []
    dl_params: List[Any] = []

    if filters.get("date_start"):
        dl_clauses.append("dl.timestamp >= ?")
        dl_params.append(filters["date_start"])
    if filters.get("date_end"):
        dl_clauses.append("dl.timestamp < ?")
        dl_params.append(filters["date_end"])
    if filters.get("calltaker"):
        dl_clauses.append("dl.user = ?")
        dl_params.append(filters["calltaker"])

    dl_where = " AND ".join(dl_clauses) if dl_clauses else "1=1"

    dl_rows = _rows_to_dicts(
        conn.execute(
            f"""
            SELECT dl.user, dl.event_type, dl.action, dl.incident_id,
                   dl.issue_found, dl.timestamp
            FROM DailyLog dl
            WHERE {dl_where} AND dl.user IS NOT NULL AND dl.user != ''
            ORDER BY dl.user, dl.timestamp
            """,
            dl_params,
        ).fetchall()
    )

    # --- Incidents created per user (approximate via narrative or history) ----
    # We'll use IncidentHistory "CREATED" events to attribute incidents to
    # the user who created them.
    ih_clauses: List[str] = []
    ih_params: List[Any] = []

    if filters.get("date_start"):
        ih_clauses.append("ih.timestamp >= ?")
        ih_params.append(filters["date_start"])
    if filters.get("date_end"):
        ih_clauses.append("ih.timestamp < ?")
        ih_params.append(filters["date_end"])
    if filters.get("calltaker"):
        ih_clauses.append("ih.user = ?")
        ih_params.append(filters["calltaker"])

    ih_where = " AND ".join(ih_clauses) if ih_clauses else "1=1"

    # Get incident-creation events and join to Incidents for dispatch timing
    incident_rows = _rows_to_dicts(
        conn.execute(
            f"""
            SELECT ih.user, ih.incident_id, ih.timestamp AS created_ts,
                   i.type AS incident_type, i.final_disposition,
                   (SELECT MIN(ua.dispatched) FROM UnitAssignments ua
                    WHERE ua.incident_id = ih.incident_id) AS first_dispatch
            FROM IncidentHistory ih
            JOIN Incidents i ON ih.incident_id = i.incident_id
            WHERE {ih_where}
              AND ih.event_type IN ('CREATED', 'CREATE', 'created', 'incident_created')
              AND ih.user IS NOT NULL AND ih.user != ''
            ORDER BY ih.user, ih.timestamp
            """,
            ih_params,
        ).fetchall()
    )

    conn.close()

    # --- Aggregate per calltaker ---------------------------------------------
    calltaker_dl: Dict[str, List[Dict]] = {}
    for row in dl_rows:
        calltaker_dl.setdefault(row["user"], []).append(row)

    calltaker_inc: Dict[str, List[Dict]] = {}
    for row in incident_rows:
        calltaker_inc.setdefault(row["user"], []).append(row)

    all_users = sorted(set(list(calltaker_dl.keys()) + list(calltaker_inc.keys())))

    rows: List[Dict[str, Any]] = []
    for user in all_users:
        dl_entries = calltaker_dl.get(user, [])
        inc_entries = calltaker_inc.get(user, [])

        # Time to dispatch: from incident creation to first unit dispatched
        dispatch_times = [
            _minutes_between(e.get("created_ts"), e.get("first_dispatch"))
            for e in inc_entries
        ]

        # Dispositions breakdown
        dispositions: Dict[str, int] = {}
        for e in inc_entries:
            d = e.get("final_disposition") or "N/A"
            dispositions[d] = dispositions.get(d, 0) + 1

        # Event-type breakdown for daily-log activity
        event_types: Dict[str, int] = {}
        for e in dl_entries:
            et = e.get("event_type") or e.get("action") or "other"
            event_types[et] = event_types.get(et, 0) + 1

        rows.append({
            "calltaker": user,
            "incidents_created": len(inc_entries),
            "daily_log_entries": len(dl_entries),
            "time_to_dispatch_avg": _safe_avg(dispatch_times),
            "time_to_dispatch_median": _safe_median(dispatch_times),
            "time_to_dispatch_90pct": _safe_percentile(dispatch_times, 90),
            "dispositions": dispositions,
            "event_types": event_types,
            "issues_flagged": sum(1 for e in dl_entries if e.get("issue_found") == 1),
        })

    stats = {
        "calltakers_active": len(rows),
        "total_incidents_created": sum(r["incidents_created"] for r in rows),
        "total_daily_log_entries": sum(r["daily_log_entries"] for r in rows),
        "overall_dispatch_avg": _safe_avg(
            [r["time_to_dispatch_avg"] for r in rows if r["time_to_dispatch_avg"] is not None]
        ),
    }

    return {
        "rows": rows,
        "stats": stats,
        "metadata": {
            "title": "Calltaker Performance Statistics",
            "template_key": "calltaker_stats",
            "date_range": [start, end],
            "shift": shift,
            "generated_at": format_time_for_display(),
            "timezone": str(get_timezone()),
        },
        "incidents": [],
        "daily_log": [],
        "issues_found": [],
    }


def _extract_shift_workload(filters: Dict[str, Any]) -> Dict[str, Any]:
    """Shift Workload -- distribution of activity across shifts."""

    start = filters.get("date_start")
    end = filters.get("date_end")

    # Default to last 24 hours if no range provided
    if not start or not end:
        now = get_local_now()
        end_dt = now
        start_dt = now - timedelta(hours=24)
        start = start_dt.strftime("%Y-%m-%d %H:%M:%S")
        end = end_dt.strftime("%Y-%m-%d %H:%M:%S")

    conn = _get_conn()

    # --- Incidents by shift --------------------------------------------------
    incidents = _rows_to_dicts(
        conn.execute(
            """
            SELECT i.incident_id, i.type, i.status, i.priority, i.shift,
                   i.created, i.closed_at, i.issue_found
            FROM Incidents i
            WHERE i.created >= ? AND i.created < ?
            ORDER BY i.created
            """,
            (start, end),
        ).fetchall()
    )

    # --- Daily log by shift (derive shift from timestamp hour) ---------------
    daily_log = _rows_to_dicts(
        conn.execute(
            """
            SELECT dl.id, dl.timestamp, dl.user, dl.event_type,
                   dl.action, dl.issue_found
            FROM DailyLog dl
            WHERE dl.timestamp >= ? AND dl.timestamp < ?
            ORDER BY dl.timestamp
            """,
            (start, end),
        ).fetchall()
    )

    # --- Unit assignments count per shift ------------------------------------
    ua_counts = _rows_to_dicts(
        conn.execute(
            """
            SELECT i.shift, COUNT(ua.id) as assignment_count,
                   COUNT(DISTINCT ua.unit_id) as units_used
            FROM UnitAssignments ua
            JOIN Incidents i ON ua.incident_id = i.incident_id
            WHERE i.created >= ? AND i.created < ?
            GROUP BY i.shift
            """,
            (start, end),
        ).fetchall()
    )

    conn.close()

    # --- Aggregate per shift -------------------------------------------------
    shift_labels = sorted(set(
        [i.get("shift") or "UNKNOWN" for i in incidents]
    ))

    def _derive_shift_from_ts(ts_str: Optional[str]) -> str:
        """Derive a day/night label from a timestamp."""
        dt = _parse_ts(ts_str)
        if dt is None:
            return "UNKNOWN"
        return get_current_shift(dt)

    rows: List[Dict[str, Any]] = []
    ua_map = {r.get("shift", "UNKNOWN"): r for r in ua_counts}

    for sl in shift_labels:
        shift_incidents = [i for i in incidents if (i.get("shift") or "UNKNOWN") == sl]
        # Daily log entries whose timestamp falls within this shift's hours
        shift_dl = [
            dl for dl in daily_log
            if _derive_shift_from_ts(dl.get("timestamp")) == sl
        ]

        ua_info = ua_map.get(sl, {})

        inc_types: Dict[str, int] = {}
        for si in shift_incidents:
            t = si.get("type") or "UNKNOWN"
            inc_types[t] = inc_types.get(t, 0) + 1

        rows.append({
            "shift": sl,
            "incident_count": len(shift_incidents),
            "daily_log_count": len(shift_dl),
            "unit_assignments": ua_info.get("assignment_count", 0),
            "distinct_units_used": ua_info.get("units_used", 0),
            "open_incidents": sum(1 for i in shift_incidents if i.get("status") not in ("CLOSED", "CANCELLED")),
            "closed_incidents": sum(1 for i in shift_incidents if i.get("status") == "CLOSED"),
            "issues_flagged": (
                sum(1 for i in shift_incidents if i.get("issue_found") == 1) +
                sum(1 for dl in shift_dl if dl.get("issue_found") == 1)
            ),
            "incidents_by_type": inc_types,
            "battalion_chief": BATTALION_CHIEFS.get(sl, {}).get("name", ""),
        })

    stats = {
        "shifts_covered": len(rows),
        "total_incidents": len(incidents),
        "total_daily_log": len(daily_log),
        "busiest_shift": max(rows, key=lambda r: r["incident_count"])["shift"] if rows else None,
    }

    return {
        "rows": rows,
        "stats": stats,
        "metadata": {
            "title": "Shift Workload Summary",
            "template_key": "shift_workload",
            "date_range": [start, end],
            "shift": None,
            "generated_at": format_time_for_display(),
            "timezone": str(get_timezone()),
        },
        "incidents": incidents,
        "daily_log": daily_log,
        "issues_found": [],
    }


def _extract_response_compliance(filters: Dict[str, Any]) -> Dict[str, Any]:
    """Response-Time Compliance -- pass / fail against configurable thresholds.

    The default threshold is 5 minutes (total response = incident created to
    first unit arrived).  The threshold may be overridden per incident type
    via filters["thresholds"] = {"FIRE": 4, "EMS": 6, ...} or globally via
    filters["threshold_minutes"].
    """

    start, end, shift = _resolve_shift_range(
        filters.get("date_start"), filters.get("date_end"), filters.get("shift")
    )
    filters = {**filters, "date_start": start, "date_end": end, "shift": shift}

    default_threshold: float = float(filters.get("threshold_minutes", 5))
    per_type_thresholds: Dict[str, float] = filters.get("thresholds", {})

    conn = _get_conn()

    clauses: List[str] = []
    params: List[Any] = []

    if filters.get("date_start"):
        clauses.append("i.created >= ?")
        params.append(filters["date_start"])
    if filters.get("date_end"):
        clauses.append("i.created < ?")
        params.append(filters["date_end"])
    if filters.get("shift"):
        clauses.append("i.shift = ?")
        params.append(filters["shift"])
    if filters.get("incident_type"):
        clauses.append("i.type = ?")
        params.append(filters["incident_type"])

    where = " AND ".join(clauses) if clauses else "1=1"

    # For each incident, find the earliest unit arrival.
    incident_rows = _rows_to_dicts(
        conn.execute(
            f"""
            SELECT i.incident_id, i.incident_number, i.type, i.location,
                   i.priority, i.status, i.created, i.shift,
                   (SELECT MIN(ua.arrived) FROM UnitAssignments ua
                    WHERE ua.incident_id = i.incident_id AND ua.arrived IS NOT NULL
                   ) AS first_arrival,
                   (SELECT ua.unit_id FROM UnitAssignments ua
                    WHERE ua.incident_id = i.incident_id AND ua.arrived IS NOT NULL
                    ORDER BY ua.arrived ASC LIMIT 1
                   ) AS first_unit
            FROM Incidents i
            WHERE {where}
            ORDER BY i.created ASC
            """,
            params,
        ).fetchall()
    )

    conn.close()

    # --- Evaluate each incident ----------------------------------------------
    rows: List[Dict[str, Any]] = []
    pass_count = 0
    fail_count = 0
    no_data_count = 0
    issues_found: List[Dict[str, Any]] = []

    for inc in incident_rows:
        inc_type = inc.get("type") or "UNKNOWN"
        threshold = per_type_thresholds.get(inc_type, default_threshold)
        response_min = _minutes_between(inc.get("created"), inc.get("first_arrival"))

        if response_min is None:
            result = "NO_DATA"
            no_data_count += 1
        elif response_min <= threshold:
            result = "PASS"
            pass_count += 1
        else:
            result = "FAIL"
            fail_count += 1
            issues_found.append({
                "source": "compliance",
                "id": inc["incident_id"],
                "number": inc.get("incident_number"),
                "timestamp": inc.get("created"),
                "description": (
                    f"Response {response_min:.1f} min > {threshold:.1f} min threshold "
                    f"for {inc_type} at {inc.get('location', 'N/A')}"
                ),
            })

        rows.append({
            "incident_id": inc["incident_id"],
            "incident_number": inc.get("incident_number"),
            "type": inc_type,
            "location": inc.get("location"),
            "priority": inc.get("priority"),
            "created": inc.get("created"),
            "first_arrival": inc.get("first_arrival"),
            "first_unit": inc.get("first_unit"),
            "response_minutes": response_min,
            "threshold_minutes": threshold,
            "result": result,
        })

    total_evaluated = pass_count + fail_count
    compliance_rate = round(pass_count / total_evaluated * 100, 1) if total_evaluated > 0 else None

    stats = {
        "total_incidents": len(rows),
        "evaluated": total_evaluated,
        "pass": pass_count,
        "fail": fail_count,
        "no_data": no_data_count,
        "compliance_rate_pct": compliance_rate,
        "threshold_default_min": default_threshold,
    }

    return {
        "rows": rows,
        "stats": stats,
        "metadata": {
            "title": "Response-Time Compliance Report",
            "template_key": "response_compliance",
            "date_range": [start, end],
            "shift": shift,
            "generated_at": format_time_for_display(),
            "timezone": str(get_timezone()),
        },
        "incidents": incident_rows,
        "daily_log": [],
        "issues_found": issues_found,
    }


def _extract_custom_template(template_key: str, filters: Dict[str, Any]) -> Dict[str, Any]:
    """Extract data for a custom (builder-created) template.

    The template's *default_config_json* is expected to contain a
    ``base_template`` key that names one of the built-in extractors.
    Additional config keys are merged into *filters* so the base
    extractor sees them.
    """

    tpl = TemplateRepository.get_by_key(template_key)
    if tpl is None:
        return {
            "rows": [],
            "stats": {"error": f"Template '{template_key}' not found"},
            "metadata": {
                "title": f"Unknown template: {template_key}",
                "template_key": template_key,
                "date_range": [None, None],
                "shift": None,
                "generated_at": format_time_for_display(),
                "timezone": str(get_timezone()),
            },
            "incidents": [],
            "daily_log": [],
            "issues_found": [],
        }

    try:
        config = json.loads(tpl.default_config_json)
    except (json.JSONDecodeError, TypeError):
        config = {}

    base_key = config.pop("base_template", "blotter")
    merged_filters = {**config, **filters}

    extractor = _TEMPLATE_REGISTRY.get(base_key, _extract_blotter)
    data = extractor(merged_filters)

    # Override metadata title with the custom template name.
    data["metadata"]["title"] = tpl.name
    data["metadata"]["template_key"] = template_key
    return data


# ============================================================================
# Template Registry
# ============================================================================

_TEMPLATE_REGISTRY: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "blotter": _extract_blotter,
    "incident_summary": _extract_incident_summary,
    "unit_response_stats": _extract_unit_response_stats,
    "calltaker_stats": _extract_calltaker_stats,
    "shift_workload": _extract_shift_workload,
    "response_compliance": _extract_response_compliance,
}


def get_extractor(template_key: str) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """Return the data-extraction function for *template_key*.

    Keys prefixed with ``custom:`` are routed through the custom-template
    loader which reads the stored configuration and delegates to a base
    extractor.
    """
    if template_key.startswith("custom:"):
        return lambda filters: _extract_custom_template(template_key, filters)
    return _TEMPLATE_REGISTRY.get(template_key, _extract_blotter)


# ============================================================================
# Report Engine
# ============================================================================

class ReportEngine:
    """Orchestrates report generation, rendering, and delivery.

    Public surface
    --------------
    * ``run_report(template_key, filters, formats, created_by)`` -- generate
      a report run end-to-end.
    * ``deliver_report(run_id, channels)`` -- deliver an existing run to one
      or more channels.
    * ``generate_report(report_type, shift, date, ...)`` -- **legacy** method
      kept for backward compatibility with routes.py / scheduler.py.
    """

    def __init__(self):
        self.email_delivery = EmailDelivery()
        self.sms_delivery = SMSDelivery()
        self.webhook_delivery = WebhookDelivery()

    # ------------------------------------------------------------------ #
    # NEW:  run_report  (template-driven)
    # ------------------------------------------------------------------ #

    def run_report(
        self,
        template_key: str,
        filters: Optional[Dict[str, Any]] = None,
        formats: Optional[List[str]] = None,
        created_by: str = "system",
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute a full report run.

        1. Create a ``report_runs`` row with status='running'.
        2. Extract data via the template function.
        3. Render each requested format (html, pdf, csv, json).
        4. Save artifacts and update the run row.
        5. Return ``{ run_id, status, artifact_paths, download_tokens }``.
        """
        if filters is None:
            filters = {}
        if formats is None:
            formats = ["html"]

        # 1. Create the run entry.
        run = ReportRun(
            template_key=template_key,
            title=title or f"Report: {template_key}",
            filters_json=json.dumps(filters),
            format_json=json.dumps(formats),
            created_by=created_by,
            status="running",
        )
        run_id = RunRepository.create(run)

        try:
            # 2. Extract data.
            extractor = get_extractor(template_key)
            data = extractor(filters)

            # 3. Render each format and persist artifacts.
            artifact_dir = ensure_artifact_dir(run_id)
            artifact_paths: Dict[str, str] = {}

            for fmt in formats:
                rendered = self._render(fmt, data)
                if rendered is not None:
                    ext = fmt if fmt != "html" else "html"
                    filename = f"report_{run_id}.{ext}"
                    artifact_path = artifact_dir / filename
                    artifact_path.write_text(rendered, encoding="utf-8")
                    artifact_paths[fmt] = str(artifact_path)

            # 4. Build summary text.
            stats = data.get("stats", {})
            meta = data.get("metadata", {})
            summary_parts = [
                meta.get("title", template_key),
                f"Date range: {meta.get('date_range', ['?', '?'])}",
            ]
            for k, v in stats.items():
                summary_parts.append(f"{k}: {v}")
            summary_text = " | ".join(summary_parts)

            # 5. Persist.
            RunRepository.save_artifacts(run_id, artifact_paths)
            RunRepository.save_summary(run_id, summary_text)
            RunRepository.update_status(run_id, "completed")

            # Audit
            AuditRepository.log(
                action="report_run_completed",
                category="reports",
                user_name=created_by,
                details=f"Run {run_id} ({template_key}) completed",
            )

            download_tokens: Dict[str, str] = {}
            for fmt, path in artifact_paths.items():
                download_tokens[fmt] = make_download_token(run_id, fmt)

            return {
                "ok": True,
                "run_id": run_id,
                "status": "completed",
                "artifact_paths": artifact_paths,
                "download_tokens": download_tokens,
                "summary": summary_text,
                "data": data,
            }

        except Exception as exc:
            error_text = f"{exc.__class__.__name__}: {exc}\n{traceback.format_exc()}"
            logger.error("Report run %d failed: %s", run_id, error_text)
            RunRepository.update_status(run_id, "failed", error=error_text)

            AuditRepository.log(
                action="report_run_failed",
                category="reports",
                user_name=created_by,
                details=f"Run {run_id} ({template_key}) failed: {exc}",
            )

            return {
                "ok": False,
                "run_id": run_id,
                "status": "failed",
                "error": str(exc),
                "artifact_paths": {},
                "download_tokens": {},
                "summary": "",
                "data": {},
            }

    # ------------------------------------------------------------------ #
    # NEW:  deliver_report
    # ------------------------------------------------------------------ #

    def deliver_report(
        self,
        run_id: int,
        channels: List[Dict[str, str]],
        triggered_by: str = "manual",
    ) -> Dict[str, Any]:
        """Send an existing report_run to the specified channels.

        *channels* is a list of dicts, each with at least:
            ``{"channel": "email"|"sms"|"webhook", "destination": "..."}``

        Returns summary of delivery attempts.
        """
        run = RunRepository.get_by_id(run_id)
        if run is None:
            return {"ok": False, "error": f"Report run {run_id} not found"}

        if run.status != "completed":
            return {"ok": False, "error": f"Run {run_id} status is '{run.status}', expected 'completed'"}

        # Load artifact paths
        try:
            artifact_paths: Dict[str, str] = json.loads(run.artifact_paths_json)
        except (json.JSONDecodeError, TypeError):
            artifact_paths = {}

        # Prefer HTML content for email body, fall back to summary text.
        html_path = artifact_paths.get("html")
        html_body = ""
        if html_path:
            try:
                html_body = Path(html_path).read_text(encoding="utf-8")
            except OSError:
                html_body = ""

        subject = f"[FORD CAD] {run.title}"

        results: List[Dict[str, Any]] = []
        success_count = 0
        fail_count = 0

        for ch in channels:
            channel_type = ch.get("channel", "email")
            destination = ch.get("destination", "")

            # Create delivery record.
            delivery = ReportDelivery(
                report_run_id=run_id,
                channel=channel_type,
                destination=destination,
                status="sending",
            )
            delivery_id = DeliveryRepository.create(delivery)

            try:
                if channel_type == "email":
                    result = self.email_delivery.send(
                        recipient=destination,
                        subject=subject,
                        body_text=run.summary_text or "See attached report.",
                        body_html=html_body or None,
                    )
                elif channel_type == "sms":
                    result = self.sms_delivery.send(
                        recipient=destination,
                        subject=subject,
                        body_text=run.summary_text or "Report ready.",
                    )
                elif channel_type == "webhook":
                    result = self.webhook_delivery.send(
                        recipient=destination,
                        subject=subject,
                        body_text=run.summary_text or "",
                    )
                else:
                    from .delivery.base import DeliveryResult
                    result = DeliveryResult(
                        success=False,
                        recipient=destination,
                        channel=channel_type,
                        error=f"Unknown channel: {channel_type}",
                    )

                status = "sent" if result.success else "failed"
                DeliveryRepository.update_status(
                    delivery_id,
                    status=status,
                    error=result.error,
                    msg_id=getattr(result, "message_id", None),
                )

                if result.success:
                    success_count += 1
                else:
                    fail_count += 1

                results.append({
                    "delivery_id": delivery_id,
                    "channel": channel_type,
                    "destination": destination,
                    "status": status,
                    "error": result.error,
                })

            except Exception as exc:
                fail_count += 1
                DeliveryRepository.update_status(delivery_id, status="failed", error=str(exc))
                results.append({
                    "delivery_id": delivery_id,
                    "channel": channel_type,
                    "destination": destination,
                    "status": "failed",
                    "error": str(exc),
                })

        AuditRepository.log(
            action="report_delivered",
            category="reports",
            user_name=triggered_by,
            details=(
                f"Run {run_id} delivered to {len(channels)} channels "
                f"(ok={success_count}, fail={fail_count})"
            ),
        )

        return {
            "ok": success_count > 0 or fail_count == 0,
            "run_id": run_id,
            "deliveries": results,
            "successful": success_count,
            "failed": fail_count,
        }

    # ------------------------------------------------------------------ #
    # Rendering helpers
    # ------------------------------------------------------------------ #

    def _render(self, fmt: str, data: Dict[str, Any]) -> Optional[str]:
        """Render extracted data into the requested format string.

        If a ``ReportRenderer`` class is available it is preferred; otherwise
        the engine falls back to built-in formatters for html / json / csv.
        """
        if ReportRenderer is not None:
            try:
                renderer = ReportRenderer()
                return renderer.render(fmt, data)
            except Exception:
                logger.debug("ReportRenderer.render(%s) failed, falling back", fmt, exc_info=True)

        if fmt == "json":
            return json.dumps(data, indent=2, default=str)
        if fmt == "csv":
            return self._render_csv(data)
        if fmt == "html":
            return self._render_html(data)
        # Unknown format -- return JSON as fallback.
        return json.dumps(data, indent=2, default=str)

    @staticmethod
    def _render_csv(data: Dict[str, Any]) -> str:
        """Minimal CSV renderer for the rows list."""
        rows = data.get("rows", [])
        if not rows:
            return ""
        import csv
        import io

        buf = io.StringIO()
        # Use keys of the first row as header.
        fieldnames = list(rows[0].keys())
        writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            # Flatten any nested dicts/lists to JSON strings for CSV safety.
            flat = {}
            for k, v in row.items():
                if isinstance(v, (dict, list)):
                    flat[k] = json.dumps(v, default=str)
                else:
                    flat[k] = v
            writer.writerow(flat)
        return buf.getvalue()

    @staticmethod
    def _render_html(data: Dict[str, Any]) -> str:
        """Built-in HTML renderer producing a self-contained report page."""
        meta = data.get("metadata", {})
        stats = data.get("stats", {})
        rows = data.get("rows", [])
        issues = data.get("issues_found", [])

        title = meta.get("title", "FORD CAD Report")
        date_range = meta.get("date_range", ["", ""])
        shift = meta.get("shift")
        generated = meta.get("generated_at", "")
        bc_name = meta.get("battalion_chief", "")

        # Stats boxes
        stats_html_parts = []
        for key, val in stats.items():
            if isinstance(val, dict):
                continue
            label = key.replace("_", " ").title()
            stats_html_parts.append(
                f'<div class="stat-box"><div class="stat-val">{val}</div>'
                f'<div class="stat-label">{label}</div></div>'
            )
        stats_html = "".join(stats_html_parts)

        # Issues section
        issues_html = ""
        if issues:
            issue_rows_html = ""
            for iss in issues:
                issue_rows_html += (
                    f'<tr><td>{iss.get("timestamp", "-")}</td>'
                    f'<td>{iss.get("source", "-")}</td>'
                    f'<td>{iss.get("number") or iss.get("id", "-")}</td>'
                    f'<td>{iss.get("description", "")}</td></tr>'
                )
            issues_html = f"""
            <div class="issues-box">
                <h2>Issues Flagged ({len(issues)})</h2>
                <table><tr><th>Time</th><th>Source</th><th>ID</th><th>Description</th></tr>
                {issue_rows_html}</table>
            </div>"""

        # Data table
        table_html = ""
        if rows:
            # Build header from first row
            headers = [k for k in rows[0].keys() if not isinstance(rows[0][k], (dict, list))]
            header_row = "".join(f"<th>{h.replace('_', ' ').title()}</th>" for h in headers)
            body_rows = ""
            for row in rows[:500]:  # Cap at 500 for performance
                cells = ""
                for h in headers:
                    v = row.get(h, "")
                    if v is None:
                        v = ""
                    cells += f"<td>{v}</td>"
                body_rows += f"<tr>{cells}</tr>"

            table_html = f"""
            <h2>Data ({len(rows)} rows)</h2>
            <div style="overflow-x:auto;">
                <table><tr>{header_row}</tr>{body_rows}</table>
            </div>"""

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{ font-family: Arial, Helvetica, sans-serif; margin: 0; padding: 0; background: #f3f4f6; }}
  .container {{ max-width: 960px; margin: 0 auto; padding: 20px; }}
  .header {{ background: linear-gradient(135deg, #1e40af, #3b82f6); color: #fff; padding: 24px; border-radius: 10px 10px 0 0; }}
  .header h1 {{ margin: 0; font-size: 22px; }}
  .header p {{ margin: 4px 0 0; opacity: 0.85; font-size: 14px; }}
  .body {{ background: #fff; padding: 24px; border-radius: 0 0 10px 10px; box-shadow: 0 2px 8px rgba(0,0,0,.08); }}
  .meta {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 20px; }}
  .meta span {{ background: #f3f4f6; padding: 6px 12px; border-radius: 6px; font-size: 13px; }}
  .stats {{ display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 24px; }}
  .stat-box {{ flex: 1; min-width: 120px; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px; padding: 14px; text-align: center; }}
  .stat-val {{ font-size: 26px; font-weight: bold; color: #1e40af; }}
  .stat-label {{ font-size: 11px; color: #6b7280; margin-top: 2px; }}
  .issues-box {{ background: #fef2f2; border: 2px solid #dc2626; border-radius: 8px; padding: 16px; margin-bottom: 20px; }}
  .issues-box h2 {{ color: #dc2626; margin: 0 0 10px; font-size: 16px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ background: #e5e7eb; text-align: left; padding: 8px; border: 1px solid #d1d5db; }}
  td {{ padding: 8px; border: 1px solid #e5e7eb; }}
  tr:nth-child(even) {{ background: #f9fafb; }}
  .footer {{ text-align: center; color: #9ca3af; font-size: 11px; margin-top: 20px; padding: 12px 0; }}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>Ford Fire Department</h1>
        <p>{title}</p>
    </div>
    <div class="body">
        <div class="meta">
            <span><strong>Period:</strong> {date_range[0]} &mdash; {date_range[1]}</span>
            {"<span><strong>Shift:</strong> " + shift + "</span>" if shift else ""}
            {"<span><strong>BC:</strong> " + bc_name + "</span>" if bc_name else ""}
        </div>
        <div class="stats">{stats_html}</div>
        {issues_html}
        {table_html}
        <div class="footer">Generated: {generated} | FORD CAD Reporting System</div>
    </div>
</div>
</body>
</html>"""

    # ================================================================== #
    # LEGACY interface  (used by routes.py / scheduler.py)
    # ================================================================== #

    def generate_report(
        self,
        report_type: str = "shift_end",
        shift: str = None,
        date: datetime = None,
        start_date: datetime = None,
        end_date: datetime = None,
    ) -> Dict[str, Any]:
        """Legacy entry point.  Maps old report_type names to template keys."""

        _type_to_template = {
            "shift_end": "blotter",
            "daily_summary": "blotter",
            "weekly": "blotter",
            "custom": "blotter",
            "incident_summary": "incident_summary",
            "unit_response_stats": "unit_response_stats",
            "calltaker_stats": "calltaker_stats",
            "shift_workload": "shift_workload",
            "response_compliance": "response_compliance",
        }
        template_key = _type_to_template.get(report_type, "blotter")

        filters: Dict[str, Any] = {}
        if shift:
            filters["shift"] = shift

        fmt = "%Y-%m-%d %H:%M:%S"
        if start_date:
            filters["date_start"] = start_date.strftime(fmt) if isinstance(start_date, datetime) else str(start_date)
        if end_date:
            filters["date_end"] = end_date.strftime(fmt) if isinstance(end_date, datetime) else str(end_date)

        if date is not None and not start_date and not end_date:
            if report_type == "weekly":
                filters["date_start"] = (date - timedelta(days=7)).strftime(fmt)
                filters["date_end"] = date.strftime(fmt)
            elif report_type == "daily_summary":
                filters["date_start"] = (date - timedelta(days=1)).strftime(fmt)
                filters["date_end"] = date.strftime(fmt)
            # shift_end and custom use shift-based defaults (handled by extractor).

        extractor = get_extractor(template_key)
        data = extractor(filters)

        # Re-shape into the format the legacy HTML formatter expects.
        return self._reshape_legacy(data, report_type, shift, date)

    def _reshape_legacy(
        self,
        data: Dict[str, Any],
        report_type: str,
        shift: Optional[str],
        date: Optional[datetime],
    ) -> Dict[str, Any]:
        """Map new-style data dict back to the shape routes.py expects."""
        meta = data.get("metadata", {})
        stats = data.get("stats", {})
        incidents = data.get("incidents", [])
        daily_log = data.get("daily_log", [])
        issues_found = data.get("issues_found", [])

        if date is None:
            date = get_local_now()

        shift = shift or meta.get("shift") or get_current_shift(date)
        bc_info = BATTALION_CHIEFS.get(shift, {})

        date_range = meta.get("date_range", [None, None])
        start_time = date_range[0][-8:-3] if date_range[0] and len(date_range[0]) >= 8 else "06:00"
        end_time = date_range[1][-8:-3] if date_range[1] and len(date_range[1]) >= 8 else "18:00"

        return {
            "report_type": report_type,
            "shift": shift,
            "date": date.strftime("%Y-%m-%d") if isinstance(date, datetime) else str(date),
            "start_time": start_time,
            "end_time": end_time,
            "timezone": str(get_timezone()),
            "battalion_chief": bc_info.get("name", "Unknown"),
            "incidents": incidents,
            "daily_log": daily_log,
            "issues_found": issues_found,
            "stats": {
                "total_incidents": stats.get("incident_count", stats.get("total_incidents", len(incidents))),
                "open_incidents": stats.get("open_incidents", 0),
                "closed_incidents": stats.get("closed_incidents", 0),
                "daily_log_entries": stats.get("daily_log_count", stats.get("daily_log_entries", len(daily_log))),
                "issues_found": stats.get("issues_count", stats.get("issues_found", len(issues_found))),
                "incidents_by_type": stats.get("incidents_by_type", {}),
            },
            "generated_at": format_time_for_display(),
        }

    # ------------------------------------------------------------------ #
    # Legacy HTML / text formatters  (used by send_report)
    # ------------------------------------------------------------------ #

    def format_report_html(self, report: Dict[str, Any]) -> str:
        """Format legacy report dict as HTML email."""
        report_type = report.get("report_type", "shift_end")
        if report_type == "shift_end":
            return self._format_shift_end_html(report)
        return self._format_generic_html(report)

    def _format_shift_end_html(self, report: Dict[str, Any]) -> str:
        """Format shift end report as HTML."""
        stats = report.get("stats", {})
        issues = report.get("issues_found", [])

        issues_html = ""
        if issues:
            issues_rows = ""
            for issue in issues:
                issues_rows += (
                    '<tr style="background:#fff5f5;">'
                    f'<td style="padding:8px;border:1px solid #e5e7eb;">{issue.get("timestamp", "-")}</td>'
                    f'<td style="padding:8px;border:1px solid #e5e7eb;">{issue.get("source", issue.get("type", "-"))}</td>'
                    f'<td style="padding:8px;border:1px solid #e5e7eb;">{issue.get("number") or issue.get("id", "-")}</td>'
                    f'<td style="padding:8px;border:1px solid #e5e7eb;">{issue.get("description", "")}</td>'
                    "</tr>"
                )
            issues_html = (
                '<div style="background:#fef2f2;border:2px solid #dc2626;border-radius:8px;padding:15px;margin:20px 0;">'
                f'<h2 style="color:#dc2626;margin-top:0;">Issues Flagged for Review ({len(issues)})</h2>'
                '<table style="width:100%;border-collapse:collapse;">'
                '<tr style="background:#fecaca;">'
                '<th style="padding:8px;border:1px solid #e5e7eb;text-align:left;">Time</th>'
                '<th style="padding:8px;border:1px solid #e5e7eb;text-align:left;">Type</th>'
                '<th style="padding:8px;border:1px solid #e5e7eb;text-align:left;">ID</th>'
                '<th style="padding:8px;border:1px solid #e5e7eb;text-align:left;">Description</th>'
                f"</tr>{issues_rows}</table></div>"
            )

        incidents_html = ""
        for inc in report.get("incidents", []):
            has_issue = inc.get("issue_found") == 1
            bg = "background:#fff5f5;" if has_issue else ""
            issue_badge = (
                '<span style="background:#dc2626;color:white;padding:2px 6px;'
                'border-radius:4px;font-size:11px;margin-left:8px;">ISSUE</span>'
                if has_issue else ""
            )
            incidents_html += (
                f'<div style="border:1px solid #e5e7eb;border-radius:8px;padding:15px;margin-bottom:15px;{bg}">'
                '<div style="display:flex;justify-content:space-between;margin-bottom:10px;">'
                f'<h3 style="margin:0;color:#1e40af;">#{inc.get("incident_number", inc.get("incident_id", ""))}'
                f' {issue_badge}</h3>'
                f'<span style="background:#e5e7eb;padding:4px 8px;border-radius:4px;font-size:12px;">'
                f'{inc.get("status", "N/A")}</span></div>'
                '<table style="width:100%;font-size:13px;">'
                f'<tr><td style="width:100px;color:#6b7280;">Type:</td><td><strong>{inc.get("type", "N/A")}</strong></td></tr>'
                f'<tr><td style="color:#6b7280;">Location:</td><td>{inc.get("location", "N/A")}</td></tr>'
                f'<tr><td style="color:#6b7280;">Created:</td><td>{inc.get("created", "N/A")}</td></tr>'
                "</table></div>"
            )

        if not report.get("incidents"):
            incidents_html = '<p style="text-align:center;color:#6b7280;padding:20px;">No incidents during this shift.</p>'

        issue_bg = "#fef2f2" if stats.get("issues_found", 0) > 0 else "#f3f4f6"
        issue_border = "#fecaca" if stats.get("issues_found", 0) > 0 else "#e5e7eb"
        issue_color = "#dc2626" if stats.get("issues_found", 0) > 0 else "#6b7280"

        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Shift End Report - {report.get('shift', '')} Shift</title></head>
<body style="font-family:Arial,sans-serif;max-width:900px;margin:0 auto;padding:20px;background:#f9fafb;">
<div style="background:white;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,0.1);overflow:hidden;">
<div style="background:linear-gradient(135deg,#1e40af,#3b82f6);color:white;padding:25px;">
<h1 style="margin:0;font-size:24px;">Ford Fire Department</h1>
<p style="margin:5px 0 0;opacity:0.9;font-size:16px;">End of Shift Report</p></div>
<div style="padding:25px;">
<div style="display:flex;gap:20px;margin-bottom:20px;flex-wrap:wrap;">
<div style="background:#f3f4f6;padding:10px 15px;border-radius:6px;"><strong>Shift:</strong> {report.get('shift', '')}</div>
<div style="background:#f3f4f6;padding:10px 15px;border-radius:6px;"><strong>Date:</strong> {report.get('date', '')}</div>
<div style="background:#f3f4f6;padding:10px 15px;border-radius:6px;"><strong>Period:</strong> {report.get('start_time', '')} - {report.get('end_time', '')}</div>
<div style="background:#f3f4f6;padding:10px 15px;border-radius:6px;"><strong>BC:</strong> {report.get('battalion_chief', 'N/A')}</div>
</div>
<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:15px;margin-bottom:25px;">
<div style="background:#eff6ff;border:1px solid #bfdbfe;padding:15px;border-radius:8px;text-align:center;">
<div style="font-size:28px;font-weight:bold;color:#1e40af;">{stats.get('total_incidents', 0)}</div>
<div style="font-size:12px;color:#6b7280;">Total Incidents</div></div>
<div style="background:#f0fdf4;border:1px solid #bbf7d0;padding:15px;border-radius:8px;text-align:center;">
<div style="font-size:28px;font-weight:bold;color:#16a34a;">{stats.get('closed_incidents', 0)}</div>
<div style="font-size:12px;color:#6b7280;">Closed</div></div>
<div style="background:#fefce8;border:1px solid #fef08a;padding:15px;border-radius:8px;text-align:center;">
<div style="font-size:28px;font-weight:bold;color:#ca8a04;">{stats.get('daily_log_entries', 0)}</div>
<div style="font-size:12px;color:#6b7280;">Daily Log</div></div>
<div style="background:{issue_bg};border:1px solid {issue_border};padding:15px;border-radius:8px;text-align:center;">
<div style="font-size:28px;font-weight:bold;color:{issue_color};">{stats.get('issues_found', 0)}</div>
<div style="font-size:12px;color:#6b7280;">Issues</div></div>
</div>
{issues_html}
<h2 style="color:#374151;border-bottom:2px solid #e5e7eb;padding-bottom:10px;margin-top:30px;">Incidents ({len(report.get('incidents', []))})</h2>
{incidents_html}
<div style="margin-top:30px;padding-top:20px;border-top:1px solid #e5e7eb;text-align:center;color:#6b7280;font-size:12px;">
<p>Generated: {report.get('generated_at', '')}</p>
<p>This report was automatically generated by FORD CAD System.</p></div>
</div></div></body></html>"""

    @staticmethod
    def _format_generic_html(report: Dict[str, Any]) -> str:
        return (
            '<!DOCTYPE html><html><head><title>Report</title></head>'
            '<body style="font-family:Arial,sans-serif;padding:20px;">'
            f'<h1>FORD CAD Report</h1>'
            f'<p>Report Type: {report.get("report_type", "unknown")}</p>'
            f'<p>Generated: {report.get("generated_at", "")}</p>'
            "</body></html>"
        )

    def format_report_text(self, report: Dict[str, Any]) -> str:
        """Format report as plain text."""
        lines = [
            "=" * 70,
            "FORD FIRE DEPARTMENT - SHIFT END REPORT",
            "=" * 70,
            f"Shift: {report.get('shift')} | Date: {report.get('date')}",
            f"Period: {report.get('start_time')} - {report.get('end_time')}",
            f"Battalion Chief: {report.get('battalion_chief', 'N/A')}",
            f"Generated: {report.get('generated_at', '')}",
            "",
        ]

        stats = report.get("stats", {})
        lines += [
            "-" * 50,
            "SUMMARY",
            "-" * 50,
            f"Total Incidents:    {stats.get('total_incidents', 0)}",
            f"  - Closed:         {stats.get('closed_incidents', 0)}",
            f"Daily Log Entries:  {stats.get('daily_log_entries', 0)}",
            f"Issues Flagged:     {stats.get('issues_found', 0)}",
            "",
        ]

        if report.get("issues_found"):
            lines += ["-" * 50, "*** ISSUES FLAGGED FOR REVIEW ***", "-" * 50]
            for issue in report["issues_found"]:
                lines.append(f"  [{issue.get('source', issue.get('type', '?'))}] "
                             f"{issue.get('number') or issue.get('id', 'N/A')}")
                lines.append(f"    {issue.get('description', '')}")
                lines.append("")

        lines += ["=" * 70, "END OF REPORT", "=" * 70]
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # Legacy send_report  (used by scheduler / routes)
    # ------------------------------------------------------------------ #

    def send_report(
        self,
        schedule_id: int = None,
        shift: str = None,
        triggered_by: str = "manual",
        triggered_by_user: str = None,
    ) -> Dict[str, Any]:
        """Generate and send a report (legacy interface)."""
        from .models import (
            RecipientRepository,
            HistoryRepository,
            DeliveryLogRepository,
            ReportHistoryEntry,
        )
        from .delivery import DeliveryResult

        now = get_local_now()
        if shift is None:
            shift = get_current_shift(now)

        report = self.generate_report(report_type="shift_end", shift=shift)
        html_report = self.format_report_html(report)
        text_report = self.format_report_text(report)

        recipients = RecipientRepository.get_by_shift(shift)
        if not recipients:
            recipients = RecipientRepository.get_all()
            recipients = [r for r in recipients if r.enabled]

        history_entry = ReportHistoryEntry(
            schedule_id=schedule_id,
            report_type="shift_end",
            shift=shift,
            status="sending",
            recipients_count=len(recipients),
            triggered_by=triggered_by,
            triggered_by_user=triggered_by_user,
        )
        history_id = HistoryRepository.create(history_entry)
        HistoryRepository.save_report_data(history_id, report)

        successful = 0
        failed = 0
        errors: List[str] = []

        subject = f"[FORD CAD] Shift End Report - {shift} Shift - {report['date']}"

        for recipient in recipients:
            log_id = DeliveryLogRepository.create(
                history_id=history_id,
                recipient=recipient.destination,
                name=recipient.name,
                channel=recipient.recipient_type,
            )

            if recipient.recipient_type == "email":
                result = self.email_delivery.send(
                    recipient=recipient.destination,
                    subject=subject,
                    body_text=text_report,
                    body_html=html_report,
                )
            elif recipient.recipient_type == "sms":
                result = self.sms_delivery.send(
                    recipient=recipient.destination,
                    subject=subject,
                    body_text=(
                        f"FORD CAD: {shift} Shift Report - "
                        f"{report['stats']['total_incidents']} incidents, "
                        f"{report['stats']['issues_found']} issues"
                    ),
                )
            elif recipient.recipient_type == "webhook":
                result = self.webhook_delivery.send(
                    recipient=recipient.destination,
                    subject=subject,
                    body_text=text_report,
                )
            else:
                result = DeliveryResult(
                    success=False,
                    recipient=recipient.destination,
                    channel=recipient.recipient_type,
                    error=f"Unknown channel type: {recipient.recipient_type}",
                )

            DeliveryLogRepository.update_status(
                log_id,
                status="sent" if result.success else "failed",
                error=result.error,
            )

            if result.success:
                successful += 1
            else:
                failed += 1
                if result.error:
                    errors.append(result.error)

        final_status = "sent" if failed == 0 else ("partial" if successful > 0 else "failed")
        HistoryRepository.update_status(
            history_id,
            status=final_status,
            successful=successful,
            failed=failed,
            error="; ".join(errors) if errors else None,
        )

        logger.info(
            "Report sent: shift=%s, recipients=%d, successful=%d, failed=%d",
            shift, len(recipients), successful, failed,
        )

        return {
            "ok": successful > 0,
            "history_id": history_id,
            "shift": shift,
            "recipients": len(recipients),
            "successful": successful,
            "failed": failed,
            "errors": errors if errors else None,
        }


# ============================================================================
# Module-level singleton
# ============================================================================

_engine: Optional[ReportEngine] = None


def get_engine() -> ReportEngine:
    """Return (or create) the global ReportEngine singleton."""
    global _engine
    if _engine is None:
        _engine = ReportEngine()
    return _engine
