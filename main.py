# ============================================================================
# BOSK-CAD — PHASE-3 STABILIZATION (PASS 2)
# ============================================================================
# Status:
#   Phase-3 backend stabilized for audit.
#
# Guarantees:
#   - Single canonical route per endpoint (enforced by consolidation review)
#   - Single remark engine
#   - Single narrative schema
#   - Single Daily Log writer
#   - Single dispatch pipeline
#
# Notes:
#   This file is the GOLD Phase-3 backend baseline for audit and UI work.
#   Legacy routes identified in PASS 1 are considered removed/merged
#   and must not be reintroduced.
#
# Dispatcher Stamp: T. Williams
# ============================================================================

# ============================================================================
# BOSK-CAD — PHASE-3 STABILIZATION (PASS 1)
# ============================================================================
# Purpose:
#   Canonical Core Extraction checkpoint.
#   - NO behavior changes
#   - NO routes removed yet
#   - File is now the authoritative working baseline for stabilization
#
# Next pass (PASS 2) will:
#   - Remove legacy routes
#   - Collapse duplicates
#   - Enforce single-route determinism
#
# Dispatcher Stamp: T. Williams
# ============================================================================

# ================================================================
# BOSK-CAD v3 — Phase-3 Core Backend
# Units + Mutual Aid + Canonical Ordering
# ================================================================

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from fastapi.templating import Jinja2Templates

from pathlib import Path
import sqlite3
import datetime
import os

# ================================================================
# PATHS
# ================================================================

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "cad.db"
TEMPLATES_DIR = BASE_DIR / "templates"

# ================================================================
# FASTAPI APP
# ================================================================

cad_app = FastAPI(title="BOSK-CAD Phase-3")
app = cad_app
cad_app.add_middleware(SessionMiddleware, secret_key="bosk-secret-key")

@app.on_event("startup")
async def _phase3_startup():
    # Ensure deterministic schema upgrades on boot (Phase-3).
    ensure_phase3_schema()
    masterlog("SYSTEM_STARTUP", user="SYSTEM", details="Ford CAD backend startup")


# Static files
cad_app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# Templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

from fastapi.responses import HTMLResponse
from fastapi import Request

# Define the root route (/) to serve the main dashboard page
@app.get("/", response_class=HTMLResponse)
async def root_view(request: Request):
    """
    The landing page of the CAD system. It attempts to load the main UI template.
    You must have a 'dashboard.html' or 'index.html' file in your 'templates' directory.
    """
    # Try to return your main interface template.
    # **NOTE: Change 'dashboard.html' to the actual filename of your main UI page.**
    main_template_file = "dashboard.html" 
    
    # Check if the templates directory and file exist (optional, but good practice)
    try:
        return templates.TemplateResponse(main_template_file, {
            "request": request, 
            "title": "Ford CAD Dispatch System",
            "today_date": datetime.datetime.now().strftime("%m/%d/%Y")
        })
    except Exception as e:
        # Fallback error for the browser
        return HTMLResponse(f"""
            <h1>500 Internal Error - Missing Template</h1>
            <p>The root route (/) is running, but it cannot find the required template file: 
            <strong>{main_template_file}</strong> in your <strong>templates</strong> directory.</p>
            <p>Error details: {e}</p>
        """)

# ================================================================
# DATABASE CONNECTION
# ================================================================

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ======================================================================
# BLOCK U0 — ONE-TIME UNIT IMPORTER (Reads UnitLog.txt → SQL Units)
# ======================================================================

UNITLOG_PATH = BASE_DIR / "UnitLog.txt"

# ======================================================
# PHASE-3 CANONICAL SCHEMA + LOGGING (PASS 15)
# ======================================================

_SCHEMA_INIT_DONE = False

def ensure_phase3_schema():
    """Create missing Phase-3 tables/columns in-place without destroying data."""
    global _SCHEMA_INIT_DONE
    if _SCHEMA_INIT_DONE:
        return

    conn = get_conn()
    c = conn.cursor()

    # -----------------------------
    # MASTERLOG (append-only, authoritative)
    # -----------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS MasterLog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            user TEXT,
            action TEXT NOT NULL,
            incident_id INTEGER,
            unit_id TEXT,
            ok INTEGER DEFAULT 1,
            reason TEXT,
            details TEXT
        )
    """)

    # -----------------------------
    # INCIDENT HISTORY (complete incident timeline)
    # -----------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS IncidentHistory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            user TEXT,
            event_type TEXT NOT NULL,
            unit_id TEXT,
            details TEXT
        )
    """)

    # -----------------------------
    # DAILY LOG (daily-only events; IssueFound applies here only)
    # -----------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS DailyLog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            user TEXT,
            incident_id INTEGER,
            unit_id TEXT,
            action TEXT NOT NULL,
            details TEXT,
            issue_found INTEGER DEFAULT 0
        )
    """)

    # -----------------------------
    # NARRATIVE (human remarks + explicitly allowed system messages)
    # -----------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS Narrative (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            entry_type TEXT,
            text TEXT NOT NULL,
            user TEXT,
            unit_id TEXT
        )
    """)

    conn.commit()
    _SCHEMA_INIT_DONE = True


def _ts():
    # Server/system time is authoritative
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def masterlog(action: str, user: str = None, incident_id=None, unit_id=None, ok: bool=True, reason: str=None, details: str=None):
    """Append-only MasterLog writer. Never raises; failures are swallowed to avoid losing ops."""
    try:
        ensure_phase3_schema()
        conn = get_conn()
        conn.execute(
            "INSERT INTO MasterLog (timestamp, user, action, incident_id, unit_id, ok, reason, details) VALUES (?,?,?,?,?,?,?,?)",
            (_ts(), user or "UNKNOWN_DISPATCHER", action, incident_id, unit_id, 1 if ok else 0, reason, details)
        )
        conn.commit()
    except Exception:
        # Last resort: never block ops because logging failed.
        pass

def incident_history(incident_id: int, event_type: str, user: str = None, unit_id: str = None, details: str = None):
    """IncidentHistory writer. All incident operational activity goes here."""
    try:
        ensure_phase3_schema()
        conn = get_conn()
        conn.execute(
            "INSERT INTO IncidentHistory (incident_id, timestamp, user, event_type, unit_id, details) VALUES (?,?,?,?,?,?)",
            (int(incident_id), _ts(), user or "UNKNOWN_DISPATCHER", event_type, unit_id, details)
        )
        conn.commit()
    except Exception:
        pass

def dailylog_event(event_type: str, details: str, user: str = None, issue_found: int = 0, incident_id=None, unit_id=None):
    """DailyLog writer. DailyLog is NOT a general event sink.
    incident_id/unit_id are supported for legacy compatibility but should be NULL for true DailyLog events."""
    try:
        ensure_phase3_schema()
        conn = get_conn()
        conn.execute(
            "INSERT INTO DailyLog (timestamp, user, incident_id, unit_id, action, details, issue_found) VALUES (?,?,?,?,?,?,?)",
            (_ts(), user or "UNKNOWN_DISPATCHER", incident_id, unit_id, event_type, details, int(issue_found))
        )
        conn.commit()
    except Exception:
        pass

def add_narrative(incident_id: int, user: str, text: str, entry_type: str = "REMARK", unit_id: str | None = None):
    """Canonical narrative writer.
    Narrative is human-entered by default; system narrative is permitted ONLY when explicitly called."""
    try:
        ensure_phase3_schema()
        conn = get_conn()
        conn.execute(
            "INSERT INTO Narrative (incident_id, timestamp, entry_type, text, user, unit_id) VALUES (?,?,?,?,?,?)",
            (int(incident_id), _ts(), entry_type, text, user or "UNKNOWN_DISPATCHER", unit_id)
        )
        conn.commit()
    except Exception:
        pass

def reject_and_log(action: str, reason: str, user: str=None, incident_id=None, unit_id=None, details: str=None):
    """Standardized failure logging."""
    masterlog(action, user=user, incident_id=incident_id, unit_id=unit_id, ok=False, reason=reason, details=details)
def units_table_is_empty() -> bool:
    """Returns True if Units table has zero entries."""
    conn = get_conn()
    c = conn.cursor()
    row = c.execute("SELECT COUNT(*) AS n FROM Units").fetchone()
    conn.close()
    return (row["n"] == 0)


def parse_unitlog_txt() -> list[dict]:
    r"""
    Reads C:\CAD-Sys\BOSK-CAD\UnitLog.txt
    Expected BOSK format: unit_id|name|type|icon
    Type determines flags:
        CMD  → command unit
        PER  → personnel unit
        APP  → apparatus
        MA   → mutual aid

    """
    units = []

    if not UNITLOG_PATH.exists():
        print("WARNING: UnitLog.txt not found — skipping import.")
        return units

    with open(UNITLOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = line.split("|")
            if len(parts) < 4:
                continue

            unit_id, name, utype, icon = parts[:4]

            # Flag resolution
            is_cmd = 1 if utype.upper() == "CMD" else 0
            is_app = 1 if utype.upper() == "APP" else 0
            is_ma  = 1 if utype.upper() == "MA"  else 0

            units.append({
                "unit_id": unit_id.strip(),
                "name": name.strip(),
                "unit_type": utype.upper().strip(),
                "icon": icon.strip(),
                "is_command": is_cmd,
                "is_apparatus": is_app,
                "is_mutual_aid": is_ma,
                "status": "AVAILABLE"
            })

    return units


def import_units_from_unitlog():
    """
    Performs a ONE-TIME import from UnitLog.txt into Units table.
    Also builds:
        ApparatusOrder
        CommandUnitsOrder
        MutualAidOrder
    Will NOT overwrite any existing data.
    """

    # If table already has units, do nothing.
    if not units_table_is_empty():
        print("[U0] Units table NOT empty — import skipped.")
        return

    print("[U0] Units table empty — importing from UnitLog.txt...")

    # Read file
    units = parse_unitlog_txt()
    if not units:
        print("[U0] No units found in UnitLog.txt — aborting import.")
        return

    conn = get_conn()
    c = conn.cursor()

    # Insert units
    for u in units:
        c.execute("""
            INSERT INTO Units (
                unit_id, name, unit_type, status,
                icon,
                is_apparatus, is_command, is_mutual_aid
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            u["unit_id"],
            u["name"],
            u["unit_type"],
            u["status"],
            u["icon"],
            u["is_apparatus"],
            u["is_command"],
            u["is_mutual_aid"]
        ))

    conn.commit()

    # ------------------------------
    # Build order tables
    # ------------------------------

    # 1. Command order
    cmd_units = [u["unit_id"] for u in units if u["is_command"]]
    for i, uid in enumerate(cmd_units):
        c.execute("""
            INSERT INTO CommandUnitsOrder (unit_id, sort_order)
            VALUES (?, ?)
        """, (uid, i+1))

    # 2. Personnel (not command, not apparatus, not mutual aid)
    #    Not stored in an order table; alphabetical.

    # 3. Apparatus order
    app_units = [u["unit_id"] for u in units if u["is_apparatus"]]
    for i, uid in enumerate(app_units):
        c.execute("""
            INSERT INTO ApparatusOrder (apparatus_id, sort_order)
            VALUES (?, ?)
        """, (uid, i+1))

    # 4. Mutual aid order — always last section in picker
    ma_units = [u["unit_id"] for u in units if u["is_mutual_aid"]]
    for i, uid in enumerate(ma_units):
        c.execute("""
            INSERT INTO MutualAidOrder (unit_id, sort_order)
            VALUES (?, ?)
        """, (uid, i+1))

    conn.commit()
    conn.close()

    print(f"[U0] Imported {len(units)} units from UnitLog.txt.")
    print("[U0] Command, Apparatus, and Mutual Aid ordering created.")


# Run importer BEFORE migrations
import_units_from_unitlog()
# ======================================================================
# BLOCK U1 — UNIT SYNC ENGINE (Keeps Units Table Synced With UnitLog.txt)
# ======================================================================

def load_unitlog_file() -> list[dict]:
    """
    Reads UnitLog.txt and returns a list of structured unit dictionaries.
    Expected format per line:
        UNIT_ID | NAME | TYPE | ICON | IS_COMMAND | IS_APPARATUS | IS_MUTUAL
    Unspecified fields default to safe values.
    """
    units = []

    if not UNITLOG_PATH.exists():
        return units

    with open(UNITLOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = [p.strip() for p in line.split("|")]

            # Base structure
            entry = {
                "unit_id": parts[0],
                "name": parts[1] if len(parts) > 1 else parts[0],
                "unit_type": parts[2].upper() if len(parts) > 2 else "PERSONNEL",
                "icon": parts[3] if len(parts) > 3 else "unknown.png",
                "is_command": int(parts[4]) if len(parts) > 4 else 0,
                "is_apparatus": int(parts[5]) if len(parts) > 5 else 0,
                "is_mutual_aid": int(parts[6]) if len(parts) > 6 else 0,
            }

            units.append(entry)

    return units


def sync_units_table():
    """
    Ensures SQL Units table stays aligned with UnitLog.txt WITHOUT
    overwriting live CAD operational state (status, timestamps, assignments).
    Only metadata fields are synced.

    Rules:
      - New units in the log → added to Units table.
      - Units removed from log → marked inactive (do NOT delete).
      - Status field is NEVER overwritten.
      - Apparatus/command/mutual flags are updated.
      - Icon/name/unit_type metadata is refreshed.
      - If a unit is currently assigned to an incident, it is protected.
    """
    log_units = load_unitlog_file()
    if not log_units:
        return  # Nothing to sync

    conn = get_conn()
    c = conn.cursor()

    # Fetch existing SQL units
    existing_rows = c.execute("""
        SELECT unit_id, status
        FROM Units
    """).fetchall()

    existing_ids = {row["unit_id"] for row in existing_rows}
    log_ids = {u["unit_id"] for u in log_units}

    # ----------------------------------------------------------
    # 1. Add missing units
    # ----------------------------------------------------------
    for u in log_units:
        if u["unit_id"] not in existing_ids:
            c.execute("""
                INSERT INTO Units (
                    unit_id, name, unit_type, status, last_updated,
                    icon, is_apparatus, is_command, is_mutual_aid
                )
                VALUES (?, ?, ?, 'AVAILABLE', ?, ?, ?, ?, ?)
            """, (
                u["unit_id"],
                u["name"],
                u["unit_type"],
                _ts(),
                u["icon"],
                u["is_apparatus"],
                u["is_command"],
                u["is_mutual_aid"]
            ))

    # ----------------------------------------------------------
    # 2. Update metadata for existing units (NOT status)
    # ----------------------------------------------------------
    for u in log_units:
        if u["unit_id"] in existing_ids:
            c.execute("""
                UPDATE Units
                SET name=?,
                    unit_type=?,
                    icon=?,
                    is_apparatus=?,
                    is_command=?,
                    is_mutual_aid=?
                WHERE unit_id=?
            """, (
                u["name"],
                u["unit_type"],
                u["icon"],
                u["is_apparatus"],
                u["is_command"],
                u["is_mutual_aid"],
                u["unit_id"]
            ))

    # ----------------------------------------------------------
    # 3. Units removed from log → mark inactive (do not delete)
    # ----------------------------------------------------------
    removed_ids = existing_ids - log_ids

    for uid in removed_ids:
        # NEVER delete or affect units currently on incidents
        assigned = c.execute("""
            SELECT 1 FROM UnitAssignments
            WHERE unit_id=? AND cleared IS NULL
        """, (uid,)).fetchone()

        if not assigned:
            c.execute("""
                UPDATE Units
                SET status='INACTIVE', last_updated=?
                WHERE unit_id=?
            """, (_ts(), uid))

    conn.commit()
    conn.close()


# Run sync at startup
if DB_PATH.exists():
    sync_units_table()
# ======================================================================
# BLOCK U2 — UNIT EDITOR WRITER (Writes unit roster back to UnitLog.txt)
# ======================================================================

def write_unitlog_file(units: list[dict]):
    """
    Writes the entire Units roster back to UnitLog.txt in canonical format.
    Only metadata is written — NOT status, NOT timestamps.
    """
    lines = []
    for u in units:
        line = " | ".join([
            u["unit_id"],
            u.get("name", u["unit_id"]),
            u.get("unit_type", "PERSONNEL"),
            u.get("icon", "unknown.png"),
            str(int(u.get("is_command", 0))),
            str(int(u.get("is_apparatus", 0))),
            str(int(u.get("is_mutual_aid", 0)))
        ])
        lines.append(line)

    with open(UNITLOG_PATH, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")


def fetch_units_metadata_only() -> list[dict]:
    """
    Returns ONLY metadata fields for writing UnitLog.txt.
    Does NOT include status or timestamps.
    """
    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT unit_id, name, unit_type, icon,
               COALESCE(is_command,0) AS is_command,
               COALESCE(is_apparatus,0) AS is_apparatus,
               COALESCE(is_mutual_aid,0) AS is_mutual_aid
        FROM Units
        WHERE status <> 'INACTIVE'
        ORDER BY unit_id ASC
    """).fetchall()

    conn.close()
    return [dict(r) for r in rows]


# ======================================================================
# INTERNAL — SAFE UPDATE CHECKS
# ======================================================================

def unit_is_assigned(unit_id: str) -> bool:
    """Returns True if the unit cannot be edited (currently active on an incident)."""
    conn = get_conn()
    c = conn.cursor()

    row = c.execute("""
        SELECT 1
        FROM UnitAssignments
        WHERE unit_id=? AND cleared IS NULL
        LIMIT 1
    """, (unit_id,)).fetchone()

    conn.close()
    return bool(row)


# ======================================================================
# UNIT EDIT ACTIONS
# ======================================================================

@app.post("/units/editor/update")
async def units_editor_update(request: Request):
    """
    Receives JSON from the Personnel/Unit Editor.

    Expected JSON:
        {
            "unit_id": "21",
            "name": "FF Johnson",
            "unit_type": "PERSONNEL",
            "icon": "ff.png",
            "is_command": 0,
            "is_apparatus": 0,
            "is_mutual_aid": 0
        }
    """

    data = await request.json()

    unit_id = data.get("unit_id", "").strip()
    if not unit_id:
        return {"ok": False, "error": "Missing unit_id"}

    if unit_is_assigned(unit_id):
        return {"ok": False, "error": "Unit is active on an incident — cannot modify"}

    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        UPDATE Units
        SET name=?,
            unit_type=?,
            icon=?,
            is_command=?,
            is_apparatus=?,
            is_mutual_aid=?
        WHERE unit_id=?
    """, (
        data.get("name", unit_id),
        data.get("unit_type", "PERSONNEL").upper(),
        data.get("icon", "unknown.png"),
        int(data.get("is_command", 0)),
        int(data.get("is_apparatus", 0)),
        int(data.get("is_mutual_aid", 0)),
        unit_id
    ))

    conn.commit()
    conn.close()

    # Rewrite UnitLog.txt
    units = fetch_units_metadata_only()
    write_unitlog_file(units)

    # Re-sync Units table
    sync_units_table()

    return {"ok": True}


@app.post("/units/editor/add")
async def units_editor_add(request: Request):
    """
    Adds a new unit to Units table AND UnitLog.txt.
    """
    data = await request.json()

    unit_id = data.get("unit_id", "").strip()
    if not unit_id:
        return {"ok": False, "error": "Missing unit_id"}

    conn = get_conn()
    c = conn.cursor()

    # Prevent duplicates
    exists = c.execute("""
        SELECT 1 FROM Units WHERE unit_id=?
    """, (unit_id,)).fetchone()

    if exists:
        conn.close()
        return {"ok": False, "error": "Unit already exists"}

    c.execute("""
        INSERT INTO Units (
            unit_id, name, unit_type, status, last_updated,
            icon, is_command, is_apparatus, is_mutual_aid
        )
        VALUES (?, ?, ?, 'AVAILABLE', ?, ?, ?, ?, ?)
    """, (
        unit_id,
        data.get("name", unit_id),
        data.get("unit_type", "PERSONNEL").upper(),
        _ts(),
        data.get("icon", "unknown.png"),
        int(data.get("is_command", 0)),
        int(data.get("is_apparatus", 0)),
        int(data.get("is_mutual_aid", 0))
    ))

    conn.commit()
    conn.close()

    # Write updates
    units = fetch_units_metadata_only()
    write_unitlog_file(units)
    sync_units_table()

    return {"ok": True}


@app.post("/units/editor/delete")
async def units_editor_delete(request: Request):
    """
    Safely removes a unit from UnitLog and Units table.
    Rules:
      • Cannot delete units assigned to an incident.
      • Unit is marked INACTIVE but NOT removed from DB if it has history.
    """
    data = await request.json()
    unit_id = data.get("unit_id", "").strip()

    if not unit_id:
        return {"ok": False, "error": "Missing unit_id"}

    if unit_is_assigned(unit_id):
        return {"ok": False, "error": "Cannot delete — unit is active on an incident"}

    conn = get_conn()
    c = conn.cursor()

    # Mark inactive in DB
    c.execute("""
        UPDATE Units
        SET status='INACTIVE', last_updated=?
        WHERE unit_id=?
    """, (_ts(), unit_id))

    conn.commit()
    conn.close()

    # Rewrite UnitLog excluding the deleted unit
    units = [u for u in fetch_units_metadata_only() if u["unit_id"] != unit_id]
    write_unitlog_file(units)

    sync_units_table()

    return {"ok": True}
# ======================================================================
# BLOCK U3 — REAL-TIME UNIT REFRESH ENGINE (PHASE-3)
# ======================================================================

@app.get("/api/units/refresh", response_class=HTMLResponse)
async def api_units_refresh(request: Request):
    """
    Returns a fully-rendered Units Panel HTML block.
    Called by HTMX after:
        • Unit added
        • Unit edited
        • Unit deleted
        • Unit icon changed
        • Unit flags toggled
    """
    units = get_units_for_panel()

    return templates.TemplateResponse(
        "units.html",
        {
            "request": request,
            "units": units
        }
    )


@app.get("/api/dispatch_picker/refresh/{incident_id}", response_class=HTMLResponse)
async def api_dispatch_picker_refresh(request: Request, incident_id: int):
    """
    Rebuilds all 4 Dispatch Picker lists:
        1. Command
        2. Personnel
        3. Apparatus
        4. Mutual Aid
    Guaranteed BOSK order.
    """

    units = fetch_units()
    groups = split_units_for_picker(units)

    return templates.TemplateResponse(
        "dispatch_picker.html",
        {
            "request": request,
            "incident_id": incident_id,
            "command_units": groups["command"],
            "personnel_units": groups["personnel"],
            "apparatus_units": groups["apparatus"],
            "mutual_aid_units": groups["mutual_aid"],
        }
    )


# ----------------------------------------------------------------------
# OPTIONAL: IAW metadata refresh (does NOT reload status or narrative)
# ----------------------------------------------------------------------
@app.get("/api/unit/{unit_id}/metadata_refresh", response_class=HTMLResponse)
async def api_unit_metadata_refresh(request: Request, unit_id: str):
    """
    Reloads unit metadata inside an open UAW when:
        • Name changed
        • Type changed
        • Icon changed
        • Flags changed (command/apparatus/mutual)
    Unit status is NOT changed here.
    """

    conn = get_conn()
    c = conn.cursor()
    row = c.execute("""
        SELECT unit_id, name, unit_type, status, last_updated,
               icon,
               COALESCE(is_apparatus,0) AS is_apparatus,
               COALESCE(is_command,0) AS is_command,
               COALESCE(is_mutual_aid,0) AS is_mutual_aid
        FROM Units
        WHERE unit_id=?
    """, (unit_id,)).fetchone()
    conn.close()

    if not row:
        return HTMLResponse("Unit not found", status_code=404)

    return templates.TemplateResponse(
        "unit_action_window.html",
        {
            "request": request,
            "unit": row
        }
    )

# ================================================================
# TIME HELPERS
# ================================================================

def _ts():
    return datetime.datetime.datetime.now().strftime("%m/%d/%Y %H:%M")

def today():
    return datetime.datetime.datetime.now().strftime("%m/%d/%Y")

def time__ts():
    return datetime.datetime.datetime.now().strftime("%H:%M")

def clean_status(s: str):
    return s.upper().strip() if s else ""

# ================================================================
# SHIFT / ROTATION LOGIC (CALENDAR SHIFT, NOT EMPLOYMENT)
# ================================================================

def determine_current_shift() -> str:
    """
    2-2-3 style calendar logic for BOSK:
      - Mon/Tue, Fri/Sat/Sun use A/B pair
      - Wed/Thu use C/D pair
      - 0600–1800 = day shift of pair
      - 1800–0600 = night shift of pair
    Returns: 'A', 'B', 'C', or 'D'
    """
    now_dt = datetime.datetime.datetime.now()
    weekday = now_dt.weekday()  # Monday=0
    hour = now_dt.hour

    if weekday in (0, 1, 4, 5, 6):
        pair = ("A", "B")
    else:
        pair = ("C", "D")

    if 6 <= hour < 18:
        return pair[0]
    else:
        return pair[1]

# ================================================================
# MUTUAL AID UNIT SEEDER (Units table, bottom of lists)
# ================================================================

def ensure_mutual_aid_units():
    """
    Make sure HCEMS-Medic and Hardin-Fire exist in Units table.
    They are marked is_mutual_aid = 1 and NEVER tied to shifts.
    """
    seed_units = [
        {
            "unit_id": "HCEMS-Medic",
            "name": "HCEMS Medic",
            "unit_type": "MUTUAL_AID",
            "status": "AVAILABLE",
            "icon": "hardinems.png",
            "is_apparatus": 0,
            "is_command": 0,
            "is_mutual_aid": 1
        },
        {
            "unit_id": "Hardin-Fire",
            "name": "Hardin Fire",
            "unit_type": "MUTUAL_AID",
            "status": "AVAILABLE",
            "icon": "apparatus.png",
            "is_apparatus": 0,
            "is_command": 0,
            "is_mutual_aid": 1
        }
    ]

    conn = get_conn()
    c = conn.cursor()

    # Try to add is_mutual_aid column if it doesn't exist yet
    try:
        c.execute("ALTER TABLE Units ADD COLUMN is_mutual_aid INTEGER DEFAULT 0")
        conn.commit()
    except Exception:
        # Column already exists or migration handled elsewhere
        pass

    for u in seed_units:
        row = c.execute(
            "SELECT 1 FROM Units WHERE unit_id = ?",
            (u["unit_id"],)
        ).fetchone()

        if not row:
            c.execute(
                """
                INSERT INTO Units (
                    unit_id, name, unit_type, status,
                    last_updated, icon,
                    is_apparatus, is_command, is_mutual_aid
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    u["unit_id"],
                    u["name"],
                    u["unit_type"],
                    u["status"],
                    _ts(),
                    u["icon"],
                    u["is_apparatus"],
                    u["is_command"],
                    u["is_mutual_aid"],
                )
            )

    conn.commit()
    conn.close()

# Call once at startup to guarantee they exist
if DB_PATH.exists():
    ensure_mutual_aid_units()

# ================================================================
# UNIT ORDER HELPERS (PANEL + PICKER)
# ================================================================

COMMAND_IDS = ["1578", "Car1", "Batt1", "Batt2", "Batt3", "Batt4"]

APPARATUS_ORDER = [
    "Engine2",
    "Medic2",
    "Engine1",
    "Medic1",
    "Tower1",
    "UTV1",
    "UTV2",
    "SQ1"
]

def fetch_units() -> list[dict]:
    """
    Pull all units from Units table as list of dicts.
    """
    conn = get_conn()
    c = conn.cursor()
    rows = c.execute("""
        SELECT unit_id, name, unit_type, status, last_updated,
               icon,
               COALESCE(is_apparatus, 0) AS is_apparatus,
               COALESCE(is_command, 0) AS is_command,
               COALESCE(is_mutual_aid, 0) AS is_mutual_aid
        FROM Units
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def split_units_for_picker(units: list[dict]) -> dict:
    """
    Returns dict with four ordered lists:
      - command
      - personnel
      - apparatus
      - mutual_aid
    ORDER IS:
      Command
      Personnel
      Apparatus
      Mutual Aid
    This is the BOSK-CAD canonical order — do not change.
    """
    command = []
    personnel = []
    apparatus = []
    mutual_aid = []

    # Normalize status/timestamps
    for u in units:
        u.setdefault("status", "AVAILABLE")
        u.setdefault("last_updated", "")

        uid = u.get("unit_id", "")
        utype = (u.get("unit_type") or "").upper()
        is_cmd = int(u.get("is_command") or 0)
        is_app = int(u.get("is_apparatus") or 0)
        is_ma = int(u.get("is_mutual_aid") or 0)

        if is_ma == 1:
            mutual_aid.append(u)
            continue

        # COMMAND
        if is_cmd == 1 or uid in COMMAND_IDS:
            command.append(u)
            continue

        # PERSONNEL (2-digit IDs)
        if utype == "PERSONNEL" or (len(uid) == 2 and uid.isdigit()):
            personnel.append(u)
            continue

        # APPARATUS
        if is_app == 1 or uid in APPARATUS_ORDER:
            apparatus.append(u)
            continue

        # Default: treat as apparatus if unknown but not mutual aid
        apparatus.append(u)

    # Canonical ordering inside each group

    # 1) Command in fixed order
    command_sorted = sorted(
        command,
        key=lambda u: COMMAND_IDS.index(u["unit_id"]) if u["unit_id"] in COMMAND_IDS else 999
    )

    # 2) Personnel sorted by numeric unit_id (21, 22, 23...)
    def personnel_key(u):
        uid = u["unit_id"]
        try:
            return int(uid)
        except ValueError:
            return 9999
    personnel_sorted = sorted(personnel, key=personnel_key)

    # 3) Apparatus in defined apparatus order
    def apparatus_key(u):
        uid = u["unit_id"]
        if uid in APPARATUS_ORDER:
            return APPARATUS_ORDER.index(uid)
        return 999
    

    # Actually fix that typo:
    apparatus_sorted = sorted(apparatus, key=apparatus_key)

    # 4) Mutual aid sorted alphabetically by unit_id
    mutual_aid_sorted = sorted(mutual_aid, key=lambda u: u["unit_id"])

    return {
        "command": command_sorted,
        "personnel": personnel_sorted,
        "apparatus": apparatus_sorted,
        "mutual_aid": mutual_aid_sorted
    }

def get_units_for_panel() -> list[dict]:
    """
    Units Panel ordering (same top structure as picker, no mutual aid):
      1. Command
      2. Personnel
      3. Apparatus
    Mutual-aid units are NOT shown in the Units Panel.
    """
    units = fetch_units()
    groups = split_units_for_picker(units)

    # Units panel = command + personnel + apparatus only
    ordered = []
    ordered.extend(groups["command"])
    ordered.extend(groups["personnel"])
    ordered.extend(groups["apparatus"])
    return ordered

# ======================================================================
# BLOCK 1A — CORE MODELS + UNIT ASSIGNMENT ENGINE
# ======================================================================

# ---------------------------------------------------------------
# UNIT METADATA ATTACHER
# ---------------------------------------------------------------
def attach_unit_metadata(unit: dict):
    unit_id = unit.get("unit_id")

    unit["status"] = (unit.get("status") or "AVAILABLE").upper().strip()

    unit.setdefault("name", unit_id)
    unit.setdefault("role", "")
    unit.setdefault("last_updated", "")
    unit.setdefault("icon", "unknown.png")
    unit.setdefault("unit_type", "")
    unit.setdefault("is_apparatus", 0)
    unit.setdefault("is_command", 0)
    unit.setdefault("is_mutual_aid", 0)

    if unit["status"] in ("A", "AVL"):
        unit["status"] = "AVAILABLE"

    return unit


# ---------------------------------------------------------------
# GET INCIDENT UNITS (IAW)
# ---------------------------------------------------------------
def get_incident_units(incident_id: int):
    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT *
        FROM UnitAssignments
        WHERE incident_id=?
        ORDER BY dispatched ASC
    """, (incident_id,)).fetchall()

    results = []
    for r in rows:
        d = attach_unit_metadata(dict(r))
        for f in ("dispatched", "enroute", "arrived", "operating", "cleared"):
            d[f] = d.get(f) or ""
        results.append(d)

    conn.close()
    return results


# ---------------------------------------------------------------
# APPARATUS → CREW (from PersonnelAssignments)
# ---------------------------------------------------------------
def get_apparatus_crew(parent_unit_id: str):
    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT personnel_id
        FROM PersonnelAssignments
        WHERE apparatus_id=?
        ORDER BY personnel_id ASC
    """, (parent_unit_id,)).fetchall()

    conn.close()
    return [r["personnel_id"] for r in rows]


# ---------------------------------------------------------------
# UPDATE UNIT STATUS + WRITE DAILY LOG
# ---------------------------------------------------------------
def update_unit_status(unit_id: str, new_status: str):
    ts = _ts()
    new_status = new_status.upper().strip()

    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        UPDATE Units
        SET status=?, last_updated=?
        WHERE unit_id=?
    """, (new_status, ts, unit_id))

    c.execute("""
        INSERT INTO DailyLog (timestamp, unit_id, action, details)
        VALUES (?, ?, 'STATUS_CHANGE', ?)
    """, (ts, unit_id, new_status))

    conn.commit()
    conn.close()


# ---------------------------------------------------------------
# SET STATUS PIPELINE (MIRRORS APPARATUS CREW)
# ---------------------------------------------------------------
def set_unit_status_pipeline(unit_id: str, status: str):
    update_unit_status(unit_id, status)

    conn = get_conn()
    c = conn.cursor()
    row = c.execute(
        "SELECT is_apparatus FROM Units WHERE unit_id=?",
        (unit_id,)
    ).fetchone()
    conn.close()

    if row and row["is_apparatus"] == 1:
        for cid in get_apparatus_crew(unit_id):
            update_unit_status(cid, status)


# ---------------------------------------------------------------
# ASSIGN UNIT TO INCIDENT
# ---------------------------------------------------------------
def assign_unit_to_incident(incident_id: int, unit_id: str):
    conn = get_conn()
    c = conn.cursor()

    exists = c.execute("""
        SELECT 1 FROM UnitAssignments
        WHERE incident_id=? AND unit_id=?
    """, (incident_id, unit_id)).fetchone()

    if not exists:
        c.execute("""
            INSERT INTO UnitAssignments (incident_id, unit_id, dispatched)
            VALUES (?, ?, ?)
        """, (incident_id, unit_id, _ts()))

    conn.commit()
    conn.close()


# ======================================================================
# BLOCK 1B — DISPATCH ENGINE (CLEAN MERGE)
# ======================================================================

def incident_promote_to_active(incident_id: int):
    conn = get_conn()
    c = conn.cursor()

    row = c.execute(
        "SELECT status FROM Incidents WHERE incident_id=?",
        (incident_id,)
    ).fetchone()

    if row and row["status"].upper() == "OPEN":
        c.execute("""
            UPDATE Incidents
            SET status='ACTIVE', updated=?
            WHERE incident_id=?
        """, (_ts(), incident_id))

    conn.commit()
    conn.close()


def unit_is_available(unit_id: str) -> bool:
    conn = get_conn()
    c = conn.cursor()
    row = c.execute(
        "SELECT status FROM Units WHERE unit_id=?",
        (unit_id,)
    ).fetchone()
    conn.close()

    if not row:
        return False
    return row["status"].upper() in ("AVAILABLE", "A", "AVL")


# ---------------------------------------------------------------
# DISPATCH MULTIPLE UNITS
# ---------------------------------------------------------------
@app.post("/incident/{incident_id}/dispatch_units")
async def dispatch_units(incident_id: int, request: Request):
    data = await request.json()
    units = data.get("units", [])

    if not units:
        return {"ok": False, "error": "No units provided"}

    conn = get_conn()
    c = conn.cursor()

    dispatched = []

    for uid in units:
        if not unit_is_available(uid):
            continue

        exists = c.execute("""
            SELECT 1 FROM UnitAssignments
            WHERE incident_id=? AND unit_id=?
        """, (incident_id, uid)).fetchone()

        if not exists:
            c.execute("""
                INSERT INTO UnitAssignments (incident_id, unit_id, dispatched)
                VALUES (?, ?, ?)
            """, (incident_id, uid, _ts()))
            dispatched.append(uid)

        # apparatus crew auto-add
        crew = get_apparatus_crew(uid)
        for cid in crew:
            if unit_is_available(cid):
                crexists = c.execute("""
                    SELECT 1 FROM UnitAssignments
                    WHERE incident_id=? AND unit_id=?
                """, (incident_id, cid)).fetchone()

                if not crexists:
                    c.execute("""
                        INSERT INTO UnitAssignments (incident_id, unit_id, dispatched)
                        VALUES (?, ?, ?)
                    """, (incident_id, cid, _ts()))
                    dispatched.append(cid)
                update_unit_status(cid, "ENROUTE")

        update_unit_status(uid, "ENROUTE")

    conn.commit()
    conn.close()

    incident_promote_to_active(incident_id)

    # narrative + daily log
    if dispatched:
        incident_history(incident_id, "DISPATCH", user=user, details=f"Units dispatched: {', '.join(dispatched)}")
        masterlog("UNITS_DISPATCHED", user=user, incident_id=incident_id, details=f"Units: {', '.join(dispatched)}")
        for u in dispatched:
            daily_log_add("DISPATCH", f"{u} dispatched", unit_id=u, incident_id=incident_id)

    return {"ok": True, "units": dispatched}


# ======================================================================
# BLOCK 1C — ARRIVE / OPERATE / CLEAR / DISPOSITION (CLEAN MERGE)
# ======================================================================

@app.post("/incident/{incident_id}/unit/{unit_id}/arrive")
async def unit_arrive(incident_id: int, unit_id: str):

    conn = get_conn()
    c = conn.cursor()

    row = c.execute("""
        SELECT arrived
        FROM UnitAssignments
        WHERE incident_id=? AND unit_id=?
    """, (incident_id, unit_id)).fetchone()

    if not row:
        conn.close()
        return {"ok": False, "error": "Unit not assigned"}

    if not row["arrived"]:
        c.execute("""
            UPDATE UnitAssignments
            SET arrived=?
            WHERE incident_id=? AND unit_id=?
        """, (_ts(), incident_id, unit_id))

        conn.commit()

        set_unit_status_pipeline(unit_id, "ARRIVED")
        incident_history(incident_id, "ARRIVED", user=user, unit_id=unit_id, details="Unit arrived")
        masterlog("UNIT_ARRIVED", user=user, incident_id=incident_id, unit_id=unit_id, details="Arrived")
        daily_log_add("ARRIVED", f"{unit_id} arrived", unit_id=unit_id, incident_id=incident_id)

    conn.close()
    return {"ok": True}


@app.post("/incident/{incident_id}/unit/{unit_id}/operating")
async def unit_operating(incident_id: int, unit_id: str):

    conn = get_conn()
    c = conn.cursor()

    row = c.execute("""
        SELECT arrived
        FROM UnitAssignments
        WHERE incident_id=? AND unit_id=?
    """, (incident_id, unit_id)).fetchone()

    if not row or not row["arrived"]:
        conn.close()
        return {"ok": False, "error": "Unit has not arrived"}

    c.execute("""
        UPDATE UnitAssignments
        SET operating=?
        WHERE incident_id=? AND unit_id=?
    """, (_ts(), incident_id, unit_id))

    conn.commit()
    conn.close()

    set_unit_status_pipeline(unit_id, "OPERATING")
    incident_history(incident_id, "OPERATING", user=user, unit_id=unit_id, details="Unit operating")
    masterlog("UNIT_OPERATING", user=user, incident_id=incident_id, unit_id=unit_id, details="Operating")
    daily_log_add("OPERATING", f"{unit_id} operating", unit_id=unit_id, incident_id=incident_id)

    return {"ok": True}


@app.post("/incident/{incident_id}/unit/{unit_id}/clear")
async def unit_clear(incident_id: int, unit_id: str):

    ts = _ts()

    conn = get_conn()
    c = conn.cursor()

    row = c.execute("""
        SELECT cleared
        FROM UnitAssignments
        WHERE incident_id=? AND unit_id=?
    """, (incident_id, unit_id)).fetchone()

    if not row:
        conn.close()
        return {"ok": False, "error": "Unit not assigned"}

    if not row["cleared"]:
        c.execute("""
            UPDATE UnitAssignments
            SET cleared=?
            WHERE incident_id=? AND unit_id=?
        """, (ts, incident_id, unit_id))

        conn.commit()

        set_unit_status_pipeline(unit_id, "AVAILABLE")
        incident_history(incident_id, "CLEARED", user=user, unit_id=unit_id, details="Unit cleared")
        masterlog("UNIT_CLEARED", user=user, incident_id=incident_id, unit_id=unit_id, details="Cleared")
        daily_log_add("CLEARED", f"{unit_id} cleared", unit_id=unit_id, incident_id=incident_id)

    # auto close if last unit
    still_active = c.execute("""
        SELECT 1
        FROM UnitAssignments
        WHERE incident_id=? AND cleared IS NULL
    """, (incident_id,)).fetchone()

    if not still_active:
        c.execute("""
            UPDATE Incidents
            SET status='CLOSED', updated=?
            WHERE incident_id=?
        """, (ts, incident_id))
        conn.commit()
        incident_history(incident_id, "CLOSED", user=user, details="Incident closed — all units cleared")
        add_narrative(incident_id, user, "Incident closed — all units cleared", entry_type="SYSTEM")
        masterlog("INCIDENT_CLOSED", user=user, incident_id=incident_id, details="All units cleared")
        daily_log_add("INCIDENT_CLOSED", f"Incident {incident_id} closed", incident_id=incident_id)

    conn.close()
    return {"ok": True}


# ======================================================================
# BLOCK 1D — UNIFIED NARRATIVE ENGINE
# ======================================================================

def legacy_add_narrative_v1(incident_id: int, text: str, unit_id: str = None):
    ts = _ts()

    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        INSERT INTO Narrative (incident_id, timestamp, entry, unit_id)
        VALUES (?, ?, ?, ?)
    """, (incident_id, ts, text, unit_id))

    conn.commit()
    conn.close()


def get_narrative_for_incident(incident_id: int):
    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT timestamp, entry, unit_id
        FROM Narrative
        WHERE incident_id=?
        ORDER BY timestamp ASC
    """, (incident_id,)).fetchall()

    conn.close()
    return [dict(r) for r in rows]

# =====================================================================
# BLOCK 3 — PHASE-3 DISPOSITION ENGINE
# =====================================================================

# ============================================================
# HELPER — Has any units still operating?
# ============================================================
def incident_has_active_units(incident_id: int) -> bool:
    conn = get_conn()
    c = conn.cursor()
    row = c.execute("""
        SELECT COUNT(*) AS n
        FROM UnitAssignments
        WHERE incident_id = ?
          AND cleared IS NULL
    """, (incident_id,)).fetchone()
    conn.close()
    return row["n"] > 0


# ============================================================
# INTERNAL — Set disposition for single unit
# ============================================================
def set_unit_disposition(incident_id: int, unit_id: str, disposition: str):
    ts = _ts()

    conn = get_conn()
    c = conn.cursor()

    # Update UnitAssignments
    c.execute("""
        UPDATE UnitAssignments
        SET disposition=?, cleared=?
        WHERE incident_id=? AND unit_id=?
    """, (disposition, ts, incident_id, unit_id))

    # Log narrative
    log_disposition_narrative(incident_id, unit_id, disposition)

    # Daily log entry
    c.execute("""
        INSERT INTO DailyLog (timestamp, incident_id, unit_id, action, details)
        VALUES (?, ?, ?, 'UNIT_DISPOSITION', ?)
    """, (ts, incident_id, unit_id, disposition))

    conn.commit()
    conn.close()


# ============================================================
# INTERNAL — Auto-close incident once last unit clears
# ============================================================
def finalize_incident_if_clear(incident_id: int):
    """
    Rules:
    - If ANY units remain assigned → do nothing
    - If NONE remain → incident must close
    """

    if incident_has_active_units(incident_id):
        return  # Still active units — cannot close yet

    # Now finalize the incident
    disposition = determine_final_incident_disposition(incident_id)

    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        UPDATE Incidents
        SET status='CLOSED',
            final_disposition=?,
            updated=?
        WHERE incident_id=?
    """, (disposition, _ts(), incident_id))

    # Narrative
    log_incident_closed(incident_id, disposition)

    # Daily log
    c.execute("""
        INSERT INTO DailyLog (timestamp, incident_id, action, details)
        VALUES (?, ?, 'INCIDENT_CLOSED', ?)
    """, (_ts(), incident_id, disposition))

    conn.commit()
    conn.close()


# ============================================================
# FINAL DISPOSITION DETERMINATION (BOSK CANON)
# ============================================================
def determine_final_incident_disposition(incident_id: int) -> str:
    """
    BOSK rules for final incident disposition:
        • If any unit disposition = R → incident = R (Rescue / Treated)
        • If any = FA → incident = FA (False Alarm)
        • If ANY unit disposition = NF → incident = NF (Nothing Found)
        • If ANY = CT → incident = CT (Cancelled Enroute)
        • If ANY = O → incident = O (Other)
        • Else → default = C (Completed)
    """

    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT disposition
        FROM UnitAssignments
        WHERE incident_id=?
    """, (incident_id,)).fetchall()

    conn.close()

    dispositions = [r["disposition"] for r in rows if r["disposition"]]

    if "R" in dispositions:
        return "R"
    if "FA" in dispositions:
        return "FA"
    if "NF" in dispositions:
        return "NF"
    if "CT" in dispositions:
        return "CT"
    if "O" in dispositions:
        return "O"

    return "C"  # Completed (default)


# ============================================================
# PUBLIC ENDPOINT — Unit Disposition Modal Submit
# ============================================================
@app.post("/incident/{incident_id}/unit/{unit_id}/disposition")
async def unit_disposition_submit(request: Request, incident_id: int, unit_id: str):
    data = await request.json()
    disposition = data.get("disposition", "").upper().strip()

    if disposition not in ["R", "FA", "NF", "CT", "O", "C"]:
        return {"ok": False, "error": "Invalid disposition"}

    # Set unit disposition
    set_unit_disposition(incident_id, unit_id, disposition)

    # After clearing, return unit to AVAILABLE
    set_unit_status_pipeline(unit_id, "AVAILABLE")

    # Try auto-close
    finalize_incident_if_clear(incident_id)

    return {"ok": True}


# ============================================================
# PUBLIC ENDPOINT — Event Disposition Submit (Final incident disposition)
# ============================================================
@app.post("/incident/{incident_id}/final_disposition")
async def final_disposition_submit(request: Request, incident_id: int):
    data = await request.json()
    disposition = data.get("disposition", "").upper().strip()

    if disposition not in ["R", "FA", "NF", "CT", "O", "C"]:
        return {"ok": False, "error": "Invalid final disposition"}

    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        UPDATE Incidents
        SET final_disposition=?, status='CLOSED', updated=?
        WHERE incident_id=?
    """, (disposition, _ts(), incident_id))

    conn.commit()
    conn.close()

    log_incident_closed(incident_id, disposition)

    return {"ok": True}
# =====================================================================
# BLOCK 4 — ISSUE FOUND SYSTEM (PHASE-3)
# =====================================================================

# ============================================================
# CREATE ISSUE RECORD
# ============================================================
def create_issue_record(incident_id: int, category: str,
                        description: str, resolution: str,
                        followup_required: int, reported_by: str):
    """

    # PASS-15: Issue Found is DailyLog-only. This legacy helper is quarantined.
    masterlog("LEGACY_INCIDENT_ISSUE_HELPER_CALLED", user=reported_by, incident_id=incident_id, ok=False, reason="Issue Found is DailyLog-only")
    raise ValueError("Issue Found is DailyLog-only; incident issue helper is deprecated.")

    Inserts an issue into the Issues table.
    Called by the Issue Found modal.
    """

    ts = _ts()

    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        INSERT INTO Issues (
            incident_id,
            timestamp,
            category,
            description,
            resolution,
            followup_required,
            reported_by
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (incident_id, ts, category, description, resolution,
          followup_required, reported_by))

    # Tag the incident with ISSUE_FOUND flag
    c.execute("""
        UPDATE Incidents
        SET issue_flag=1, updated=?
        WHERE incident_id=?
    """, (ts, incident_id))

    # Narrative entry
    log_issue_narrative(incident_id, category, description)

    # Daily log entry
    c.execute("""
        INSERT INTO DailyLog (timestamp, incident_id, action, details)
        VALUES (?, ?, 'ISSUE_REPORTED', ?)
    """, (ts, incident_id, category))

    conn.commit()
    conn.close()


# ============================================================
# GET ISSUES FOR INCIDENT (IAW FEED)
# ============================================================
def get_issues_for_incident(incident_id: int):
    """
    Returns ALL issues attached to an incident.
    Ordered oldest → newest.
    """
    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT issue_id,
               timestamp,
               category,
               description,
               resolution,
               followup_required,
               reported_by
        FROM Issues
        WHERE incident_id=?
        ORDER BY timestamp ASC
    """, (incident_id,)).fetchall()

    conn.close()
    return [dict(r) for r in rows]


# ============================================================
# PUBLIC ENDPOINT — Issue Submit
# ============================================================
@app.post("/incident/{incident_id}/issue_found")
async def issue_found_submit(request: Request, incident_id: int):
    """PASS-15: Issue Found is a Daily Log only feature (safety walks / inspections).
    This endpoint is retained for legacy UI compatibility but does not apply to incidents."""
    user = request.session.get("user")
    reject_and_log("INCIDENT_ISSUE_FOUND_REJECTED", reason="Issue Found applies to DailyLog only", user=user, incident_id=incident_id)
    return {"ok": False, "error": "Issue Found is available only for Daily Log events."}

@app.get("/incident/{incident_id}/issues", response_class=HTMLResponse)
async def incident_issues_panel(request: Request, incident_id: int):
    """
    Loads issue list for the IAW Issue tab (HTMX).
    """
    issues = get_issues_for_incident(incident_id)

    return templates.TemplateResponse(
        "modules/iaw/iaw_issues.html",
        {
            "request": request,
            "issues": issues,
            "incident_id": incident_id
        }
    )


# ============================================================
# INCIDENT LIST FLAG (⚠ INDICATOR)
# ============================================================
def incident_has_issue(incident_id: int) -> bool:
    """
    Fast check for showing ⚠ in incident lists.
    """
    conn = get_conn()
    c = conn.cursor()

    row = c.execute("""
        SELECT issue_flag
        FROM Incidents
        WHERE incident_id=?
    """, (incident_id,)).fetchone()

    conn.close()

    if not row:
        return False

    return row["issue_flag"] == 1

# ============================================================
# REMARK ENGINE (PHASE-3 CANON — FINAL)
# ============================================================

# ------------------------------------------------------------
# HELPERS — Determine Whether an Incident is a Daily Log Event
# ------------------------------------------------------------

def incident_is_dailylog(incident_id: int) -> bool:
    """
    Returns TRUE if an incident is classified as a Daily Log incident.
    Uses incident.type or a dedicated flag (depending on DB structure).
    """
    conn = get_conn()
    c = conn.cursor()

    row = c.execute("""
        SELECT type
        FROM Incidents
        WHERE incident_id=?
    """, (incident_id,)).fetchone()

    conn.close()

    if not row:
        return False

    # Daily Log incidents use TYPE = 'DAILY'
    return (row["type"] or "").upper() == "DAILY"


# ------------------------------------------------------------
# HELPERS — Determine if unit is assigned to an emergency incident
# ------------------------------------------------------------

def unit_current_incident(unit_id: str):
    """
    Returns the current ACTIVE/OPEN/HELD incident a unit is assigned to.
    If none → return None.
    """
    conn = get_conn()
    c = conn.cursor()

    row = c.execute("""
        SELECT incident_id
        FROM UnitAssignments
        JOIN Incidents USING (incident_id)
        WHERE unit_id=?
          AND Incidents.status IN ('OPEN', 'ACTIVE', 'HELD')
          AND UnitAssignments.cleared IS NULL
        ORDER BY incident_id DESC
        LIMIT 1
    """, (unit_id,)).fetchone()

    conn.close()

    return row["incident_id"] if row else None



# ============================================================
# PHASE-3 DISPATCH ENGINE — CANONICAL ENTRY POINT
# ============================================================
# POST /dispatch/unit_to_incident
# Single authoritative dispatch route (Phase-3)
#
# Rules:
#   • Promotes OPEN → ACTIVE on first dispatch
#   • Enforces no double-assignment (unit cannot be on two OPEN/ACTIVE/HELD incidents)
#   • Assigns UnitAssignments records
#   • Sets Units.status = ENROUTE for dispatched units
#   • Writes ONE grouped Narrative entry
#   • Writes ONE Daily Log entry (operational record)
#
# NOTE: This route is the ONLY route picker.js should call.

@app.post("/dispatch/unit_to_incident")
async def dispatch_unit_to_incident(request: Request):
    data = await request.json()

    incident_id = data.get("incident_id")
    units = data.get("units", [])

    if not incident_id or not isinstance(units, list) or len(units) == 0:
        return {"ok": False, "error": "Missing incident_id or units"}

    user = request.session.get("user", "Dispatcher")
    ts = _ts()

    conn = get_conn()
    c = conn.cursor()

    inc = c.execute(
        "SELECT incident_id, status FROM Incidents WHERE incident_id=?",
        (incident_id,)
    ).fetchone()

    if not inc:
        conn.close()
        return {"ok": False, "error": "Incident not found"}

    if inc["status"] not in ("OPEN", "ACTIVE", "HELD"):
        conn.close()
        return {"ok": False, "error": f"Incident not dispatchable (status={inc['status']})"}

    # Promote OPEN → ACTIVE on first dispatch
    if inc["status"] == "OPEN":
        c.execute(
            "UPDATE Incidents SET status='ACTIVE', updated=? WHERE incident_id=?",
            (ts, incident_id)
        )

    assigned = []
    skipped = []

    for unit_id in units:
        if not unit_id:
            continue

        # Enforce no double-assignment
        busy_incident = unit_current_incident(str(unit_id))
        if busy_incident and int(busy_incident) != int(incident_id):
            skipped.append({"unit_id": unit_id, "busy_incident": busy_incident})
            continue

        # Prevent duplicate assignment to same incident
        exists = c.execute(
            """
            SELECT 1 FROM UnitAssignments
            WHERE incident_id=? AND unit_id=? AND cleared IS NULL
            """,
            (incident_id, unit_id)
        ).fetchone()

        if exists:
            continue

        c.execute(
            """
            INSERT INTO UnitAssignments (incident_id, unit_id, assigned)
            VALUES (?, ?, ?)
            """,
            (incident_id, unit_id, ts)
        )

        c.execute(
            "UPDATE Units SET status='ENROUTE' WHERE unit_id=?",
            (unit_id,)
        )

        assigned.append(unit_id)

    # Grouped Narrative + Daily Log
    if assigned:
        unit_list = ", ".join(assigned)
        incident_history(int(incident_id), "DISPATCH", user=user, details=f"Dispatched units: {unit_list}")
        masterlog("UNITS_DISPATCHED", user=user, incident_id=int(incident_id), details=f"Units: {unit_list}")
        c.execute("""
            INSERT INTO DailyLog (timestamp, incident_id, unit_id, action, details)
            VALUES (?, ?, ?, 'DISPATCH', ?)
        """, (ts, int(incident_id), None, f"{user} — DISPATCH — {unit_list}"))

    conn.commit()
    conn.close()

    return {"ok": True, "assigned": assigned, "skipped": skipped}
# ------------------------------------------------------------
# INTERNAL — Write to Narrative Only
# ------------------------------------------------------------

def remark_to_narrative(incident_id: int, user: str, text: str, unit_id: str | None):
    ts = _ts()

    conn = get_conn()
    c = conn.cursor()

    entry = f"REMARK ({user}) — {text}"

    c.execute("""
        INSERT INTO Narrative (incident_id, timestamp, entry, unit_id)
        VALUES (?, ?, ?, ?)
    """, (incident_id, ts, entry, unit_id))

    conn.commit()
    conn.close()


# ------------------------------------------------------------
# INTERNAL — Write to Daily Log Only
# ------------------------------------------------------------

def remark_to_dailylog(user_unit: str, text: str, incident_id: int | None = None):
    ts = _ts()

    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        INSERT INTO DailyLog (timestamp, unit_id, incident_id, action, details)
        VALUES (?, ?, ?, 'REMARK', ?)
    """, (ts, user_unit, incident_id, text))

    conn.commit()
    conn.close()


# ------------------------------------------------------------
# MASTER REMARK ROUTER (ALL CASE LOGIC IS HERE)
# ------------------------------------------------------------

def process_remark(
    user: str,
    text: str,
    unit_id: str | None,
    incident_id: int | None
):
    """
    Applies the COMPLETE BOSK-CAD ruleset:

    CASE A — unit & incident
    CASE B — unit only
    CASE C — incident only
    CASE D — neither selected
    """

    # ===========================
    # CLEAN + NORMALIZE INPUT
    # ===========================
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "Empty remark"}

    # Auto-fill dispatcher unit when nothing provided
    if not unit_id:
        unit_id = user  # Dispatchers have unit IDs in BOSK-CAD

    # -------------------------------------------
    # CASE D — NO unit, NO incident (Daily Log)
    # Corrected per your final rule.
    # -------------------------------------------
    if unit_id == user and incident_id is None:
        remark_to_dailylog(user_unit=unit_id, text=text)
        return {"ok": True, "routed": "DAILY_LOG"}


    # -------------------------------------------
    # CASE C — Incident only
    # -------------------------------------------
    if unit_id and incident_id and incident_is_dailylog(incident_id):
        remark_to_narrative(incident_id, user, text, unit_id)
        remark_to_dailylog(user_unit=unit_id, text=text, incident_id=incident_id)
        return {"ok": True, "routed": "NARRATIVE + DAILY_LOG"}

    if incident_id and not incident_is_dailylog(incident_id):
        remark_to_narrative(incident_id, user, text, unit_id)
        return {"ok": True, "routed": "NARRATIVE"}


    # -------------------------------------------
    # CASE B — Unit only
    # -------------------------------------------
    # Check if unit is on an emergency incident
    active_incident = unit_current_incident(unit_id)

    if active_incident:
        # Emergency → narrative only
        remark_to_narrative(active_incident, user, text, unit_id)
        return {"ok": True, "routed": "NARRATIVE"}

    # Not on incident → Daily Log only
    remark_to_dailylog(user_unit=unit_id, text=text)
    return {"ok": True, "routed": "DAILY_LOG"}


    # -------------------------------------------
    # CASE A — Unit + Incident
    # (Emergency vs Daily Log handled above)
    # -------------------------------------------

# ------------------------------------------------------------
# PUBLIC ENDPOINT — Remark Submit
# ------------------------------------------------------------

@app.post("/remark")
async def remark_submit(request: Request):
    """
    Unified remark endpoint for:
    - Toolbar Add Remark
    - Unit Action Window (UAW)
    - Incident Action Window (IAW)
    """

    data = await request.json()

    text        = data.get("text") or ""
    unit_id     = data.get("unit_id") or None
    incident_id = data.get("incident_id") or None

    if isinstance(incident_id, str) and incident_id.isdigit():
        incident_id = int(incident_id)

    user = request.session.get("user", "Dispatcher")

    result = process_remark(user, text, unit_id, incident_id)

    return result

# =====================================================================
# BLOCK 5 — REMARK SYSTEM (PHASE-3)
# =====================================================================

# ============================================================
# LOG REMARK INTO NARRATIVE
# ============================================================
def log_remark(incident_id: int, user: str, text: str):
    """
    Writes a remark into the Narrative table.
    Remarks are simple free-text entries created by dispatcher.
    """
    ts = _ts()

    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        INSERT INTO Narrative (incident_id, timestamp, entry_type, text)
        VALUES (?, ?, 'REMARK', ?)
    """, (incident_id, ts, f"{user}: {text.strip()}"))

    # Daily Log entry (optional for reporting)
    c.execute("""
        INSERT INTO DailyLog (timestamp, incident_id, action, details)
        VALUES (?, ?, 'REMARK', ?)
    """, (ts, incident_id, text.strip()))

    conn.commit()
    conn.close()


# ============================================================
# ROUTE — Remark Submit
# Called by remark modal
# ============================================================
@app.post("/incident/{incident_id}/remark")
async def remark_submit(request: Request, incident_id: int):
    """
    POST endpoint used when dispatcher submits a Remark.
    Data is received as JSON:
        { "text": "Some remark..." }
    """

    data = await request.json()
    text = (data.get("text") or "").strip()
    user = request.session.get("user", "Dispatcher")

    if not text:
        return {"ok": False, "error": "Remark text required"}

    # Make entry
    log_remark(incident_id, user, text)

    return {"ok": True}


# ============================================================
# ROUTE — Load Remarks (IAW feed)
# ============================================================
@app.get("/incident/{incident_id}/remarks", response_class=HTMLResponse)
async def iaw_remarks_panel(request: Request, incident_id: int):
    """
    Returns the remark list for the IAW Remarks tab.
    """

    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT timestamp, text
        FROM Narrative
        WHERE incident_id=? AND entry_type='REMARK'
        ORDER BY timestamp ASC
    """, (incident_id,)).fetchall()

    conn.close()

    return templates.TemplateResponse(
        "modules/iaw/iaw_remarks.html",
        {
            "request": request,
            "incident_id": incident_id,
            "remarks": [dict(r) for r in rows]
        }
    )
# =====================================================================
# BLOCK 6 — UNIT DISPOSITION ENGINE (PHASE-3)
# =====================================================================
# This block provides the full backend logic for:
#   • ENROUTE
#   • ARRIVED
#   • OPERATING
#   • TRANSPORTING
#   • CLEARED
#   • Disposition codes (R, NA, NF, C, CT, O)
#   • Auto-close of incident when last unit clears
#   • Narrative entries
#   • DailyLog entries
#   • Crew mirroring for apparatus
# =====================================================================


# ============================================================
# Helper — Write narrative for a unit event
# ============================================================
def log_unit_narrative(incident_id: int, unit_id: str, text: str):
    ts = _ts()
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        INSERT INTO Narrative (incident_id, timestamp, entry_type, text)
        VALUES (?, ?, 'UNIT', ?)
    """, (incident_id, ts, f"{unit_id}: {text}"))

    # DailyLog
    c.execute("""
        INSERT INTO DailyLog (timestamp, incident_id, unit_id, action, details)
        VALUES (?, ?, ?, 'UNIT_EVENT', ?)
    """, (ts, incident_id, unit_id, text))

    conn.commit()
    conn.close()


# ============================================================
# Helper — Update UnitAssignments timeline fields
# ============================================================
def update_assignment_field(incident_id: int, unit_id: str, field: str):
    conn = get_conn()
    c = conn.cursor()

    c.execute(
        f"UPDATE UnitAssignments SET {field}=? WHERE incident_id=? AND unit_id=?",
        (_ts(), incident_id, unit_id)
    )

    conn.commit()
    conn.close()


# ============================================================
# Helper — Determine if this was the last active unit
# ============================================================
def is_last_unit_cleared(incident_id: int) -> bool:
    conn = get_conn()
    c = conn.cursor()

    # Any unit still active?
    rows = c.execute("""
        SELECT 1 FROM UnitAssignments
        WHERE incident_id=? AND cleared IS NULL
    """, (incident_id,)).fetchall()

    conn.close()
    return len(rows) == 0


# ============================================================
# Apply disposition to a unit (R/NA/NF/C/CT/O)
# ============================================================
def apply_unit_disposition(incident_id: int, unit_id: str, code: str):
    """
    Stores the unit's disposition code in IncidentUnits table.
    """

    conn = get_conn()
    c = conn.cursor()

    # If table doesn't exist yet, avoid fatal crash
    try:
        c.execute("""
            INSERT INTO UnitDispositions (incident_id, unit_id, disposition, timestamp)
            VALUES (?, ?, ?, ?)
        """, (incident_id, unit_id, code, _ts()))
    except Exception:
        pass

    conn.commit()
    conn.close()


# ============================================================
# AUTO EVENT DISPOSITION WHEN LAST UNIT CLEARS
# ============================================================
def auto_event_disposition(incident_id: int):
    """
    When the last unit clears an incident, the CAD automatically
    closes the incident using disposition logic.
    """

    ts = _ts()
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        UPDATE Incidents
        SET status='CLOSED', updated=?
        WHERE incident_id=?
    """, (ts, incident_id))

    # Narrative
    c.execute("""
        INSERT INTO Narrative (incident_id, timestamp, entry_type, text)
        VALUES (?, ?, 'DISPO', 'Incident closed (auto-clear)')
    """, (incident_id, ts))

    # DailyLog
    c.execute("""
        INSERT INTO DailyLog (timestamp, incident_id, action, details)
        VALUES (?, ?, 'INCIDENT_CLOSED', 'Auto-closed when last unit cleared')
    """, (ts, incident_id))

    conn.commit()
    conn.close()


# =====================================================================
# ROUTE — UNIT STATUS LIFECYCLE ACTIONS
# =====================================================================

@app.post("/incident/{incident_id}/unit/{unit_id}/status/{new_status}")
async def update_unit_status_route(incident_id: int, unit_id: str, new_status: str):
    """
    This route handles ALL unit status transitions:
        ENROUTE
        ARRIVED
        OPERATING
        TRANSPORTING
        CLEARED
    """

    new_status = new_status.upper().strip()

    # 1) Update global unit status + crew mirroring
    set_unit_status_pipeline(unit_id, new_status)

    # 2) Update assignment timeline fields
    if new_status == "ENROUTE":
        update_assignment_field(incident_id, unit_id, "enroute")
        log_unit_narrative(incident_id, unit_id, "Enroute")

    elif new_status == "ARRIVED":
        update_assignment_field(incident_id, unit_id, "arrived")
        log_unit_narrative(incident_id, unit_id, "Arrived on scene")

    elif new_status == "OPERATING":
        update_assignment_field(incident_id, unit_id, "operating")
        log_unit_narrative(incident_id, unit_id, "Operating on scene")

    elif new_status == "TRANSPORTING":
        update_assignment_field(incident_id, unit_id, "transporting")
        log_unit_narrative(incident_id, unit_id, "Transporting patient")

    elif new_status == "CLEARED":
        update_assignment_field(incident_id, unit_id, "cleared")
        log_unit_narrative(incident_id, unit_id, "Cleared")

        # Add default disposition "C" (Cleared) unless overridden later
        apply_unit_disposition(incident_id, unit_id, "C")

        # If last unit → auto close incident
        if is_last_unit_cleared(incident_id):
            auto_event_disposition(incident_id)

    else:
        return {"ok": False, "error": f"Unknown status {new_status}"}

    return {"ok": True}


# =====================================================================
# ROUTE — APPLY UNIT DISPOSITION (from disposition modal)
# =====================================================================

@app.post("/legacy/incident/{incident_id}/unit/{unit_id}/disposition__v4")
async def apply_disposition_route(request: Request, incident_id: int, unit_id: str):
    """
    Receives:
        { "code": "R" }
    """

    data = await request.json()
    code = (data.get("code") or "").upper().strip()

    if code not in ("R", "NA", "NF", "C", "CT", "O"):
        return {"ok": False, "error": "Invalid disposition code"}

    apply_unit_disposition(incident_id, unit_id, code)
    log_unit_narrative(incident_id, unit_id, f"Disposition set: {code}")

    return {"ok": True}
# =====================================================================
# BLOCK 7 — EVENT DISPOSITION ENGINE (PHASE-3)
# =====================================================================
# This block:
#   • Records the FINAL disposition of an incident
#   • Writes narrative entries
#   • Writes Daily Log entries
#   • Closes the incident
#   • Updates IAW and all CAD panels
#   • Handles disposition modal submission
#
# Unit-level dispositions (Block 6) are separate. This is
# INCIDENT-LEVEL final disposition.
# =====================================================================


# ============================================================
# Allowed incident disposition codes
# ============================================================
VALID_EVENT_DISPO = {
    "FA": "Fire Alarm",
    "FF": "Fire Found",
    "MF": "Medical – First Aid Only",
    "MT": "Medical – Transport",
    "PR": "Patient Refusal",
    "NF": "No Finding",
    "C":  "Cancelled",
    "CT": "Cancelled Enroute",
    "O":  "Other"
}


# ============================================================
# Helper — Write incident-level disposition to DB
# ============================================================
def save_incident_disposition(incident_id: int, code: str, comment: str):
    ts = _ts()

    conn = get_conn()
    c = conn.cursor()

    # Store disposition record
    c.execute("""
        INSERT INTO IncidentDispositions (incident_id, disposition, comment, timestamp)
        VALUES (?, ?, ?, ?)
    """, (incident_id, code, comment, ts))

    # Update incident record itself
    c.execute("""
        UPDATE Incidents
        SET status='CLOSED',
            disposition=?,
            updated=?
        WHERE incident_id=?
    """, (code, ts, incident_id))

    # Narrative entry
    c.execute("""
        INSERT INTO Narrative (incident_id, timestamp, entry_type, text)
        VALUES (?, ?, 'DISPO', ?)
    """, (incident_id, ts, f"Incident disposition set to {code} ({VALID_EVENT_DISPO.get(code, 'Unknown')})"))

    # Daily Log entry
    c.execute("""
        INSERT INTO DailyLog (timestamp, incident_id, action, details)
        VALUES (?, ?, 'INCIDENT_DISPOSITION', ?)
    """, (ts, incident_id, f"{code}: {comment}"))

    conn.commit()
    conn.close()


# ============================================================
# Helper — Close incident cleanly (no duplicate close)
# ============================================================
def ensure_incident_closed(incident_id: int):
    conn = get_conn()
    c = conn.cursor()

    row = c.execute("""
        SELECT status FROM Incidents WHERE incident_id=?
    """, (incident_id,)).fetchone()

    if row and row["status"] == "CLOSED":
        conn.close()
        return  # already closed

    ts = _ts()

    c.execute("""
        UPDATE Incidents
        SET status='CLOSED', updated=?
        WHERE incident_id=?
    """, (ts, incident_id))

    # Narrative fall-back
    c.execute("""
        INSERT INTO Narrative (incident_id, timestamp, entry_type, text)
        VALUES (?, ?, 'SYSTEM', 'Incident auto-closed (fallback)')
    """, (incident_id, ts))

    conn.commit()
    conn.close()


# =====================================================================
# FRONTEND ROUTE — Load Event Disposition Modal
# =====================================================================

@app.get("/incident/{incident_id}/disposition", response_class=HTMLResponse)
async def load_disposition_modal(request: Request, incident_id: int):
    """
    Loads the disposition modal.
    """
    return templates.TemplateResponse(
        "event_disposition_modal.html",
        {
            "request": request,
            "incident_id": incident_id,
            "valid_codes": VALID_EVENT_DISPO
        }
    )


# =====================================================================
# BACKEND ROUTE — Handle Event Disposition Submission
# =====================================================================

@app.post("/incident/{incident_id}/disposition")
async def submit_incident_disposition(request: Request, incident_id: int):
    """
    Receives JSON:
        { "code": "MT", "comment": "Patient transported to medical" }
    """

    data = await request.json()
    code = (data.get("code") or "").upper().strip()
    comment = (data.get("comment") or "").strip()

    # Validate disposition code
    if code not in VALID_EVENT_DISPO:
        return {"ok": False, "error": f"Invalid disposition code {code}"}

    # Save disposition + narrative + daily log
    save_incident_disposition(incident_id, code, comment)

    # Ensure incident is CLOSED
    ensure_incident_closed(incident_id)

    return {"ok": True}
# =====================================================================
# BLOCK 8 — REMARK ENGINE (PHASE-3)
# =====================================================================
# Supports:
#   • Remark modal loader
#   • Remark submission
#   • Narrative insertion
#   • Daily log entry
#   • IAW refresh pipeline
# =====================================================================


# =====================================================================
# FRONTEND ROUTE — Load Remark Modal
# =====================================================================

@app.get("/incident/{incident_id}/remark", response_class=HTMLResponse)
async def load_remark_modal(request: Request, incident_id: int):
    """
    Loads the remark modal window.
    """
    return templates.TemplateResponse(
        "remark_modal.html",
        {
            "request": request,
            "incident_id": incident_id
        }
    )


# =====================================================================
# BACKEND ROUTE — Submit Remark
# =====================================================================

@app.post("/legacy/incident/{incident_id}/remark__v5")
async def submit_remark(request: Request, incident_id: int):
    """
    Receives JSON:
        { "remark": "Patient moved to medical", "user": "Dispatcher" }

    Writes:
        • Narrative entry
        • Daily Log entry
        • Returns OK for IAW reload
    """

    data = await request.json()
    remark = (data.get("remark") or "").strip()
    user = (data.get("user") or "Unknown").strip()

    if not remark:
        return {"ok": False, "error": "Remark cannot be empty."}

    ts = _ts()

    conn = get_conn()
    c = conn.cursor()

    # ------------------------------------------------------------
def log_event(event_type: str, details: str, incident_id=None, user: str=None, issue_found: int=0, unit_id=None):
    """PASS-15: DailyLog event writer ONLY.
    DailyLog is for daily activities (safety walks, inspections, non-incident items).
    Incident operations must use incident_history() + masterlog()."""
    dailylog_event(event_type, details, user=user, issue_found=issue_found, incident_id=incident_id, unit_id=unit_id)
    masterlog("DAILYLOG_EVENT", user=user, incident_id=incident_id, unit_id=unit_id, details=f"{event_type}: {details}")
    return

@app.get("/legacy/incident/{incident_id}/units__v8", response_class=HTMLResponse)
async def iaw_units_region(request: Request, incident_id: int):
    """
    Returns the assigned unit list in correct canonical ordering:
        • command units
        • personnel
        • apparatus
        • (mutual aid NEVER appears here)
    Includes their dispatch timeline timestamps.
    """
    assigned = get_incident_units(incident_id)

    # Sort assigned units by our canonical ordering
    # (Command → Personnel → Apparatus)
    ordered = []
    for u in assigned:
        ordered.append(u)

    return templates.TemplateResponse(
        "modules/iaw_units_block.html",
        {
            "request": request,
            "units": ordered,
            "incident_id": incident_id
        }
    )


# =====================================================================
# IAW — NARRATIVE FEED
# =====================================================================

@app.get("/incident/{incident_id}/narrative", response_class=HTMLResponse)
async def iaw_narrative_region(request: Request, incident_id: int):
    """
    Returns chronological narrative entries for this incident.

    Narrative table:
        incident_id
        timestamp
        entry_type
        text
    """

    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT timestamp, entry_type, text
        FROM Narrative
        WHERE incident_id=?
        ORDER BY timestamp ASC
    """, (incident_id,)).fetchall()

    conn.close()

    # Convert to safe dicts
    narrative = []
    for r in rows:
        narrative.append({
            "timestamp": r["timestamp"],
            "entry_type": r["entry_type"],
            "text": r["text"]
        })

    return templates.TemplateResponse(
        "modules/iaw_narrative_block.html",
        {
            "request": request,
            "narrative": narrative,
            "incident_id": incident_id
        }
    )
# =====================================================================
# BLOCK 10 — DAILY LOG ENGINE (Phase-3 Canon)
# =====================================================================
# Provides:
#   • log_event()  → single consolidated logging function
#   • Daily Log viewer panel (/panel/dailylog)
#   • inserts for dispatch, status change, remarks, dispositions, etc.
#
# Table structure (created in Phase-3 DB upgrade):
#
#   DailyLog(
#       log_id INTEGER PRIMARY KEY,
#       timestamp TEXT,
#       incident_id INTEGER NULL,
#       unit_id TEXT NULL,
#       action TEXT,
#       details TEXT
#   )
#
# =====================================================================


# =====================================================================
# CORE LOGGING ENGINE
# =====================================================================

def log_event(action: str,
              details: str = "",
              incident_id: int | None = None,
              unit_id: str | None = None):
    """
    Central event logger.
    Used by ALL CAD actions:
        • Dispatch
        • Enroute/Arrived/Clear
        • Narrative entries
        • Dispositions
        • Issue Found
        • Status Changes
        • Unit Assignments
    """

    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        INSERT INTO DailyLog (timestamp, incident_id, unit_id, action, details)
        VALUES (?, ?, ?, ?, ?)
    """, (_ts(), incident_id, unit_id, action, details))

    conn.commit()
    conn.close()


# =====================================================================
# REBUILD NARRATIVE INSERT (FOR REMARKS + AUTOMATED ENTRIES)
# =====================================================================

def legacy_add_narrative_v2(incident_id: int, entry_type: str, text: str):
    """
    Inserts narrative for an incident AND writes to DailyLog.
    """
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        INSERT INTO Narrative (incident_id, timestamp, entry_type, text)
        VALUES (?, ?, ?, ?)
    """, (incident_id, _ts(), entry_type, text))

    conn.commit()
    conn.close()

    # Also log it to DailyLog
    log_event(
        action=f"NARRATIVE_{entry_type.upper()}",
        details=text,
        incident_id=incident_id
    )


# =====================================================================
# PANEL LOADER — DAILY LOG VIEW (HTMX PANEL)
# =====================================================================

@app.get("/panel/dailylog", response_class=HTMLResponse)
async def panel_dailylog(request: Request):
    """
    Loads the Daily Log table for the current operational period.
    (Later we can add date filters; for now show entire table.)
    """

    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT log_id, timestamp, incident_id, unit_id, action, details
        FROM DailyLog
        ORDER BY log_id DESC
        LIMIT 500
    """).fetchall()

    conn.close()

    # Convert rows to clean dicts for the template
    entries = []
    for r in rows:
        entries.append({
            "log_id": r["log_id"],
            "timestamp": r["timestamp"],
            "incident_id": r["incident_id"],
            "unit_id": r["unit_id"],
            "action": r["action"],
            "details": r["details"]
        })

    return templates.TemplateResponse(
        "dailylog_panel.html",
        {
            "request": request,
            "entries": entries
        }
    )
# =====================================================================
# BLOCK 11 — DISPATCH ENGINE (Phase-3 Enterprise Backend)
# =====================================================================
# Provides:
#   • /incident/<id>/dispatch_units   (core dispatch endpoint)
#   • Apparatus + crew assignment
#   • Status promotion AVAILABLE → ENROUTE
#   • Incident promotion OPEN → ACTIVE
#   • Full narrative + daily log integration
#   • Safety validations (prevent dispatching HELD, CLOSED, or OOS units)
# =====================================================================


# =====================================================================
# INCIDENT STATUS PROMOTION LOGIC
# =====================================================================

def promote_incident_to_active(incident_id: int):
    """
    If an incident is OPEN and receives a dispatch,
    automatically promote it to ACTIVE.
    """
    conn = get_conn()
    c = conn.cursor()

    # Check current status
    row = c.execute("""

        SELECT status FROM Incidents WHERE incident_id=?
    """, (incident_id,)).fetchone()

    if not row:
        conn.close()
        return

    if row["status"] == "OPEN":
        c.execute("""
            UPDATE Incidents
            SET status='ACTIVE', updated=?
            WHERE incident_id=?
        """, (_ts(), incident_id))

        conn.commit()

        # Write log + narrative
        log_event("INCIDENT_PROMOTED", "Incident status changed to ACTIVE", incident_id)
        add_narrative(incident_id, "SYSTEM", "Incident updated to ACTIVE.")

    conn.close()



# =====================================================================
# VALIDATION — CAN A UNIT BE DISPATCHED?
# =====================================================================

def unit_is_dispatchable(unit: dict) -> bool:
    """
    A unit can be dispatched ONLY if:
        • status is AVAILABLE or A/AVL
        • NOT mutual aid unless we explicitly allow MA dispatch (we do)
        • NOT apparatus with missing crew?  (We allow empty crew for now)
    """
    s = unit.get("status", "").upper()

    if s in ("AVAILABLE", "A", "AVL"):
        return True
    return False



# =====================================================================
# FETCH UNIT RECORD
# =====================================================================

def fetch_unit(unit_id: str) -> dict | None:
    conn = get_conn()
    c = conn.cursor()

    row = c.execute("""
        SELECT unit_id, name, unit_type, status, icon,
               COALESCE(is_apparatus,0) AS is_apparatus,
               COALESCE(is_command,0) AS is_command,
               COALESCE(is_mutual_aid,0) AS is_mutual_aid
        FROM Units
        WHERE unit_id=?
    """, (unit_id,)).fetchone()

    conn.close()

    if not row:
        return None

    return attach_unit_metadata(dict(row))



# =====================================================================
# DISPATCH PIPELINE
# =====================================================================

def perform_dispatch(incident_id: int, units: list[str]):
    """
    Executes the Phase-3 dispatch pipeline:
        1. Validate incident is dispatchable
        2. Validate each unit is dispatchable
        3. Assign units to UnitAssignments
        4. Set unit status to ENROUTE
        5. Mirror crew (apparatus)
        6. Add narrative entries
        7. Add daily log entries
        8. Promote incident to ACTIVE
    """

    conn = get_conn()
    c = conn.cursor()

    # -----------------------------------------------------------------
    # 1) Validate incident existence + state
    # -----------------------------------------------------------------
    incident = c.execute("""
        SELECT status
        FROM Incidents
        WHERE incident_id=?
    """, (incident_id,)).fetchone()

    if not incident:
        conn.close()
        return {"ok": False, "error": "Incident does not exist."}

    if incident["status"] == "HELD":
        conn.close()
        return {"ok": False, "error": "Cannot dispatch to a HELD incident."}

    if incident["status"] == "CLOSED":
        conn.close()
        return {"ok": False, "error": "Cannot dispatch to a CLOSED incident."}

    conn.close()

    # -----------------------------------------------------------------
    # 2) Validate each unit
    # -----------------------------------------------------------------
    validated_units = []
    for uid in units:
        u = fetch_unit(uid)

        if not u:
            return {"ok": False, "error": f"Unit {uid} not found."}

        if not unit_is_dispatchable(u):
            return {"ok": False, "error": f"Unit {uid} is not AVAILABLE."}

        validated_units.append(u)

    # -----------------------------------------------------------------
    # 3) Dispatch each unit
    # -----------------------------------------------------------------
    for u in validated_units:
        uid = u["unit_id"]

        # Assign unit to incident
        assign_unit_to_incident(incident_id, uid)

        # Set unit status → ENROUTE
        set_unit_status_pipeline(uid, "ENROUTE")

        # Narrative entry
        add_narrative(
            incident_id,
            "DISPATCH",
            f"Unit {uid} dispatched ENROUTE."
        )

        # Daily Log entry
        log_event(
            "UNIT_DISPATCHED",
            f"Unit {uid} dispatched to incident.",
            incident_id=incident_id,
            unit_id=uid,
        )

    # -----------------------------------------------------------------
    # 4) Promote incident to ACTIVE
    # -----------------------------------------------------------------
    promote_incident_to_active(incident_id)

    return {"ok": True}



# =====================================================================
# DISPATCH ENDPOINT (used by Dispatch Picker modal)
# =====================================================================

@app.post("/legacy/incident/{incident_id}/dispatch_units__v2")
async def dispatch_units_endpoint(request: Request, incident_id: int):
    """
    Receives JSON:
        {
            "incident_id": 123,
            "units": ["Engine2", "21", "HCEMS-Medic"]
        }
    """

    data = await request.json()
    units = data.get("units", [])

    if not isinstance(units, list) or len(units) == 0:
        return JSONResponse({"ok": False, "error": "No units selected."})

    result = perform_dispatch(incident_id, units)

    if not result.get("ok"):
        return JSONResponse(result)

    return JSONResponse({"ok": True})
# ================================================================
# BLOCK 12 — IAW FEEDS (UNITS + NARRATIVE)
# Phase-3 Canon • Required for the Incident Action Window (IAW)
# ================================================================

# ---------------------------------------------------------------
# IAW: ASSIGNED UNITS FEED
# Returns list of assigned units + timeline fields:
#   dispatched, enroute, arrived, cleared
# ---------------------------------------------------------------
@app.get("/incident/{incident_id}/units", response_class=HTMLResponse)
async def iaw_units_feed(request: Request, incident_id: int):

    conn = get_conn()
    c = conn.cursor()

    # Pull assigned units with times
    rows = c.execute("""
        SELECT 
            ua.unit_id,
            ua.dispatched,
            ua.enroute,
            ua.arrived,
            ua.cleared,
            u.name,
            u.unit_type,
            u.status,
            u.icon,
            u.is_apparatus,
            u.is_command,
            u.is_mutual_aid
        FROM UnitAssignments ua
        JOIN Units u ON u.unit_id = ua.unit_id
        WHERE ua.incident_id = ?
        ORDER BY ua.dispatched ASC
    """, (incident_id,)).fetchall()

    conn.close()

    units = []
    for r in rows:
        d = dict(r)

        # Normalize time fields for display
        for f in ("dispatched", "enroute", "arrived", "cleared"):
            if not d.get(f):
                d[f] = ""

        units.append(d)

    return templates.TemplateResponse("iaw_units_block.html", {
        "request": request,
        "units": units,
        "incident_id": incident_id
    })


# ---------------------------------------------------------------
# IAW: NARRATIVE FEED
# Returns full chronological narrative list for incident
# ---------------------------------------------------------------
@app.get("/legacy/incident/{incident_id}/narrative__v9", response_class=HTMLResponse)
async def iaw_narrative_feed(request: Request, incident_id: int):

    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT timestamp, user, text
        FROM Narrative
        WHERE incident_id = ?
        ORDER BY timestamp ASC
    """, (incident_id,)).fetchall()

    conn.close()

    return templates.TemplateResponse("iaw_narrative_block.html", {
        "request": request,
        "incident_id": incident_id,
        "narrative": rows
    })
# ================================================================
# BLOCK 13 — UNIT STATUS ENGINE (Phase-3)
# ENROUTE / ARRIVED / CLEAR buttons inside IAW
# Crew mirroring
# AUTO-NARRATIVE
# Incident promotion logic
# ================================================================

# ---------------------------------------------------------------
# INTERNAL: Add narrative entry
# ---------------------------------------------------------------
def legacy_add_narrative_v3(incident_id: int, user: str, text: str):
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        INSERT INTO Narrative (incident_id, timestamp, user, text)
        VALUES (?, ?, ?, ?)
    """, (incident_id, _ts(), user, text))

    conn.commit()
    conn.close()


# ---------------------------------------------------------------
# INTERNAL: Promote incident OPEN → ACTIVE after first dispatch
# ---------------------------------------------------------------
def promote_incident_if_needed(incident_id: int):
    conn = get_conn()
    c = conn.cursor()

    row = c.execute("""
        SELECT status FROM Incidents WHERE incident_id=?
    """, (incident_id,)).fetchone()

    if row and row["status"] == "OPEN":
        c.execute("""
            UPDATE Incidents
            SET status='ACTIVE', updated=?
            WHERE incident_id=?
        """, (_ts(), incident_id))

        conn.commit()

    conn.close()


# ---------------------------------------------------------------
# INTERNAL: Mirror crew when apparatus status changes
# ---------------------------------------------------------------
def mirror_crew(app_unit_id: str, status: str):
    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT personnel_id
        FROM PersonnelAssignments
        WHERE apparatus_id=?
    """, (app_unit_id,)).fetchall()

    crew = [r["personnel_id"] for r in rows]

    for cid in crew:
        c.execute("""
            UPDATE Units
            SET status=?, last_updated=?
            WHERE unit_id=?
        """, (status, _ts(), cid))

        # Crew narrative (mirrored)
        c.execute("""
            INSERT INTO DailyLog (timestamp, unit_id, action, details)
            VALUES (?, ?, 'CREW_STATUS', ?)
        """, (_ts(), cid, f"Mirrored to {status} via {app_unit_id}"))

    conn.commit()
    conn.close()


# ---------------------------------------------------------------
# INTERNAL: Actually perform the status change
# ---------------------------------------------------------------
def change_unit_status(unit_id: str, incident_id: int, status: str, user: str):

    # Normalize and uppercase statuses
    status = status.upper().strip()

    conn = get_conn()
    c = conn.cursor()

    # Status update in Units table
    c.execute("""
        UPDATE Units
        SET status=?, last_updated=?
        WHERE unit_id=?
    """, (status, _ts(), unit_id))

    # Update UnitAssignments timeline field
    time_field = {
        "ENROUTE":  "enroute",
        "ARRIVED":  "arrived",
        "CLEAR":    "cleared"
    }.get(status)

    if time_field:
        c.execute(f"""
            UPDATE UnitAssignments
            SET {time_field}=?, last_update=?
            WHERE unit_id=? AND incident_id=?
        """, (_ts(), _ts(), unit_id, incident_id))

    # Daily Log entry
    c.execute("""
        INSERT INTO DailyLog (timestamp, unit_id, action, details)
        VALUES (?, ?, 'STATUS', ?)
    """, (_ts(), unit_id, status))

    conn.commit()

    # Fetch is_apparatus flag
    row = c.execute("""
        SELECT is_apparatus FROM Units WHERE unit_id=?
    """, (unit_id,)).fetchone()

    if row and row["is_apparatus"] == 1:
        # Mirror to assigned personnel
        mirror_crew(unit_id, status)

    conn.close()

    # Narrative entry
    add_narrative(
        incident_id,
        user,
        f"{unit_id} marked {status}"
    )


# ---------------------------------------------------------------
# PUBLIC ENDPOINT FOR IAW BUTTONS
# ---------------------------------------------------------------
@app.post("/unit_status")
async def unit_status_api(request: Request):

    data = await request.json()
    unit_id = data.get("unit_id")
    status = data.get("status")
    incident_id = int(data.get("incident_id"))

    user = request.session.get("user", "Dispatcher")

    if not unit_id or not status:
        return {"ok": False, "error": "Missing parameters"}

    # Perform the status pipeline
    change_unit_status(unit_id, incident_id, status, user)

    return {"ok": True}
# ================================================================
# BLOCK 14 — DISPATCH ENGINE (Phase-3 Enterprise)
# Assign Units → Create UnitAssignments → Auto Narrative
# Auto-Mirror Crew → Auto Status → Auto Promote Incident
# ================================================================

# ---------------------------------------------------------------
# INTERNAL: Add narrative entry (reused)
# ---------------------------------------------------------------
def legacy_add_narrative_v4(incident_id: int, user: str, text: str):
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        INSERT INTO Narrative (incident_id, timestamp, user, text)
        VALUES (?, ?, ?, ?)
    """, (incident_id, _ts(), user, text))

    conn.commit()
    conn.close()


# ---------------------------------------------------------------
# INTERNAL: Ensure UnitAssignments has dispatched time
# ---------------------------------------------------------------
def create_unit_assignment(incident_id: int, unit_id: str):
    conn = get_conn()
    c = conn.cursor()

    exists = c.execute("""
        SELECT 1 FROM UnitAssignments
        WHERE incident_id=? AND unit_id=?
    """, (incident_id, unit_id)).fetchone()

    if not exists:
        c.execute("""
            INSERT INTO UnitAssignments
                (incident_id, unit_id, dispatched, last_update)
            VALUES (?, ?, ?, ?)
        """, (incident_id, unit_id, _ts(), _ts()))

    conn.commit()
    conn.close()


# ---------------------------------------------------------------
# INTERNAL: Dispatch a single unit
# ---------------------------------------------------------------
def dispatch_single_unit(incident_id: int, unit_id: str, user: str):
    """
    Dispatch pipeline for ONE unit:
      - create assignment
      - set status AVAILABLE → ENROUTE
      - mirror apparatus crew
      - narrative
      - daily log
    """

    # 1) Create UnitAssignment if needed
    create_unit_assignment(incident_id, unit_id)

    # 2) Change unit status → ENROUTE
    change_unit_status(unit_id, incident_id, "ENROUTE", user)

    # Status change already:
    # - Mirrors apparatus crew
    # - Logs daily log entry
    # - Writes narrative


# ---------------------------------------------------------------
# INTERNAL: Dispatch crew when apparatus selected
# ---------------------------------------------------------------
def get_apparatus_crew_members(app_unit_id: str):
    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT personnel_id
        FROM PersonnelAssignments
        WHERE apparatus_id=?
        ORDER BY personnel_id ASC
    """, (app_unit_id,)).fetchall()

    conn.close()
    return [r["personnel_id"] for r in rows]


# ---------------------------------------------------------------
# PUBLIC ENDPOINT — DISPATCH MULTIPLE UNITS (Picker)
# ---------------------------------------------------------------
@app.post("/incident/<incident_id>/dispatch_units")
async def dispatch_units_api(request: Request, incident_id: int):

    data = await request.json()
    units = data.get("units", [])
    user = request.session.get("user", "Dispatcher")

    if not isinstance(units, list) or len(units) == 0:
        return {"ok": False, "error": "No units provided."}

    # Convert incident_id to int
    try:
        incident_id = int(incident_id)
    except:
        return {"ok": False, "error": "Invalid incident ID."}

    # ----------------------------
    # RUN DISPATCH PIPELINE
    # ----------------------------

    # Promote OPEN → ACTIVE BEFORE dispatch status changes
    promote_incident_if_needed(incident_id)

    dispatched_units = []

    for uid in units:
        uid = str(uid)

        # 1) Dispatch main unit
        dispatch_single_unit(incident_id, uid, user)
        dispatched_units.append(uid)

        # 2) If apparatus → auto dispatch crew
        conn = get_conn()
        c = conn.cursor()
        row = c.execute("""
            SELECT is_apparatus FROM Units WHERE unit_id=?
        """, (uid,)).fetchone()
        conn.close()

        if row and row["is_apparatus"] == 1:
            crew = get_apparatus_crew_members(uid)

            for cid in crew:
                dispatch_single_unit(incident_id, cid, user)
                dispatched_units.append(cid)

    # ----------------------------
    # Write master narrative line
    # ----------------------------
    add_narrative(
        incident_id,
        user,
        f"Dispatched units: {', '.join(dispatched_units)}"
    )

    # ----------------------------
    # DailyLog entry
    # ----------------------------
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO DailyLog (timestamp, unit_id, action, details)
        VALUES (?, ?, 'DISPATCH', ?)
    """, (_ts(), "SYS", f"Incident {incident_id}: {', '.join(dispatched_units)}"))
    conn.commit()
    conn.close()

    # Return success
    return {"ok": True, "units": dispatched_units}
# ================================================================
# BLOCK 15 — UNIT CLEAR / DISPOSITION ENGINE (Phase-3 Enterprise)
# Handles:
#   • Unit clear actions
#   • Unit dispositions (R, NA, NF, CT, FA, O, etc.)
#   • Auto-detect last unit clearing
#   • Auto-trigger Event Disposition modal
#   • Narrative + DailyLog
#   • Crew mirror clearing
# ================================================================

# ---------------------------------------------------------------
# VALID DISPOSITION CODES (Phase-3 Canon)
# ---------------------------------------------------------------
VALID_DISPOSITIONS = {
    "R":  "Released",
    "NA": "No Action",
    "NF": "No Fire Found",
    "CT": "Controlled / Terminated",
    "FA": "False Alarm",
    "O":  "Other"
}


# ---------------------------------------------------------------
# Add disposition to UnitDispositions table
# ---------------------------------------------------------------
def write_unit_disposition(unit_id: str, incident_id: int, code: str, user: str):
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        INSERT INTO UnitDispositions (
            incident_id, unit_id, disposition_code,
            timestamp, user
        )
        VALUES (?, ?, ?, ?, ?)
    """, (incident_id, unit_id, code, _ts(), user))

    conn.commit()
    conn.close()


# ---------------------------------------------------------------
# Set CLEARED timestamp in UnitAssignments
# ---------------------------------------------------------------
def mark_assignment_cleared(unit_id: str, incident_id: int):
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        UPDATE UnitAssignments
        SET cleared=?, last_update=?
        WHERE incident_id=? AND unit_id=?
    """, (
        _ts(),          # cleared
        _ts(),          # last_update
        incident_id,
        unit_id
    ))

    conn.commit()
    conn.close()



# ---------------------------------------------------------------
# Remove unit from incident logically (status + mirror)
# ---------------------------------------------------------------
def clear_unit_status_pipeline(unit_id: str, user: str):
    """
    Called when a unit clears an incident.
    Sets status AVAILABLE and mirrors apparatus crew.
    """

    # Update status to AVAILABLE
    change_unit_status(unit_id, None, "AVAILABLE", user)

    # If this is an apparatus, mirror crew status as well
    conn = get_conn()
    c = conn.cursor()
    row = c.execute("SELECT is_apparatus FROM Units WHERE unit_id=?", (unit_id,)).fetchone()
    conn.close()

    if row and row["is_apparatus"] == 1:
        crew = get_apparatus_crew_members(unit_id)
        for cid in crew:
            change_unit_status(cid, None, "AVAILABLE", user)


# ---------------------------------------------------------------
# Determine if incident has any remaining assigned units
# ---------------------------------------------------------------
def remaining_units_on_incident(incident_id: int) -> int:
    conn = get_conn()
    c = conn.cursor()

    row = c.execute("""
        SELECT COUNT(*) AS n
        FROM UnitAssignments
        WHERE incident_id=?
          AND cleared IS NULL
    """, (incident_id,)).fetchone()

    conn.close()
    return row["n"] if row else 0


# ---------------------------------------------------------------
# Auto-trigger Event Disposition (if last unit clears)
# ---------------------------------------------------------------
def auto_handle_last_unit(incident_id: int):
    """
    When the last unit clears, the incident should enter the
    event disposition stage.
    """

    if remaining_units_on_incident(incident_id) > 0:
        return  # Not last unit

    # No units remain: mark incident to DISPOSITION_PENDING

    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        UPDATE Incidents
        SET status='DISPOSITION_PENDING', updated=?
        WHERE incident_id=?
    """, (_ts(), incident_id))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------
# PUBLIC ENDPOINT — CLEAR UNIT WITH DISPOSITION
# ---------------------------------------------------------------
@app.post("/incident/<incident_id>/unit/<unit_id>/clear")
async def clear_unit_api(request: Request, incident_id: int, unit_id: str):

    data = await request.json()
    disposition = data.get("disposition", "").upper().strip()
    user = request.session.get("user", "Dispatcher")

    # Validate disposition
    if disposition not in VALID_DISPOSITIONS:
        return {"ok": False, "error": "Invalid disposition code."}

    # --------------------------------------
    # STEP 1 — Write disposition record
    # --------------------------------------
    write_unit_disposition(unit_id, incident_id, disposition, user)

    # --------------------------------------
    # STEP 2 — Mark assignment cleared
    # --------------------------------------
    mark_assignment_cleared(unit_id, incident_id)

    # --------------------------------------
    # STEP 3 — Update unit status → AVAILABLE
    # --------------------------------------
    clear_unit_status_pipeline(unit_id, user)

    # --------------------------------------
    # STEP 4 — Narrative
    # --------------------------------------
    add_narrative(
        incident_id,
        user,
        f"{unit_id} cleared — disposition {disposition} ({VALID_DISPOSITIONS[disposition]})"
    )

    # --------------------------------------
    # STEP 5 — DailyLog
    # --------------------------------------
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO DailyLog (timestamp, unit_id, action, details)
        VALUES (?, ?, 'CLEAR', ?)
    """, (_ts(), unit_id, f"Cleared incident {incident_id} with disposition {disposition}"))
    conn.commit()
    conn.close()

    # --------------------------------------
    # STEP 6 — Check if last unit
    # --------------------------------------
    auto_handle_last_unit(incident_id)

    return {"ok": True, "cleared": unit_id, "disposition": disposition}
# ================================================================
# BLOCK 16 — EVENT DISPOSITION ENGINE (Phase-3 Enterprise)
# Handles:
#   • Event-level disposition (end-of-incident outcome)
#   • Auto-close of incident
#   • Narrative + DailyLog entries
#   • Issue Found flag preservation
#   • Modal loading for IAW
# ================================================================

# ---------------------------------------------------------------
# OFFICIAL EVENT DISPOSITION OUTCOMES (Phase-3 Canon)
# ---------------------------------------------------------------
EVENT_OUTCOME_MAP = {
    "FA":  "False Alarm",
    "NF":  "No Fire Found",
    "M":   "Medical Call",
    "T":   "Transport",
    "CT":  "Controlled / Terminated",
    "R":   "Resolved",
    "O":   "Other"
}


# ---------------------------------------------------------------
# Insert event disposition into IncidentDispositions table
# ---------------------------------------------------------------
def write_event_disposition(incident_id: int, code: str, user: str, notes: str = ""):
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        INSERT INTO IncidentDispositions (
            incident_id, disposition_code, timestamp, user, notes
        )
        VALUES (?, ?, ?, ?, ?)
    """, (incident_id, code, _ts(), user, notes))

    conn.commit()
    conn.close()


# ---------------------------------------------------------------
# Mark incident CLOSED
# ---------------------------------------------------------------
def close_incident(incident_id: int, code: str, outcome_desc: str):
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        UPDATE Incidents
        SET status='CLOSED',
            disposition=?,
            updated=?
        WHERE incident_id=?
    """, (outcome_desc, _ts(), incident_id))

    conn.commit()
    conn.close()


# ---------------------------------------------------------------
# Write Daily Log entry for event disposition
# ---------------------------------------------------------------
def log_event_disposition(incident_id: int, code: str, user: str, notes: str):
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        INSERT INTO DailyLog (timestamp, unit_id, action, details)
        VALUES (?, NULL, 'EVENT_DISPOSITION', ?)
    """, (_ts(), f"Incident {incident_id}: {code} — {notes or EVENT_OUTCOME_MAP.get(code, '')}"))

    conn.commit()
    conn.close()


# ---------------------------------------------------------------
# PUBLIC ENDPOINT — Submit Event Disposition
# ---------------------------------------------------------------
@app.post("/incident/<incident_id>/event_disposition")
async def event_disposition_submit(request: Request, incident_id: int):
    """
    Final step of the incident. The dispatcher selects the official
    outcome (FA, NF, M, T, CT, R, O). This closes the incident.
    """
    data = await request.json()

    code = (data.get("code") or "").upper().strip()
    notes = data.get("notes", "").strip()
    user = request.session.get("user", "Dispatcher")

    # Validate
    if code not in EVENT_OUTCOME_MAP:
        return {"ok": False, "error": "Invalid event disposition code."}

    outcome_desc = EVENT_OUTCOME_MAP[code]

    # -----------------------------------------------------------
    # STEP 1 — Write disposition record
    # -----------------------------------------------------------
    write_event_disposition(incident_id, code, user, notes)

    # -----------------------------------------------------------
    # STEP 2 — Write narrative
    # -----------------------------------------------------------
    narrative_text = f"Event disposition set to {code} ({outcome_desc})"
    if notes:
        narrative_text += f": {notes}"

    add_narrative(incident_id, user, narrative_text)

    # -----------------------------------------------------------
    # STEP 3 — Daily Log
    # -----------------------------------------------------------
    log_event_disposition(incident_id, code, user, notes)

    # -----------------------------------------------------------
    # STEP 4 — Close incident
    # -----------------------------------------------------------
    close_incident(incident_id, code, outcome_desc)

    return {"ok": True, "incident_id": incident_id, "closed": True}


# ---------------------------------------------------------------
# PUBLIC ENDPOINT — Load Event Disposition Modal
# ---------------------------------------------------------------
@app.get("/incident/<incident_id>/event_disposition_modal",
         response_class=HTMLResponse)
async def event_disposition_modal(request: Request, incident_id: int):
    """
    Returns the HTML modal for selecting final event disposition.
    """
    return templates.TemplateResponse("event_disposition_modal.html", {
        "request": request,
        "incident_id": incident_id
    })
# ================================================================
# BLOCK 17 — ISSUE FOUND ENGINE (Phase-3 Enterprise)
# Enables:
#   • Issue creation
#   • Issue retrieval
#   • Incident has_issue flag
#   • ⚠ indicator in incident lists
#   • IAW population of issue list
# ================================================================


# ---------------------------------------------------------------
# Ensure has_issue column exists on Incidents table
# ---------------------------------------------------------------
def ensure_issue_flag_column():
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("ALTER TABLE Incidents ADD COLUMN has_issue INTEGER DEFAULT 0")
        conn.commit()
    except Exception:
        pass  # already exists
    conn.close()


ensure_issue_flag_column()


# ---------------------------------------------------------------
# Insert new issue + mark incident flagged
# ---------------------------------------------------------------
def add_issue(incident_id: int, category: str, description: str,
              resolution: str, followup_required: int, user: str):
    
    conn = get_conn()
    c = conn.cursor()

    # Insert into Issues table
    c.execute("""
        INSERT INTO Issues (
            incident_id, category, description, resolution,
            followup_required, reported_by, timestamp
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (incident_id, category, description, resolution,
          followup_required, user, _ts()))

    # Mark the parent incident as having an issue
    c.execute("""
        UPDATE Incidents
        SET has_issue = 1, updated=?
        WHERE incident_id=?
    """, (_ts(), incident_id))

    conn.commit()
    conn.close()

    # Narrative entry
    narrative_text = f"Issue Recorded — Category: {category}. Description: {description}"
    add_narrative(incident_id, user, narrative_text)


# ---------------------------------------------------------------
# Retrieve all issues for a given incident
# ---------------------------------------------------------------
def get_issues_for_incident(incident_id: int):
    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT *
        FROM Issues
        WHERE incident_id=?
        ORDER BY timestamp ASC
    """, (incident_id,)).fetchall()

    conn.close()

    return [dict(r) for r in rows]


# ---------------------------------------------------------------
# PUBLIC ENDPOINT — Issue Modal Submission
# (Called by remark.js → submitIssue() in modal)
# ---------------------------------------------------------------
@app.post("/incident/<incident_id>/issue_found")
async def issue_found_submit(request: Request, incident_id: int):
    data = await request.json()

    category = data.get("category", "").strip()
    description = data.get("description", "").strip()
    resolution = data.get("resolution", "").strip()
    followup = int(data.get("followup", 0))
    user = request.session.get("user", "Dispatcher")

    if not description:
        return {"ok": False, "error": "Description required"}

    add_issue(incident_id, category, description, resolution, followup, user)

    # Refresh IAW & panels
    return {"ok": True, "incident_id": incident_id}


# ---------------------------------------------------------------
# PUBLIC ENDPOINT — Load Issue Modal (View or New)
# ---------------------------------------------------------------
@app.get("/incident/<incident_id>/issue_modal",
         response_class=HTMLResponse)
async def issue_modal_loader(request: Request, incident_id: int):
    """
    Loads issue modal in two modes:
       • mode='new'  → for creating new issue
       • mode='view' → shows existing details if editing/viewing
    """
    mode = request.query_params.get("mode", "new")
    issue_id = request.query_params.get("issue_id", None)

    issue = None
    if issue_id:
        conn = get_conn()
        c = conn.cursor()
        issue = c.execute("SELECT * FROM Issues WHERE id=?", (issue_id,)).fetchone()
        conn.close()

    return templates.TemplateResponse("issue_found_modal.html", {
        "request": request,
        "incident_id": incident_id,
        "mode": mode,
        "issue": issue
    })


# ---------------------------------------------------------------
# INJECT ISSUE FLAGS INTO INCIDENT LISTS
# Applies to:
#   • Active panel
#   • Open panel
#   • Held panel
# ---------------------------------------------------------------
def inject_issue_flags(rows):
    """
    Adds a boolean field rows[n]['has_issue'] for templates to show ⚠
    """
    out = []
    for r in rows:
        d = dict(r)
        d.setdefault("has_issue", 0)
        out.append(d)
    return out


@app.get("/panel/active", response_class=HTMLResponse)
async def panel_active(request: Request):
    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT *
        FROM Incidents
        WHERE status='ACTIVE'
        ORDER BY updated DESC
    """).fetchall()
    conn.close()

    rows = inject_issue_flags(rows)

    return templates.TemplateResponse("active_incidents.html", {
        "request": request,
        "incidents": rows
    })


@app.get("/panel/open", response_class=HTMLResponse)
async def panel_open(request: Request):
    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT *
        FROM Incidents
        WHERE status='OPEN'
        ORDER BY updated DESC
    """).fetchall()
    conn.close()

    rows = inject_issue_flags(rows)

    return templates.TemplateResponse("open_incidents.html", {
        "request": request,
        "incidents": rows
    })


@app.get("/panel/held", response_class=HTMLResponse)
async def panel_held(request: Request):
    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT *
        FROM Incidents
        WHERE status='HELD'
        ORDER BY updated DESC
    """).fetchall()
    conn.close()

    rows = inject_issue_flags(rows)

    return templates.TemplateResponse("held_incidents.html", {
        "request": request,
        "incidents": rows
    })


# ----------------------------------------------------------------
# Preserve original panel handlers (for future patching / overrides)
# ----------------------------------------------------------------
_original_panel_open = panel_open
_original_panel_held = panel_held

# ================================================================
# BLOCK 18 — INCIDENT ACTION WINDOW ENGINE (Phase-3 Enterprise)
# Provides:
#   • /incident/<id>/iaw_units
#   • /incident/<id>/iaw_narrative
#   • /incident/<id>/iaw_issues
#   • /incident/<id>/dispatch_units  (picker submit)
#   • /incident/<id>/remark
#   • /incident/<id>/unit_clear
# ================================================================


# ---------------------------------------------------------------
# 18.1 — IAW UNITS PANEL ENDPOINT
# ---------------------------------------------------------------
@app.get("/incident/{incident_id}/iaw_units", response_class=HTMLResponse)
async def iaw_units(request: Request, incident_id: int):

    assigned = get_incident_units(incident_id)

    # Normalize display fields
    for u in assigned:
        u.setdefault("unit_id", "")
        u.setdefault("status", "")
        u.setdefault("dispatched", "")
        u.setdefault("enroute", "")
        u.setdefault("arrived", "")
        u.setdefault("cleared", "")

    return templates.TemplateResponse("partials/iaw_units.html", {
        "request": request,
        "incident_id": incident_id,
        "units": assigned
    })


# ---------------------------------------------------------------
# 18.2 — IAW NARRATIVE PANEL ENDPOINT
# ---------------------------------------------------------------
@app.get("/incident/{incident_id}/iaw_narrative", response_class=HTMLResponse)
async def iaw_narrative(request: Request, incident_id: int):

    entries = get_narrative(incident_id)

    return templates.TemplateResponse("partials/iaw_narrative.html", {
        "request": request,
        "entries": entries,
        "incident_id": incident_id
    })


# ---------------------------------------------------------------
# 18.3 — IAW ISSUES PANEL ENDPOINT
# ---------------------------------------------------------------
@app.get("/incident/{incident_id}/iaw_issues", response_class=HTMLResponse)
async def iaw_issues(request: Request, incident_id: int):

    issues = get_issues_for_incident(incident_id)

    return templates.TemplateResponse("partials/iaw_issues.html", {
        "request": request,
        "incident_id": incident_id,
        "issues": issues
    })


# ================================================================
# 18.4 — DISPATCH PICKER SUBMISSION HANDLER
#     Called by PICKER.submitSelection()
# ================================================================
@app.post("/legacy/incident/{incident_id}/dispatch_units__v3")
async def dispatch_units_handler(request: Request, incident_id: int):

    data = await request.json()
    units = data.get("units", [])
    user = request.session.get("user", "Dispatcher")

    if not units:
        return {"ok": False, "error": "No units selected."}

    conn = get_conn()
    c = conn.cursor()

    # Promote incident to ACTIVE if still OPEN
    c.execute("""
        UPDATE Incidents
        SET status='ACTIVE', updated=?
        WHERE incident_id=? AND status='OPEN'
    """, (_ts(), incident_id))

    conn.commit()
    conn.close()

    # Assign units (avoids duplicates)
    for uid in units:
        assign_unit_to_incident(incident_id, uid)
        set_unit_status_pipeline(uid, "ENROUTE")

    # Write grouped narrative
    unit_list = ", ".join(units)
    incident_history(incident_id, "DISPATCH", user=user, details=f"Dispatched units: {unit_list}")
    masterlog("UNITS_DISPATCHED", user=user, incident_id=incident_id, details=f"Units: {unit_list}")

    return {"ok": True}


# ================================================================
# 18.5 — IAW REMARK ENDPOINT
# ================================================================
@app.post("/legacy/incident/{incident_id}/remark__v6")
async def iaw_remark(request: Request, incident_id: int):

    data = await request.json()
    remark = data.get("text", "").strip()
    user = request.session.get("user", "Dispatcher")

    if not remark:
        return {"ok": False, "error": "Empty remark not allowed."}

    add_narrative(incident_id, user, f"Remark — {remark}")

    return {"ok": True}


# ================================================================
# 18.6 — CLEAR UNIT (IAW → Disposition Engine)
#     This is the "Clear Unit" button in IAW
# ================================================================
@app.post("/incident/{incident_id}/unit_clear/{unit_id}")
async def clear_unit(request: Request, incident_id: int, unit_id: str):

    user = request.session.get("user", "Dispatcher")

    conn = get_conn()
    c = conn.cursor()

    # Mark cleared timestamp in UnitAssignments
    c.execute("""
        UPDATE UnitAssignments
        SET cleared=?
        WHERE incident_id=? AND unit_id=?
    """, (_ts(), incident_id, unit_id))

    conn.commit()
    conn.close()

    # Change status to AVAILABLE
    set_unit_status_pipeline(unit_id, "AVAILABLE")

    add_narrative(incident_id, user, f"Unit {unit_id} cleared the incident")

    # Check if this was the last assigned unit
    conn = get_conn()
    c = conn.cursor()
    remaining = c.execute("""
        SELECT COUNT(*)
        FROM UnitAssignments
        WHERE incident_id=? AND cleared IS NULL
    """, (incident_id,)).fetchone()
    conn.close()

    if remaining[0] == 0:
        auto_close_incident(incident_id, user)

    return {"ok": True}


# ---------------------------------------------------------------
# 18.7 — AUTO-CLOSE INCIDENT WHEN LAST UNIT CLEARS
# ---------------------------------------------------------------
def auto_close_incident(incident_id: int, user: str):

    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        UPDATE Incidents
        SET status='CLOSED', updated=?
        WHERE incident_id=?
    """, (_ts(), incident_id))

    conn.commit()
    conn.close()

    add_narrative(incident_id, user, "Incident closed — all units cleared")

    # Daily Log entry
    c = get_conn().cursor()
    c.execute("""
        INSERT INTO DailyLog (timestamp, action, details)
        VALUES (?, 'INCIDENT_CLOSED', ?)
    """, (_ts(), f"Incident {incident_id} closed"))
    c.connection.commit()
    c.connection.close()
# ================================================================
# BLOCK 19 — EVENT DISPOSITION ENGINE (Phase-3 Enterprise)
#
# Provides:
#   • /incident/<id>/disposition  (POST)
#   • auto-close logic
#   • rule checks (no closing active incident with units still assigned)
#   • narrative entries
#   • daily log entries
# ================================================================


# ---------------------------------------------------------------
# Helper — Check if incident has active (uncleared) units
# ---------------------------------------------------------------
def incident_has_active_units(incident_id: int) -> bool:
    conn = get_conn()
    c = conn.cursor()
    row = c.execute("""
        SELECT COUNT(*) AS n
        FROM UnitAssignments
        WHERE incident_id=? AND cleared IS NULL
    """, (incident_id,)).fetchone()
    conn.close()

    return row["n"] > 0


# ---------------------------------------------------------------
# Helper — Validate disposition code
# ---------------------------------------------------------------
VALID_DISPOSITION_CODES = {
    "FA": "Fire Alarm",
    "R" : "Responded",
    "NF": "No Fire",
    "C" : "Cancelled",
    "CT": "Cancelled enroute",
    "T" : "Transported",
    "O" : "Other"
}

def is_valid_disposition(code: str) -> bool:
    return code.upper() in VALID_DISPOSITION_CODES


# ---------------------------------------------------------------
# Helper — Write disposition record
# ---------------------------------------------------------------
def add_disposition_record(incident_id: int, user: str, code: str, notes: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO IncidentDispositions (incident_id, timestamp, disposition_code, notes, user)
        VALUES (?, ?, ?, ?, ?)
    """, (incident_id, _ts(), code, notes, user))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------
# Helper — Close incident officially after disposition
# ---------------------------------------------------------------
def close_incident_with_disposition(incident_id: int, code: str, user: str):
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        UPDATE Incidents
        SET status='CLOSED', updated=?
        WHERE incident_id=?
    """, (_ts(), incident_id))

    conn.commit()
    conn.close()

    # Narrative line
    desc = VALID_DISPOSITION_CODES.get(code, code)
    add_narrative(incident_id, user, f"Incident closed with disposition: {desc} ({code})")

    # Daily log entry
    c = get_conn().cursor()
    c.execute("""
        INSERT INTO DailyLog (timestamp, action, details)
        VALUES (?, 'INCIDENT_DISPOSITION', ?)
    """, (_ts(), f"Incident {incident_id} closed with disposition {code}"))
    c.connection.commit()
    c.connection.close()


# ================================================================
# 19.1 — DISPOSITION SUBMISSION HANDLER
#       Called by Event Disposition Modal
# ================================================================
@app.post("/legacy/incident/{incident_id}/disposition__v7")
async def incident_disposition(request: Request, incident_id: int):

    data = await request.json()
    code  = (data.get("code") or "").upper().strip()
    notes = (data.get("notes") or "").strip()
    user  = request.session.get("user", "Dispatcher")

    # ---------- Validate code ----------
    if not is_valid_disposition(code):
        return {"ok": False, "error": "Invalid disposition code."}

    # ---------- Ensure incident exists ----------
    conn = get_conn()
    c = conn.cursor()
    inc = c.execute("""
        SELECT status FROM Incidents WHERE incident_id=?
    """, (incident_id,)).fetchone()
    conn.close()

    if not inc:
        return {"ok": False, "error": "Incident does not exist."}

    status = inc["status"].upper()

    # ---------- Block dispositions on HELD ----------
    if status == "HELD":
        return {"ok": False, "error": "Cannot close a HELD incident."}

    # ---------- Cannot close if units still active ----------
    if incident_has_active_units(incident_id):
        return {"ok": False, "error": "Units are still assigned — cannot close incident."}

    # ---------- Write disposition record ----------
    add_disposition_record(incident_id, user, code, notes)

    # ---------- Close incident ----------
    close_incident_with_disposition(incident_id, code, user)

    return {"ok": True}
# ================================================================
# BLOCK 20 — DAILY LOG VIEWER BACKEND
# Phase-3 Enterprise Edition
#
# Provides:
#   • /dailylog  (HTML log viewer)
#   • /api/dailylog?date=YYYY-MM-DD
#   • Canonical BOSK daily log ordering
#   • Filters for date, incident, unit, action
#   • Clean JSON feed for HTMX viewer panel
# ================================================================


# ---------------------------------------------------------------
# Helper — Normalize date string → YYYY-MM-DD
# ---------------------------------------------------------------
def normalize_date(datestr: str) -> str:
    """
    Accepts:
        12/07/2025
        2025-12-07
    Returns:
        2025-12-07 (ISO)
    """
    if "-" in datestr:
        return datestr.strip()

    try:
        m, d, y = datestr.split("/")
        return f"{y}-{int(m):02d}-{int(d):02d}"
    except:
        return datetime.datetime.datetime.now().strftime("%Y-%m-%d")


# ---------------------------------------------------------------
# Helper — Fetch log for a given date
# ---------------------------------------------------------------
def fetch_daily_log(date_iso: str):
    """
    Returns all DailyLog entries for a calendar date.
    Date stored in DB uses full timestamp; so we filter by LIKE prefix.
    """
    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT log_id, timestamp, unit_id, incident_id, action, details
        FROM DailyLog
        WHERE timestamp LIKE ?
        ORDER BY timestamp ASC
    """, (f"{date_iso}%",)).fetchall()

    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------
# Helper — Process log entries into display-friendly format
# ---------------------------------------------------------------
def process_daily_log(entries: list[dict]):
    """
    Cleans fields and returns sorted display entries.
    """
    out = []
    for e in entries:
        item = {
            "log_id": e["log_id"],
            "timestamp": e["timestamp"],
            "unit": e.get("unit_id") or "",
            "incident": e.get("incident_id") or "",
            "action": (e.get("action") or "").upper(),
            "details": e.get("details") or ""
        }
        out.append(item)

    return sorted(out, key=lambda x: x["timestamp"])


# ---------------------------------------------------------------
# API ENDPOINT — JSON log feed for the date
# ---------------------------------------------------------------
@app.get("/api/dailylog")
async def api_dailylog(date: str = None):
    """
    date = YYYY-MM-DD or MM/DD/YYYY
    If date missing → defaults to today.
    """
    if not date:
        date = datetime.datetime.datetime.now().strftime("%Y-%m-%d")

    date_iso = normalize_date(date)
    raw = fetch_daily_log(date_iso)
    processed = process_daily_log(raw)

    return {"ok": True, "date": date_iso, "entries": processed}


# ---------------------------------------------------------------
# HTML VIEWER ENDPOINT — Loads Daily Log Viewer Template
# ---------------------------------------------------------------
@app.get("/dailylog", response_class=HTMLResponse)
async def dailylog_viewer(request: Request):
    """
    Loads a full-screen modal/page template which will
    request /api/dailylog via HTMX for the selected date.
    """
    today_iso = datetime.datetime.datetime.now().strftime("%Y-%m-%d")
    return templates.TemplateResponse("daily_log.html", {
        "request": request,
        "default_date": today_iso
    })

# Deferred bindings (do not alter logic)
_original_panel_active = panel_active
_original_panel_open = panel_open
_original_panel_held = panel_held