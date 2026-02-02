_IMPORT_PHASE = True

# ============================================================================
# FORD-CAD — PHASE-3 CORE BACKEND (CAD2)
# ============================================================================
# Phase-3 Stabilization
# Block A — Import-Safe Definitions Only
#
# RULES:
#   • NO database access (outside guarded helpers)
#   • NO unit import
#   • Definitions ONLY
# ============================================================================

from fastapi import FastAPI, Request, Body, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from pathlib import Path
import sqlite3
import datetime
import re
from contextvars import ContextVar
import os
import base64
import hashlib
import hmac


# ================================================================
# PATHS
# ================================================================

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "cad.db"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
UNITLOG_PATH = BASE_DIR / "UnitLog.txt"

# ================================================================
# FASTAPI APP
# ================================================================

app = FastAPI(title="FORD-CAD Phase-3")
app.add_middleware(SessionMiddleware, secret_key="cad-secret-key")

# ================================================================
# MASTERLOG GUARANTEE (ALL MUTATIONS ARE AUDITED)
# ================================================================

MASTERLOG_WRITTEN: ContextVar[bool] = ContextVar('MASTERLOG_WRITTEN', default=False)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ================================================================
# REPORTS & MESSAGING MODULE
# ================================================================
try:
    import reports
    reports.register_report_routes(app)
    print("[MAIN] Reports module loaded")

    # Optional: Start report scheduler as background thread
    import os
    import threading
    if os.getenv("CAD_ENABLE_REPORT_SCHEDULER", "false").lower() == "true":
        scheduler_thread = threading.Thread(target=reports.run_scheduler, daemon=True)
        scheduler_thread.start()
        print("[MAIN] Report scheduler started (30 min before shift change)")
except ImportError as e:
    print(f"[MAIN] Reports module not available: {e}")

# ------------------------------------------------
# Middleware: guarantee every mutation is written to MasterLog
# ------------------------------------------------
@app.middleware("http")
async def masterlog_guard(request: Request, call_next):
    """Guarantee: every mutating request produces a MasterLog entry.

    If a handler already called masterlog(), we do nothing.
    Otherwise we write a generic fallback entry (HTTP_METHOD + path).
    """
    # Reset per-request flag
    MASTERLOG_WRITTEN.set(False)

    # Skip static and non-mutating verbs
    if request.url.path.startswith("/static") or request.method in ("GET", "HEAD", "OPTIONS"):
        return await call_next(request)

    # Read body safely and re-inject for downstream
    body_bytes = await request.body()

    async def _receive():
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    req2 = Request(request.scope, _receive)

    response = await call_next(req2)

    # If handler already wrote to MasterLog, do nothing
    if MASTERLOG_WRITTEN.get():
        return response

    # Generic audit fallback
    try:
        user = (req2.session.get("user") if hasattr(req2, "session") else None) or "Dispatcher"
    except Exception:
        user = "Dispatcher"

    ok = 1 if getattr(response, "status_code", 200) < 400 else 0

    incident_id = None
    unit_id = None

    # Path-based hints
    m = re.search(r"/incident/(\d+)", req2.url.path)
    if m:
        try:
            incident_id = int(m.group(1))
        except Exception:
            incident_id = None

    m2 = re.search(r"/unit/([^/]+)", req2.url.path)
    if m2:
        unit_id = m2.group(1)

    # Body-based hints (JSON) for better attribution
    details = None
    try:
        if body_bytes:
            b = body_bytes.decode("utf-8", "ignore")
            details = b[:800]
            jm = re.search(r'"incident_id"\s*:\s*(\d+)', b)
            if jm and incident_id is None:
                incident_id = int(jm.group(1))
            um = re.search(r'"unit_id"\s*:\s*"([^"]+)"', b)
            if um and unit_id is None:
                unit_id = um.group(1)
    except Exception:
        details = None

    event = f"HTTP_{req2.method} {req2.url.path}"[:80]

    try:
        masterlog(event_type=event, user=user, incident_id=incident_id, unit_id=unit_id, ok=ok, reason=None, details=details)
        if incident_id:
            incident_history(incident_id=incident_id, event_type=event, user=user, unit_id=unit_id, details=(details or ""))
    except Exception:
        # never break the request path due to audit logging
        pass

    return response

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)

# ------------------------------------------------
# Middleware: Prevent caching of HTML pages
# ------------------------------------------------
@app.middleware("http")
async def no_cache_html(request: Request, call_next):
    """Prevent browsers from caching HTML pages."""
    response = await call_next(request)

    # Add no-cache headers to HTML responses (not static assets)
    if not request.url.path.startswith("/static"):
        content_type = response.headers.get("content-type", "")
        if "text/html" in content_type or request.url.path in ("/", "/login", "/logout"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"

    return response


# ================================================================
# ROOT ROUTE (NO DB ACCESS)
# ================================================================

@app.get("/", response_class=HTMLResponse)
async def root_view(request: Request):
    # Phase-3 "Login" is not security auth yet — it is a session initializer
    # that sets dispatcher identity + shift context (A/B/C/D + effective A/B).

    # Backward-compatible: accept legacy session["shift"] if present
    shift_letter = (request.session.get("shift_letter") or request.session.get("shift") or "").strip().upper()
    # Standalone login gate: do not load the CAD console until shift context is set.
    if not shift_letter:
        return RedirectResponse(url="/login", status_code=302)
    shift_effective = (request.session.get("shift_effective") or "").strip().upper()

    user = (request.session.get("user") or "").strip() or "Dispatcher"
    unit = (request.session.get("dispatcher_unit") or request.session.get("unit") or "").strip() or user

    # Safe fallback if a shift letter exists but effective wasn't stored yet.
    if shift_letter and shift_effective not in ("A", "B"):
        shift_effective = ("A" if shift_letter in ("A", "C") else "B")

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "title": "Ford CAD Dispatch System",
            "today_date": datetime.datetime.now().strftime("%m/%d/%Y"),
            "shift": shift_letter,
            "shift_effective": shift_effective,
            "unit": unit,
            "user": user,
            "is_admin": bool(request.session.get("is_admin") or False),
        }
    )
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    # If already logged in, go to console
    if get_session_shift_letter(request):
        return RedirectResponse(url="/", status_code=302)

    suggested = determine_current_shift()
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "dispatcher_options": _dispatcher_options(),
            "suggested_shift_letter": suggested,
            "dispatcher_unit": "",
            "shift_letter": suggested,
            "require_password": False,
            "error": "",
        },
    )


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request):
    form = await request.form()
    dispatcher_unit = (form.get("dispatcher_unit") or "").strip()
    shift_letter = (form.get("shift_letter") or "").strip().upper()
    password = (form.get("password") or "").strip()
    require_password = bool(form.get("require_password"))

    if not dispatcher_unit:
        suggested = determine_current_shift()
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "dispatcher_options": _dispatcher_options(),
                "suggested_shift_letter": suggested,
                "dispatcher_unit": "",
                "shift_letter": shift_letter or suggested,
                "require_password": require_password,
                "error": "Unit ID is required.",
            },
        )

    # Resolve display name from Units table if possible (sqlite3.Row has no .get)
    ensure_phase3_schema()
    display_name = ""
    conn = get_conn()
    try:
        r = conn.execute(
            "SELECT name FROM Units WHERE unit_id = ?",
            (dispatcher_unit,),
        ).fetchone()

        if r is not None:
            # sqlite3.Row supports index access and key access, not .get()
            try:
                display_name = (r["name"] or "").strip()
            except Exception:
                try:
                    display_name = (r[0] or "").strip()
                except Exception:
                    display_name = ""
    finally:
        conn.close()


    is_admin = _is_admin_unit(dispatcher_unit)

    # Load existing account
    acct = _get_user_account(dispatcher_unit)
    acct_pw = (acct.get("password_hash") if acct else "") or ""
    acct_req = bool(int(acct.get("require_password") or 0)) if acct else False

    # Admins must have a password
    if is_admin:
        if not acct_pw:
            # First admin login must set password
            if not password:
                suggested = determine_current_shift()
                return templates.TemplateResponse(
                    "login.html",
                    {
                        "request": request,
                        "dispatcher_options": _dispatcher_options(),
                        "suggested_shift_letter": suggested,
                        "dispatcher_unit": dispatcher_unit,
                        "shift_letter": shift_letter or suggested,
                        "require_password": True,
                        "error": "Admin password required. Set your password to continue.",
                    },
                )
            _upsert_user_account(dispatcher_unit, display_name, True, True, password)
        else:
            # Existing admin must verify password
            if not password or not _pw_verify(password, acct_pw):
                suggested = determine_current_shift()
                return templates.TemplateResponse(
                    "login.html",
                    {
                        "request": request,
                        "dispatcher_options": _dispatcher_options(),
                        "suggested_shift_letter": suggested,
                        "dispatcher_unit": dispatcher_unit,
                        "shift_letter": shift_letter or suggested,
                        "require_password": True,
                        "error": "Invalid admin password.",
                    },
                )
            # Allow toggling require_password (admins always effectively required)
            _upsert_user_account(dispatcher_unit, display_name, True, True, None)
    else:
        # Non-admin: password optional unless require_password already enabled
        if acct_req and not password:
            suggested = determine_current_shift()
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "dispatcher_options": _dispatcher_options(),
                    "suggested_shift_letter": suggested,
                    "dispatcher_unit": dispatcher_unit,
                    "shift_letter": shift_letter or suggested,
                    "require_password": True,
                    "error": "Password is required for this account.",
                },
            )
        if acct_pw and password and not _pw_verify(password, acct_pw):
            suggested = determine_current_shift()
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "dispatcher_options": _dispatcher_options(),
                    "suggested_shift_letter": suggested,
                    "dispatcher_unit": dispatcher_unit,
                    "shift_letter": shift_letter or suggested,
                    "require_password": acct_req,
                    "error": "Invalid password.",
                },
            )
        # If they entered a password, set/update it; also persist require_password toggle
        _upsert_user_account(dispatcher_unit, display_name, False, require_password, password if password else None)

    if shift_letter not in ("A", "B", "C", "D"):
        shift_letter = determine_current_shift()

    shift_effective = _shift_effective_from_letter(shift_letter)

    # Set session (same keys your system already uses)
    request.session["user"] = dispatcher_unit
    request.session["dispatcher_unit"] = dispatcher_unit
    request.session["shift_letter"] = shift_letter
    request.session["shift_effective"] = shift_effective
    request.session["shift_start_ts"] = _ts()
    request.session["is_admin"] = bool(is_admin)

    # Legacy compatibility keys
    request.session["shift"] = shift_letter
    request.session["unit"] = dispatcher_unit

    try:
        log_master("SESSION_LOGIN", f"LOGIN: {dispatcher_unit} • shift {shift_letter} (effective {shift_effective})")
    except Exception:
        pass

    return RedirectResponse(url="/", status_code=302)

# ================================================================

# ================================================================
# INCIDENT TYPE CATALOG + NUMBERING POLICY (FORD-CAD CANON)
# ================================================================

INCIDENT_TYPE_CATALOG = [
    # FIRE / THERMAL
    {"key": "THERMAL EVENT",      "group": "FIRE", "requires_number": True},
    {"key": "VEGETATION FIRE",    "group": "FIRE", "requires_number": True},

    # EMS
    {"key": "PERSONAL MEDICAL",   "group": "EMS",  "requires_number": True},
    {"key": "INJURY",             "group": "EMS",  "requires_number": True},
    {"key": "FALL",               "group": "EMS",  "requires_number": True},

    # RESCUE / OPS
    {"key": "RESCUE",             "group": "RESCUE", "requires_number": True},
    {"key": "MVA",                "group": "OPS",    "requires_number": True},

    # NON-NUMBERED
    {"key": "TRANSPORT",          "group": "OPS",  "requires_number": False},  # non-emergency transport
    {"key": "TEST",               "group": "OPS",  "requires_number": False},
    {"key": "DAILY LOG",          "group": "OPS",  "requires_number": False},
]

INCIDENT_TYPE_KEYS = {t["key"] for t in INCIDENT_TYPE_CATALOG}
INCIDENT_TYPE_REQUIRES_NUMBER = {t["key"]: bool(t["requires_number"]) for t in INCIDENT_TYPE_CATALOG}

# Fuzzy aliases (dispatcher-friendly)
INCIDENT_TYPE_ALIASES = {
    "THERMAL": "THERMAL EVENT",
    "THERM": "THERMAL EVENT",
    "FIRE": "THERMAL EVENT",

    "VEG": "VEGETATION FIRE",
    "VEGETATION": "VEGETATION FIRE",
    "BRUSH": "VEGETATION FIRE",

    "MED": "PERSONAL MEDICAL",
    "MEDICAL": "PERSONAL MEDICAL",
    "EMS": "PERSONAL MEDICAL",

    "MVC": "MVA",

    "COURTESY": "TRANSPORT",
    "COURTESY RIDE": "TRANSPORT",
    "RIDE": "TRANSPORT",
}

def normalize_incident_type(raw: str) -> str:
    import re
    s = (raw or "").strip().upper()
    s = re.sub(r"\s+", " ", s)

    if not s:
        return ""

    if s in INCIDENT_TYPE_KEYS:
        return s

    if s in INCIDENT_TYPE_ALIASES:
        return INCIDENT_TYPE_ALIASES[s]

    squish = s.replace(" ", "")
    if squish in ("DAILYLOG", "DAILY"):
        return "DAILY LOG"

    return ""  # invalid

def incident_type_requires_number(type_key: str) -> bool:
    if not type_key:
        return True
    return bool(INCIDENT_TYPE_REQUIRES_NUMBER.get(type_key, True))

# ================================================================
# DATABASE CONNECTION
# ================================================================

def get_conn():
    """
    Canon DB connector.
    NOTE: sqlite3.connect() does NOT accept row_factory as a kwarg.
          You must set conn.row_factory AFTER connecting.
    """
    conn = sqlite3.connect(
        DB_PATH,                 # keep your existing DB_PATH variable
        timeout=30,
        check_same_thread=False
        # IMPORTANT: do NOT pass row_factory=... here (Python will throw TypeError)
    )

    # Row factory must be set on the connection object
    conn.row_factory = sqlite3.Row

    return conn


def _sqlite_exec_retry(cursor, sql: str, params=(), retries: int = 8, sleep_base: float = 0.05):
    """
    Retries SQLITE_BUSY / 'database is locked' transient write conflicts.
    Keep transactions short; this is a last-mile guard.
    """
    import time
    import sqlite3

    for attempt in range(retries):
        try:
            return cursor.execute(sql, params)
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if "database is locked" in msg or "database is busy" in msg:
                time.sleep(sleep_base * (attempt + 1))
                continue
            raise
    # Final attempt (raise real error if still locked)
    return cursor.execute(sql, params)


def assert_known_unit(unit_id: str):
    """Raise 400 if unit_id is not present in Units table."""
    ensure_phase3_schema()
    uid = str(unit_id or "").strip()
    if not uid:
        raise HTTPException(status_code=400, detail="Missing unit_id")
    conn = get_conn()
    c = conn.cursor()
    row = c.execute("SELECT 1 FROM Units WHERE unit_id = ? LIMIT 1", (uid,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=400, detail=f"Unknown unit_id: {uid}")
    return uid

def _ts() -> str:
    """Generate ISO 8601 timestamp string."""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _format_age(timestamp_str: str) -> str:
    """
    Convert a timestamp string to a human-readable age (e.g., '2m', '15m', '1h', '3h').
    Returns empty string if timestamp is invalid.
    """
    if not timestamp_str:
        return ""
    try:
        dt = datetime.datetime.strptime(str(timestamp_str).strip()[:19], "%Y-%m-%d %H:%M:%S")
        now = datetime.datetime.now()
        delta = now - dt
        total_seconds = int(delta.total_seconds())

        if total_seconds < 0:
            return "0m"
        if total_seconds < 60:
            return f"{total_seconds}s"
        if total_seconds < 3600:
            return f"{total_seconds // 60}m"
        if total_seconds < 86400:
            hours = total_seconds // 3600
            return f"{hours}h"
        days = total_seconds // 86400
        return f"{days}d"
    except Exception:
        return ""

# ================================================================
# DAILY LOG (JOURNAL) — Canon Schema + Subtypes (Ford CAD)
# ================================================================

DAILYLOG_SUBTYPES = [
    "BUILDING/RISER CHECKS",
    "TRAINING",
    "MAINTENANCE",
    "SAFETY WALK",
    "VEHICLE INSPECTION",
    "BUMP TEST",
    "STANDBY",
    "AED CHECK",
    "EXTINGUISHER CHECK",
    "OTHER",
]

_DAILYLOG_SUBTYPE_SET = set(DAILYLOG_SUBTYPES)


def normalize_dailylog_subtype(raw: str | None) -> str:
    s = (raw or "").strip().upper()

    # Allow a few forgiving aliases
    aliases = {
        "BUILDING RISER CHECKS": "BUILDING/RISER CHECKS",
        "BUILDING/RISER": "BUILDING/RISER CHECKS",
        "RISER CHECK": "BUILDING/RISER CHECKS",
        "RISER CHECKS": "BUILDING/RISER CHECKS",
        "EXT CHECK": "EXTINGUISHER CHECK",
        "EXTINGUISHERS": "EXTINGUISHER CHECK",
        "AED": "AED CHECK",
        "BUMP": "BUMP TEST",
        "VEHICLE": "VEHICLE INSPECTION",
    }

    if s in aliases:
        s = aliases[s]

    # Exact match required after normalization
    if s not in _DAILYLOG_SUBTYPE_SET:
        s = "OTHER"

    return s


def ensure_dailylog_schema():
    """
    Ensures the DailyLog table matches Ford CAD's canonical Daily Log Journal schema.
    If legacy DailyLog exists with different columns, it will be migrated.
    Canon columns:
      id INTEGER PK AUTOINCREMENT
      timestamp TEXT
      incident_id INTEGER NULL
      unit_id TEXT NULL
      action TEXT  (must be 'DAILYLOG')
      event_type TEXT (subtype)
      details TEXT
      user TEXT
    """
    conn = get_conn()
    c = conn.cursor()

    # Does DailyLog exist?
    t = c.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='DailyLog'
    """).fetchone()

    if not t:
        c.execute("""
            CREATE TABLE IF NOT EXISTS DailyLog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                incident_id INTEGER,
                unit_id TEXT,
                action TEXT,
                event_type TEXT,
                details TEXT,
                user TEXT
            )
        """)
        conn.commit()
        conn.close()
        return

    cols = [r[1] for r in c.execute("PRAGMA table_info('DailyLog')").fetchall()]
    colset = set(cols)

    # If it already has canonical 'id' + 'event_type', just add missing cols
    need_cols = {
        "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
        "timestamp": "TEXT",
        "incident_id": "INTEGER",
        "unit_id": "TEXT",
        "action": "TEXT",
        "event_type": "TEXT",
        "details": "TEXT",
        "user": "TEXT",
    }

    # If there is no primary key column we can rely on, migrate to a new table.
    if "id" not in colset:
        # Rename legacy
        c.execute("ALTER TABLE DailyLog RENAME TO DailyLog_legacy")

        # Create canonical
        c.execute("""
            CREATE TABLE IF NOT EXISTS DailyLog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                incident_id INTEGER,
                unit_id TEXT,
                action TEXT,
                event_type TEXT,
                details TEXT,
                user TEXT
            )
        """)

        legacy_cols = [r[1] for r in c.execute("PRAGMA table_info('DailyLog_legacy')").fetchall()]
        lset = set(legacy_cols)

        # Map legacy columns if they exist
        ts_col = "timestamp" if "timestamp" in lset else ("ts" if "ts" in lset else None)
        incident_col = "incident_id" if "incident_id" in lset else None
        unit_col = "unit_id" if "unit_id" in lset else None
        action_col = "action" if "action" in lset else None
        details_col = "details" if "details" in lset else ("text" if "text" in lset else None)
        user_col = "user" if "user" in lset else None
        et_col = "event_type" if "event_type" in lset else ("subtype" if "subtype" in lset else None)

        # Build INSERT…SELECT only with available columns
        sel_ts = ts_col if ts_col else "''"
        sel_inc = incident_col if incident_col else "NULL"
        sel_unit = unit_col if unit_col else "NULL"
        sel_action = action_col if action_col else "NULL"
        sel_et = et_col if et_col else "NULL"
        sel_details = details_col if details_col else "''"
        sel_user = user_col if user_col else "''"

        c.execute(f"""
            INSERT INTO DailyLog (timestamp, incident_id, unit_id, action, event_type, details, user)
            SELECT
                {sel_ts},
                {sel_inc},
                {sel_unit},
                {sel_action},
                {sel_et},
                {sel_details},
                {sel_user}
            FROM DailyLog_legacy
        """)

        conn.commit()
        conn.close()
        return

    # Otherwise, add any missing canonical columns (SQLite allows ADD COLUMN)
    for name, decl in need_cols.items():
        if name not in colset:
            # primary key can't be added via ALTER COLUMN, but we already have 'id' here.
            if name == "id":
                continue
            c.execute(f"ALTER TABLE DailyLog ADD COLUMN {name} {decl}")

    conn.commit()
    conn.close()

# ================================================================
# CORE HELPER FUNCTIONS
# ================================================================

# ================================================================
# DAILY LOG JOURNAL (Phase-3 Canon)
#   • DailyLog table stores ONLY journal entries (action='DAILYLOG')
#   • Subtype stored in event_type
#   • Non-journal system events must NOT write into DailyLog table,
#     but they may still write to MasterLog + IncidentHistory.
# ================================================================


def dailylog_event(
    action: str | None = None,
    event_type: str | None = None,
    details: str | None = None,
    user: str | None = None,
    incident_id: int | None = None,
    unit_id: str | None = None,
    timestamp: str | None = None,
):
    """
    DAILY LOG JOURNAL ONLY.
    Inserts ONLY when action == 'DAILYLOG'.
    Subtype is stored in event_type (Canon).
    """

    # Hard gate: this table is not the MasterLog.
    if (action or "").strip().upper() != "DAILYLOG":
        return False

    subtype = (event_type or "OTHER").strip().upper()
    text = (details or "").strip()
    if not text:
        return False

    ensure_phase3_schema()

    ts = (timestamp or _ts()).strip()

    conn = get_conn()
    c = conn.cursor()

    c.execute(
        """
        INSERT INTO DailyLog (timestamp, user, incident_id, unit_id, action, event_type, details)
        VALUES (?, ?, ?, ?, 'DAILYLOG', ?, ?)
        """,
        (ts, user, incident_id, unit_id, subtype, text),
    )

    conn.commit()
    conn.close()

    # Optional: also mirror to MasterLog for audit visibility
    try:
        masterlog(
            action="DAILYLOG",
            user=user,
            incident_id=incident_id,
            unit_id=unit_id,
            details=f"{subtype}: {text}",
            event_type=subtype,
        )
    except Exception:
        pass

    return True




def add_narrative(
    incident_id: int,
    user: str,
    text: str,
    entry_type: str = "REMARK",
    unit_id: str | None = None
):
    """Canonical narrative writer."""
    ensure_phase3_schema()
    
    conn = get_conn()
    c = conn.cursor()
    
    c.execute("""
        INSERT INTO Narrative (
            incident_id, timestamp, entry_type, text, user, unit_id
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (incident_id, _ts(), entry_type, text, user, unit_id))
    
    conn.commit()
    conn.close()

    # CAD_NARRATIVE_MASTERLOG: every narrative entry is also MasterLogged
    try:
        ev = f"NARRATIVE_{(entry_type or 'REMARK').upper().strip()}"
        masterlog(event_type=ev, user=user, incident_id=incident_id, unit_id=unit_id, details=text, ok=1, reason=None)
        incident_history(incident_id=incident_id, event_type=ev, user=user, unit_id=unit_id, details=text)
    except Exception:
        pass


def incident_has_data(incident_id: int) -> bool:
    """Returns True if incident has assigned units or narrative entries."""
    ensure_phase3_schema()
    
    conn = get_conn()
    c = conn.cursor()
    
    units = c.execute(
        "SELECT 1 FROM UnitAssignments WHERE incident_id = ? LIMIT 1",
        (incident_id,)
    ).fetchone()
    
    if units:
        conn.close()
        return True
    
    narrative = c.execute(
        "SELECT 1 FROM Narrative WHERE incident_id = ? LIMIT 1",
        (incident_id,)
    ).fetchone()
    
    conn.close()
    return bool(narrative)


def sync_units_table():
    """Sync Units table from UnitLog.txt.

    Supports BOTH formats:
      • Canonical pipe format: unit_id|name|unit_type|icon|is_command|is_apparatus|is_mutual_aid|status
      • Legacy dash format:    UnitID - Name - (optional Role) - icon.png

    Also normalizes legacy IDs to Phase-3 canonical IDs:
      • Battalion 1..4 → Batt1..Batt4
      • E1/E2/M1/M2/T1 → Engine1/Engine2/Medic1/Medic2/Tower1
    """

    if not UNITLOG_PATH.exists():
        return

    # Legacy shorthand → canonical IDs
    _APP_MAP = {
        "E1": "Engine1",
        "E2": "Engine2",
        "M1": "Medic1",
        "M2": "Medic2",
        "T1": "Tower1",
    }
    _IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".svg")

    conn = get_conn()
    c = conn.cursor()

    for raw in UNITLOG_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = (raw or "").strip()
        if not line or line.startswith("#"):
            continue

        up = line.upper()
        # Skip section headers / labels in the legacy file
        if up.startswith(("A-SHIFT", "B-SHIFT", "C-SHIFT", "D-SHIFT", "APPARATUS", "EXTERIOR", "INTERIOR")):
            continue

        unit_id = ""
        name = ""
        unit_type = ""
        status = ""
        icon = ""
        is_command = 0
        is_apparatus = 0
        is_mutual_aid = 0

        # -------------------------
        # Canonical pipe format
        # -------------------------
        if "|" in line:
            parts = [p.strip() for p in line.split("|")]

            if len(parts) < 4:
                continue

            unit_id = parts[0]
            name = parts[1] if len(parts) > 1 else unit_id
            unit_type = parts[2] if len(parts) > 2 else ""
            icon = parts[3] if len(parts) > 3 else ""

            if len(parts) > 4 and parts[4].isdigit():
                is_command = int(parts[4])
            if len(parts) > 5 and parts[5].isdigit():
                is_apparatus = int(parts[5])
            if len(parts) > 6 and parts[6].isdigit():
                is_mutual_aid = int(parts[6])

            status = parts[7] if len(parts) > 7 else ""

        # -------------------------
        # Legacy dash format
        # -------------------------
        else:
            parts = [p.strip() for p in line.split(" - ")]

            if len(parts) < 2:
                continue

            unit_id = parts[0].strip()

            # Battalion 1 → Batt1 (etc.)
            if unit_id.lower().startswith("battalion"):
                digits = "".join(ch for ch in unit_id if ch.isdigit())
                if digits:
                    unit_id = f"Batt{digits}"

            # Apparatus shorthand → canonical IDs
            unit_id = _APP_MAP.get(unit_id, unit_id)

            name = parts[1].strip() if len(parts) > 1 else unit_id

            # Icon is usually last token in legacy format
            if parts and parts[-1].lower().endswith(_IMG_EXTS):
                icon = parts[-1].strip()

            # Infer unit type / flags (canonical)
            if unit_id.isdigit() and len(unit_id) == 2:
                unit_type = "PERSONNEL"
            elif unit_id in COMMAND_IDS:
                unit_type = "COMMAND"
                is_command = 1
            elif unit_id in APPARATUS_ORDER:
                unit_type = "APPARATUS"
                is_apparatus = 1
            else:
                unit_type = "UNIT"

            # Defaults if legacy line didn't provide an icon
            if not icon:
                if is_command:
                    icon = "command.png"
                elif unit_type == "PERSONNEL":
                    icon = "firefighter.png"
                else:
                    icon = "logo.png"

        unit_id = (unit_id or "").strip()
        if not unit_id:
            continue

        # Always ensure we have a sane display name
        name = (name or unit_id).strip()

        # Status: never overwrite DB status unless the UnitLog line explicitly includes one
        # Icon: preserve existing icon if set (don't overwrite with defaults)
        row = c.execute("SELECT status, icon FROM Units WHERE unit_id = ?", (unit_id,)).fetchone()
        if row:
            existing_status = row["status"] if row else "AVAILABLE"
            existing_icon = row["icon"] if row else None
            final_status = status or existing_status or "AVAILABLE"
            # Only use default icon if no existing icon in database
            final_icon = existing_icon if existing_icon else icon

            c.execute(
                """
                UPDATE Units
                SET name = ?, unit_type = ?, status = ?, icon = ?,
                    is_apparatus = ?, is_command = ?, is_mutual_aid = ?, last_updated = ?
                WHERE unit_id = ?
                """,
                (name, unit_type, final_status, final_icon, is_apparatus, is_command, is_mutual_aid, _ts(), unit_id)
            )
        else:
            final_status = status or "AVAILABLE"

            c.execute(
                """
                INSERT INTO Units (unit_id, name, unit_type, status, last_updated, icon,
                                   is_apparatus, is_command, is_mutual_aid)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (unit_id, name, unit_type, final_status, _ts(), icon, is_apparatus, is_command, is_mutual_aid)
            )

    conn.commit()
    conn.close()

    # Phase-3: also sync UnitRoster from UnitLog shift sections
    try:
        sync_unit_roster_from_unitlog()
    except Exception as e:
        print(f"[SYNC] sync_unit_roster_from_unitlog failed: {e}")

def _normalize_roster_unit_id(tokens: list[str]) -> str | None:
    """
    Normalize a UnitLog roster line into a FORD-CAD unit_id.
    Supports:
      - "11 - Name" (two-digit personnel)
      - "Battalion 1 - Name" -> "Batt1"
    """
    if not tokens:
        return None

    t0 = (tokens[0] or "").strip()
    if not t0:
        return None

    # Two-digit personnel
    if t0.isdigit() and len(t0) == 2:
        return t0

    # Battalion X
    if t0.lower().startswith("battalion") and len(tokens) >= 2:
        n = (tokens[1] or "").strip()
        if n.isdigit():
            return f"Batt{int(n)}"

    return None


def sync_unit_roster_from_unitlog(unitlog_path: str = UNITLOG_PATH) -> None:
    """
    Phase-3: Populate UnitRoster from UnitLog.txt shift sections (A/B/C/D).

    Robust parsing:
      • Accepts headers like "A Shift", "A-Shift", "A SHIFT ROSTER", etc.
      • Accepts roster lines like:
          "17 - T. Williams"
          "17 T. Williams"
          "Batt1 - Name" / "Car1 - Name" / "1578 - Name"
      • Stores BOTH:
          shift_letter (current roster assignment)
          home_shift_letter (initial default; only set if null)
    """
    ensure_phase3_schema()

    if not os.path.exists(unitlog_path):
        print(f"[ROSTER] UnitLog not found: {unitlog_path}")
        return

    try:
        with open(unitlog_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = [ln.rstrip("\n") for ln in f.readlines()]
    except Exception as e:
        print(f"[ROSTER] Unable to read UnitLog: {e}")
        return

    current_shift: str | None = None
    roster: dict[str, str] = {}  # unit_id -> shift_letter

    # Accept headers: "A Shift", "A-Shift", "A SHIFT", "A SHIFT ROSTER", etc.
    _hdr_re = re.compile(r"^\s*([ABCD])\s*[- ]?\s*SHIFT\b", re.IGNORECASE)

    for raw in (lines or []):
        line = (raw or "").strip()
        if not line:
            continue

        m = _hdr_re.match(line)
        if m:
            current_shift = m.group(1).upper()
            continue

        if not current_shift:
            continue

        # Normalize delimiter variants (hyphen, en dash, em dash, colon)
        # Split once: left side contains unit token(s)
        left = re.split(r"\s*[-–—:]\s*", line, maxsplit=1)[0].strip()
        if not left:
            continue

        tokens = [t for t in left.split() if t.strip()]
        uid = _normalize_roster_unit_id(tokens)
        if not uid:
            continue

        roster[uid] = current_shift

    if not roster:
        print("[ROSTER] No shift roster lines found in UnitLog.")
        return

    ts = _ts()
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("BEGIN IMMEDIATE")

        for uid, sh in roster.items():
            c.execute(
                """
                INSERT INTO UnitRoster (unit_id, shift_letter, home_shift_letter, updated)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(unit_id) DO UPDATE SET
                    shift_letter = excluded.shift_letter,
                    home_shift_letter = COALESCE(UnitRoster.home_shift_letter, excluded.home_shift_letter),
                    updated = excluded.updated
                """,
                (uid, sh, sh, ts),
            )

        conn.commit()
        print(f"[ROSTER] UnitRoster synced ({len(roster)} entries).")
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"[ROSTER] UnitRoster sync failed: {e}")
    finally:
        conn.close()



def _shift_effective_from_letter(shift_letter: str) -> str:
    """
    Effective shift key (A/B) used by Phase-3 session + crew persistence.
    
    4-shift rotation:
      A-Shift and C-Shift work days (0600-1800) → effective "A"
      B-Shift and D-Shift work nights (1800-0600) → effective "B"
    """
    s = (shift_letter or "").strip().upper()
    if s in ("A", "C"):
        return "A"
    if s in ("B", "D"):
        return "B"
    return "A"  # Default fallback


def get_session_shift_letter(request: Request) -> str:
    # Backward-compatible legacy key: session["shift"]
    return (request.session.get("shift_letter") or request.session.get("shift") or "").strip().upper()


def get_session_shift_effective(request: Request) -> str:
    eff = (request.session.get("shift_effective") or "").strip().upper()
    if eff in ("A", "B"):
        return eff
    sh = get_session_shift_letter(request)
    return _shift_effective_from_letter(sh) if sh else ""


def session_is_initialized(request: Request) -> bool:
    return bool(get_session_shift_letter(request))


def roster_personnel_ids_for_shift(shift_letter: str) -> set[str]:
    """
    Base roster personnel IDs for a shift letter (A/B/C/D) from UnitRoster.
    """
    sh = (shift_letter or "").strip().upper()
    if not sh:
        return set()

    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()
    try:
        rows = c.execute(
            """
            SELECT unit_id
            FROM UnitRoster
            WHERE shift_letter = ?
              AND unit_id GLOB '[0-9][0-9]'
            """,
            (sh,),
        ).fetchall()
        return {str(r["unit_id"]).strip() for r in (rows or []) if (r["unit_id"] or "").strip()}
    finally:
        conn.close()


def apply_active_shift_overrides(shift_letter: str, base_ids: set[str]) -> set[str]:
    """
    Apply temporary shift overrides:
      - Add units moved INTO this shift
      - Remove units moved OUT of this shift
    """
    sh = (shift_letter or "").strip().upper()
    if not sh:
        return set(base_ids or set())

    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()
    try:
        rows = c.execute(
            """
            SELECT unit_id, from_shift_letter, to_shift_letter
            FROM ShiftOverrides
            WHERE end_ts IS NULL
            """
        ).fetchall()

        add_in: set[str] = set()
        take_out: set[str] = set()

        for r in (rows or []):
            uid = (r["unit_id"] or "").strip()
            frm = (r["from_shift_letter"] or "").strip().upper()
            to = (r["to_shift_letter"] or "").strip().upper()
            if not uid or not frm or not to:
                continue

            if to == sh:
                add_in.add(uid)
            if frm == sh:
                take_out.add(uid)

        out = set(base_ids or set())
        out |= add_in
        out -= take_out
        return out
    finally:
        conn.close()


def get_active_personnel_ids_for_request(request: Request) -> set[str]:
    """
    Resolve personnel roster set for the current session shift letter,
    then apply active overrides.
    """
    sh = get_session_shift_letter(request)
    base = roster_personnel_ids_for_shift(sh)
    return apply_active_shift_overrides(sh, base)

def get_session_roster_view_mode(request: Request) -> str:
    return (request.session.get("roster_view_mode") or "CURRENT").strip().upper()


def roster_personnel_ids_all_shifts() -> set[str]:
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()
    try:
        rows = c.execute(
            """
            SELECT unit_id
            FROM UnitRoster
            WHERE unit_id GLOB '[0-9][0-9]'
            """
        ).fetchall()
        return {str(r["unit_id"]).strip() for r in (rows or []) if (r["unit_id"] or "").strip()}
    finally:
        conn.close()


# Battalion chiefs are SHIFT-SCOPED (letter-based). 1578 and Car1 are always visible.
# 4-shift rotation: A/C work days (0600-1800), B/D work nights (1800-0600)
# Each shift has its own Battalion Chief:
#   A-Shift → Batt1, B-Shift → Batt2, C-Shift → Batt3, D-Shift → Batt4
BATTALION_BY_SHIFT = {
    "A": ["Batt1"],
    "B": ["Batt2"],
    "C": ["Batt3"],
    "D": ["Batt4"],
}

def visible_command_unit_ids(shift_letter: str, shift_effective: str) -> set[str]:
    """
    Command visibility rules:
      • Always: 1578, Car1
      • Battalion chiefs: shift-scoped (prefer shift_letter A/B/C/D, fallback to shift_effective)
    """
    always = {"1578", "Car1"}

    sl = (shift_letter or "").strip().upper()
    se = (shift_effective or "").strip().upper()

    allowed_batts: list[str] = []
    if isinstance(BATTALION_BY_SHIFT, dict):
        allowed_batts = BATTALION_BY_SHIFT.get(sl) or BATTALION_BY_SHIFT.get(se) or []

    return always | set(allowed_batts)




def reject_and_log(
    event_type: str,
    reason: str,
    user: str = "System",
    incident_id: int | None = None,
    unit_id: str | None = None
):
    """Logs a rejected action with reason."""
    masterlog(
        event_type=event_type, user=user,
        incident_id=incident_id, details=f"REJECTED: {reason}"
    )
    dailylog_event(
        action=event_type, details=f"Rejected: {reason}",
        user=user, incident_id=incident_id, unit_id=unit_id
    )


def set_unit_disposition(incident_id: int, unit_id: str, disposition: str):
    """Sets disposition code for a unit assignment."""
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()
    
    c.execute("""
        UPDATE UnitAssignments
        SET disposition = ?
        WHERE incident_id = ? AND unit_id = ?
    """, (disposition, incident_id, unit_id))
    
    conn.commit()
    conn.close()


def incident_has_active_units(incident_id: int) -> bool:
    """Returns True if incident has units that have not been cleared."""
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()
    
    row = c.execute("""
        SELECT 1 FROM UnitAssignments
        WHERE incident_id = ? AND cleared IS NULL
        LIMIT 1
    """, (incident_id,)).fetchone()
    
    conn.close()
    return bool(row)


def close_incident_with_disposition(incident_id: int, code: str, user: str = "System"):
    """Closes an incident with the provided disposition code."""
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        UPDATE Incidents
        SET status='CLOSED', final_disposition=?, updated=?
        WHERE incident_id=?
    """, (code, _ts(), incident_id))

    conn.commit()
    conn.close()


def masterlog(event_type, user="System", incident_id=None, details=None, unit_id=None, action=None):
    """
    Canonical MasterLog writer.
    Always satisfies legacy NOT NULL action column.
    """
    ensure_phase3_schema()

    conn = get_conn()
    c = conn.cursor()

    # PRAGMA table_info returns tuples: (cid, name, type, notnull, dflt, pk)
    cols = [row[1] for row in c.execute("PRAGMA table_info(MasterLog)").fetchall()]

    ts = _ts()
    action_value = event_type or "SYSTEM"

    if "action" in cols:
        # Always write action if it exists
        c.execute("""
            INSERT INTO MasterLog (
                timestamp,
                user,
                action,
                incident_id,
                details
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            ts,
            user,
            action_value,
            incident_id,
            details
        ))

        # Mirror to event_type if present
        if "event_type" in cols:
            c.execute("""
                UPDATE MasterLog
                SET event_type = ?
                WHERE rowid = last_insert_rowid()
            """, (action_value,))
    else:
        # Pure new schema
        c.execute("""
            INSERT INTO MasterLog (
                timestamp,
                user,
                event_type,
                incident_id,
                details
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            ts,
            user,
            action_value,
            incident_id,
            details
        ))

    conn.commit()
    conn.close()


def log_master(unit_id=None, incident_id=None, action="SYSTEM", details=None, user: str = "System"):
    """Legacy-compatible alias for the canonical masterlog() writer."""
    return masterlog(event_type=action, user=user, incident_id=incident_id, details=details, unit_id=unit_id, action=action)


# ======================================================
# PHASE-3 SCHEMA INITIALIZATION (GUARDED)
# ======================================================

_SCHEMA_INIT_DONE = False


def ensure_phase3_schema():
    global _SCHEMA_INIT_DONE
    # Return early if already initialized to prevent concurrent schema operations
    # which can cause database locks on multi-threaded access
    if _SCHEMA_INIT_DONE:
        return

    conn = get_conn()
    c = conn.cursor()

    # ------------------------------------------------------------
    # SAFE COLUMN ADDS (NON-DESTRUCTIVE)
    # ------------------------------------------------------------
    def _add_col(sql: str):
        try:
            c.execute(sql)
        except Exception:
            pass

    # --------------------------------------------------
    # INCIDENT COUNTER
    # --------------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS IncidentCounter (
            year INTEGER PRIMARY KEY,
            next_seq INTEGER NOT NULL
        )
    """)

    # ------------------------------------------------------------
    # INCIDENTS (CORE TABLE)
    # ------------------------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS Incidents (
            incident_id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_number TEXT UNIQUE,
            run_number INTEGER,
            status TEXT DEFAULT 'OPEN',
            is_draft INTEGER DEFAULT 0,

            type TEXT,
            location TEXT,
            node TEXT,
            pole TEXT,

            priority INTEGER,
            caller_name TEXT,
            caller_phone TEXT,

            narrative TEXT,
            issue_found INTEGER DEFAULT 0,

            created TEXT,
            updated TEXT,
            closed_at TEXT,
            cancel_reason TEXT,

            final_disposition TEXT,
            issue_flag INTEGER DEFAULT 0,
            address TEXT
        )
    """)

    # Retrofit older DBs safely
    _add_col("ALTER TABLE Incidents ADD COLUMN incident_number TEXT")
    _add_col("ALTER TABLE Incidents ADD COLUMN run_number INTEGER")
    _add_col("ALTER TABLE Incidents ADD COLUMN status TEXT DEFAULT 'OPEN'")
    _add_col("ALTER TABLE Incidents ADD COLUMN is_draft INTEGER DEFAULT 0")

    _add_col("ALTER TABLE Incidents ADD COLUMN type TEXT")
    _add_col("ALTER TABLE Incidents ADD COLUMN location TEXT")
    _add_col("ALTER TABLE Incidents ADD COLUMN node TEXT")
    _add_col("ALTER TABLE Incidents ADD COLUMN pole TEXT")

    _add_col("ALTER TABLE Incidents ADD COLUMN priority INTEGER")
    _add_col("ALTER TABLE Incidents ADD COLUMN caller_name TEXT")
    _add_col("ALTER TABLE Incidents ADD COLUMN caller_phone TEXT")

    _add_col("ALTER TABLE Incidents ADD COLUMN narrative TEXT")
    _add_col("ALTER TABLE Incidents ADD COLUMN issue_found INTEGER DEFAULT 0")

    _add_col("ALTER TABLE Incidents ADD COLUMN created TEXT")
    _add_col("ALTER TABLE Incidents ADD COLUMN updated TEXT")
    _add_col("ALTER TABLE Incidents ADD COLUMN closed_at TEXT")
    _add_col("ALTER TABLE Incidents ADD COLUMN cancel_reason TEXT")

    _add_col("ALTER TABLE Incidents ADD COLUMN final_disposition TEXT")
    _add_col("ALTER TABLE Incidents ADD COLUMN held_reason TEXT")
    _add_col("ALTER TABLE Incidents ADD COLUMN held_at TEXT")
    _add_col("ALTER TABLE Incidents ADD COLUMN held_by TEXT")
    _add_col("ALTER TABLE Incidents ADD COLUMN held_released_at TEXT")
    _add_col("ALTER TABLE Incidents ADD COLUMN held_released_by TEXT")
    _add_col("ALTER TABLE Incidents ADD COLUMN issue_flag INTEGER DEFAULT 0")
    _add_col("ALTER TABLE Incidents ADD COLUMN address TEXT")

    # --------------------------------------------------
    # MASTER LOG
    # --------------------------------------------------
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
            details TEXT,
            event_type TEXT
        )
    """)

    ml_cols = [r[1] for r in c.execute("PRAGMA table_info(MasterLog)").fetchall()]
    if "event_type" not in ml_cols:
        _add_col("ALTER TABLE MasterLog ADD COLUMN event_type TEXT")
    if "unit_id" not in ml_cols:
        _add_col("ALTER TABLE MasterLog ADD COLUMN unit_id TEXT")

    # --------------------------------------------------
    # INCIDENT HISTORY
    # --------------------------------------------------
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

    # --------------------------------------------------
    # DAILY LOG (JOURNAL)
    # Canon requires subtype support via event_type
    # --------------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS DailyLog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            user TEXT,
            incident_id INTEGER,
            unit_id TEXT,
            action TEXT NOT NULL,
            event_type TEXT,
            details TEXT,
            issue_found INTEGER DEFAULT 0
        )
    """)

    dl_cols = [r[1] for r in c.execute("PRAGMA table_info(DailyLog)").fetchall()]
    if "user" not in dl_cols:
        _add_col("ALTER TABLE DailyLog ADD COLUMN user TEXT")
    if "incident_id" not in dl_cols:
        _add_col("ALTER TABLE DailyLog ADD COLUMN incident_id INTEGER")
    if "unit_id" not in dl_cols:
        _add_col("ALTER TABLE DailyLog ADD COLUMN unit_id TEXT")
    if "action" not in dl_cols:
        _add_col("ALTER TABLE DailyLog ADD COLUMN action TEXT")
    if "event_type" not in dl_cols:
        _add_col("ALTER TABLE DailyLog ADD COLUMN event_type TEXT")
    if "details" not in dl_cols:
        _add_col("ALTER TABLE DailyLog ADD COLUMN details TEXT")
    if "issue_found" not in dl_cols:
        _add_col("ALTER TABLE DailyLog ADD COLUMN issue_found INTEGER DEFAULT 0")




    # --------------------------------------------------
    # NARRATIVE
    # --------------------------------------------------
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

    # --------------------------------------------------
    # UNITS
    # --------------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS Units (
            unit_id TEXT PRIMARY KEY,
            name TEXT,
            unit_type TEXT,
            status TEXT,
            icon TEXT,
            is_apparatus INTEGER DEFAULT 0,
            is_command INTEGER DEFAULT 0,
            is_mutual_aid INTEGER DEFAULT 0,
            last_updated TEXT,
            custom_status TEXT
        )
    """)

    _add_col("ALTER TABLE Units ADD COLUMN name TEXT")
    _add_col("ALTER TABLE Units ADD COLUMN unit_type TEXT")
    _add_col("ALTER TABLE Units ADD COLUMN status TEXT")
    _add_col("ALTER TABLE Units ADD COLUMN icon TEXT")
    _add_col("ALTER TABLE Units ADD COLUMN is_apparatus INTEGER DEFAULT 0")
    _add_col("ALTER TABLE Units ADD COLUMN is_command INTEGER DEFAULT 0")
    _add_col("ALTER TABLE Units ADD COLUMN is_mutual_aid INTEGER DEFAULT 0")
    _add_col("ALTER TABLE Units ADD COLUMN last_updated TEXT")
    _add_col("ALTER TABLE Units ADD COLUMN custom_status TEXT")
    _add_col("ALTER TABLE Units ADD COLUMN aliases TEXT")  # CSV list of aliases, e.g. "e1,eng1,engine1"

    # --------------------------------------------------
    # UNIT ASSIGNMENTS
    # --------------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS UnitAssignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id INTEGER,
            unit_id TEXT,
            assigned TEXT,
            dispatched TEXT,
            enroute TEXT,
            arrived TEXT,
            transporting TEXT,
            at_medical TEXT,
            cleared TEXT,
            disposition TEXT,
            disposition_remark TEXT,
            commanding_unit INTEGER DEFAULT 0
        )
    """)

    _add_col("ALTER TABLE UnitAssignments ADD COLUMN incident_id INTEGER")
    _add_col("ALTER TABLE UnitAssignments ADD COLUMN unit_id TEXT")
    _add_col("ALTER TABLE UnitAssignments ADD COLUMN assigned TEXT")
    _add_col("ALTER TABLE UnitAssignments ADD COLUMN dispatched TEXT")
    _add_col("ALTER TABLE UnitAssignments ADD COLUMN enroute TEXT")
    _add_col("ALTER TABLE UnitAssignments ADD COLUMN arrived TEXT")
    _add_col("ALTER TABLE UnitAssignments ADD COLUMN transporting TEXT")
    _add_col("ALTER TABLE UnitAssignments ADD COLUMN at_medical TEXT")
    _add_col("ALTER TABLE UnitAssignments ADD COLUMN cleared TEXT")
    _add_col("ALTER TABLE UnitAssignments ADD COLUMN disposition TEXT")
    _add_col("ALTER TABLE UnitAssignments ADD COLUMN disposition_remark TEXT")
    _add_col("ALTER TABLE UnitAssignments ADD COLUMN commanding_unit INTEGER DEFAULT 0")

    # --------------------------------------------------
    # PERSONNEL ASSIGNMENTS (Crew Mirroring)
    # Canon table used by get_apparatus_crew()
    # --------------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS PersonnelAssignments (
            apparatus_id TEXT NOT NULL,
            personnel_id TEXT NOT NULL,
            role TEXT,
            shift TEXT,
            updated TEXT,
            PRIMARY KEY (apparatus_id, personnel_id)
        )
    """)

    # -----------------------------
    # UnitRoster (Phase-3 Login / Shift roster source-of-truth)
    # -----------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS UnitRoster (
            unit_id TEXT PRIMARY KEY,
            shift_letter TEXT NOT NULL,          -- A/B/C/D (roster)
            home_shift_letter TEXT NOT NULL,     -- A/B/C/D (default)
            updated TEXT
        )
    """)

    # -----------------------------
    # UserAccounts (Phase-3+ Login Auth)
    # Optional passwords for non-admin; required for admins.
    # -----------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS UserAccounts (
            unit_id TEXT PRIMARY KEY,
            display_name TEXT,
            password_hash TEXT,            -- nullable for non-admin
            require_password INTEGER DEFAULT 0,
            is_admin INTEGER DEFAULT 0,
            created TEXT,
            updated TEXT
        )
    """)


    # -----------------------------
    # ShiftOverrides (temporary shift moves; do not rewrite UnitRoster)
    # -----------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS ShiftOverrides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            unit_id TEXT NOT NULL,
            from_shift_letter TEXT NOT NULL,
            to_shift_letter TEXT NOT NULL,
            reason TEXT NOT NULL,
            start_ts TEXT NOT NULL,
            end_ts TEXT,
            created_by TEXT
        )
    """)


    # Backfill optional columns for older cad.db files
    def _add_col_safe(sql: str):
        try:
            c.execute(sql)
        except Exception:
            pass

    _add_col_safe("ALTER TABLE PersonnelAssignments ADD COLUMN role TEXT")
    _add_col_safe("ALTER TABLE PersonnelAssignments ADD COLUMN shift TEXT")
    _add_col_safe("ALTER TABLE PersonnelAssignments ADD COLUMN updated TEXT")

    # --------------------------------------------------
    # HELD SEEN
    # --------------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS HeldSeen (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            seen_at TEXT NOT NULL
        )
    """)

    # --------------------------------------------------
    # PERFORMANCE INDEXES (Commercial CAD Standard)
    # --------------------------------------------------
    def _create_index(sql: str):
        try:
            c.execute(sql)
        except Exception:
            pass  # Index already exists

    # UnitAssignments - critical for incident lookups and unit queries
    _create_index("CREATE INDEX IF NOT EXISTS idx_unit_assignments_incident ON UnitAssignments(incident_id)")
    _create_index("CREATE INDEX IF NOT EXISTS idx_unit_assignments_unit ON UnitAssignments(unit_id)")
    _create_index("CREATE INDEX IF NOT EXISTS idx_unit_assignments_cleared ON UnitAssignments(cleared)")

    # Incidents - status filtering is the most common query
    _create_index("CREATE INDEX IF NOT EXISTS idx_incidents_status ON Incidents(status)")
    _create_index("CREATE INDEX IF NOT EXISTS idx_incidents_created ON Incidents(created)")
    _create_index("CREATE INDEX IF NOT EXISTS idx_incidents_is_draft ON Incidents(is_draft)")

    # MasterLog - timestamp queries for audit reports
    _create_index("CREATE INDEX IF NOT EXISTS idx_masterlog_timestamp ON MasterLog(timestamp)")
    _create_index("CREATE INDEX IF NOT EXISTS idx_masterlog_incident ON MasterLog(incident_id)")

    # DailyLog - timestamp queries for daily journal
    _create_index("CREATE INDEX IF NOT EXISTS idx_dailylog_timestamp ON DailyLog(timestamp)")

    # IncidentHistory - incident timeline queries
    _create_index("CREATE INDEX IF NOT EXISTS idx_incident_history_incident ON IncidentHistory(incident_id)")
    _create_index("CREATE INDEX IF NOT EXISTS idx_incident_history_timestamp ON IncidentHistory(timestamp)")

    # Narrative - incident narrative lookups
    _create_index("CREATE INDEX IF NOT EXISTS idx_narrative_incident ON Narrative(incident_id)")

    # PersonnelAssignments - crew lookups
    _create_index("CREATE INDEX IF NOT EXISTS idx_personnel_apparatus ON PersonnelAssignments(apparatus_id)")

    # UnitRoster - shift filtering
    _create_index("CREATE INDEX IF NOT EXISTS idx_unit_roster_shift ON UnitRoster(shift_letter)")

    # ShiftOverrides - active override lookups
    _create_index("CREATE INDEX IF NOT EXISTS idx_shift_overrides_unit ON ShiftOverrides(unit_id)")
    _create_index("CREATE INDEX IF NOT EXISTS idx_shift_overrides_to_shift ON ShiftOverrides(to_shift_letter)")

    # --------------------------------------------------
    # CONTACTS (for messaging responders)
    # --------------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS Contacts (
            contact_id INTEGER PRIMARY KEY AUTOINCREMENT,
            unit_id TEXT,
            name TEXT,
            email TEXT,
            phone TEXT,
            carrier TEXT,
            signal_number TEXT,
            role TEXT,
            is_active INTEGER DEFAULT 1,
            receive_reports INTEGER DEFAULT 0,
            created TEXT,
            updated TEXT
        )
    """)
    _create_index("CREATE INDEX IF NOT EXISTS idx_contacts_unit ON Contacts(unit_id)")

    conn.commit()
    conn.close()
    _SCHEMA_INIT_DONE = True




# ================================================================
# INCIDENT CREATION (DRAFT ONLY — NO INCIDENT NUMBER)
# ================================================================

@app.post("/incident/new")
async def create_incident(request: Request):
    ensure_phase3_schema()

    ts = _ts()

    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        INSERT INTO Incidents (
            is_draft,
            status,
            created,
            updated
        )
        VALUES (
            1,
            'OPEN',
            ?,
            ?
        )
    """, (ts, ts))

    incident_id = c.lastrowid

    conn.commit()
    conn.close()

    masterlog(
        "INCIDENT_DRAFT_CREATED",
        incident_id=incident_id,
        details="Draft incident created"
    )

    dailylog_event(
        action="INCIDENT_DRAFT_CREATED",
        incident_id=incident_id,
        details="Draft incident created"
    )

    return {
        "ok": True,
        "incident_id": incident_id
    }

# ================================================================
# INCIDENT CANCEL (DRAFT ONLY)
# ================================================================

@app.post("/incident/cancel/{incident_id}")
async def cancel_incident(request: Request, incident_id: int):
    ensure_phase3_schema()

    conn = get_conn()
    c = conn.cursor()

    row = c.execute("""
        SELECT is_draft
        FROM Incidents
        WHERE incident_id=?
    """, (incident_id,)).fetchone()

    if not row:
        conn.close()
        return {"ok": False, "error": "Incident not found"}

    if row["is_draft"] != 1:
        conn.close()
        return {"ok": False, "error": "Only draft incidents can be canceled"}

    c.execute("""
        DELETE FROM Incidents
        WHERE incident_id=?
    """, (incident_id,))

    conn.commit()
    conn.close()

    masterlog(
        "INCIDENT_DRAFT_CANCELED",
        incident_id=incident_id,
        details="Draft incident canceled"
    )

    dailylog_event(
        action="INCIDENT_DRAFT_CANCELED",
        incident_id=incident_id,
        details="Draft incident canceled"
    )

    return {"ok": True}

# ================================================================
# INCIDENT NUMBER ASSIGN ON SAVE
# ================================================================
@app.post("/incident/save/{incident_id}")
async def save_incident(request: Request, incident_id: int):
    ensure_phase3_schema()
    data = await request.json()
    ts = _ts()
    user = (data.get("user") or "CLI").strip()  # safe default

    # Accept both legacy + new Calltaker payload shapes
    caller_name = (data.get("caller_name") or "").strip()
    if not caller_name:
        first = (data.get("caller_first") or "").strip()
        last = (data.get("caller_last") or "").strip()
        caller_name = (" ".join([x for x in [first, last] if x]) or "").strip()

    caller_phone = (
        (data.get("caller_phone") or "").strip()
        or (data.get("callerPhone") or "").strip()
    )

    pole = (data.get("pole") or "").strip()
    if not pole:
        pa = (data.get("pole_alpha") or "").strip()
        pad = (data.get("pole_alpha_dec") or "").strip()
        pn = (data.get("pole_number") or data.get("pole_num") or "").strip()
        pnd = (data.get("pole_number_dec") or data.get("pole_num_dec") or "").strip()
        parts = [((pa + pad).strip()), ((pn + pnd).strip())]
        pole = "-".join([p for p in parts if p]) if any(parts) else ""

    # Optional: store caller location into Incidents.address if provided
    address = (data.get("address") or data.get("caller_location") or "").strip()

    # Enforce the type catalog
    raw_type = (data.get("type") or "").strip()
    type_key = normalize_incident_type(raw_type)
    if not type_key:
        allowed = ", ".join(sorted(INCIDENT_TYPE_KEYS))
        raise HTTPException(status_code=400, detail=f"Invalid incident type. Allowed: {allowed}")

    # Daily Log subtype support (only meaningful when type_key == "DAILY LOG")
    dailylog_subtype = (data.get("dailylog_subtype") or data.get("subtype") or "").strip()

    # If this is a DAILY LOG incident, narrative is required (it becomes the journal details)
    if type_key == "DAILY LOG":
        if not (data.get("narrative") or "").strip():
            raise HTTPException(status_code=400, detail="Daily Log requires Narrative (used as the journal entry).")

    conn = get_conn()
    c = conn.cursor()

    incident_number = None
    seq = None

    try:
        c.execute("BEGIN IMMEDIATE")

        inc = c.execute(
            """
            SELECT incident_number, is_draft, status
            FROM Incidents
            WHERE incident_id=?
            """,
            (incident_id,),
        ).fetchone()

        if not inc:
            raise HTTPException(status_code=404, detail="Incident not found")

        # A saved incident is defined by is_draft=0 (not by having an incident_number),
        # because some types are intentionally non-numbered (TEST / DAILY LOG / TRANSPORT).
        if int(inc["is_draft"] or 0) == 0:
            raise HTTPException(status_code=400, detail="Incident already saved")

        # Numbering policy
        if incident_type_requires_number(type_key):
            incident_number, year, seq = allocate_incident_number(conn)
        else:
            incident_number, seq = None, None

        c.execute(
            """
            UPDATE Incidents
            SET
                incident_number=?,
                run_number=?,
                is_draft=0,
                status='OPEN',
                type=?,
                priority=?,
                location=?,
                node=?,
                pole=?,
                caller_name=?,
                caller_phone=?,
                narrative=?,
                address=?,
                updated=?
            WHERE incident_id=?
            """,
            (
                incident_number,
                seq,
                type_key,
                data.get("priority"),
                data.get("location"),
                data.get("node"),
                pole,
                caller_name,
                caller_phone,
                data.get("narrative"),
                address,
                ts,
                incident_id,
            ),
        )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    # --- Logs (outside transaction) ----------------------------------------

    masterlog(
        "INCIDENT_OPENED",
        incident_id=incident_id,
        details=f"Issued {incident_number}" if incident_number else "Opened (no number)",
        user=user,
    )

    # DailyLog table must contain ONLY Daily Log Journal entries.
    # So: DO NOT write INCIDENT_OPENED, DISPATCH, STATUS_CHANGE, etc. into DailyLog.
    # Only mirror when the incident itself is a DAILY LOG event.
    if type_key == "DAILY LOG":
        try:
            dailylog_event(
                action="DAILYLOG",
                event_type=dailylog_subtype or "OTHER",
                details=(data.get("narrative") or "").strip(),
                incident_id=incident_id,
                unit_id=None,
                user=user,
            )
        except Exception:
            pass

    return {
        "ok": True,
        "incident_id": incident_id,
        "incident_number": incident_number,
    }



# ------------------------------------------------
# INCIDENT ACTION WINDOW (IAW — HARD GUARANTEE)
# ------------------------------------------------
@app.get("/incident_action_window/{incident_id}", response_class=HTMLResponse)
def ford_incident_action_window(request: Request, incident_id: int):
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()

    incident = c.execute("""
        SELECT *
        FROM Incidents
        WHERE incident_id = ?
    """, (incident_id,)).fetchone()

    if not incident:
        conn.close()
        raise HTTPException(status_code=404, detail="Incident not found")

    units = c.execute("""
        SELECT *
        FROM UnitAssignments
        WHERE incident_id = ?
    """, (incident_id,)).fetchall()

    narrative = c.execute("""
        SELECT *
        FROM Narrative
        WHERE incident_id = ?
        ORDER BY timestamp ASC
    """, (incident_id,)).fetchall()

    conn.close()

    return templates.TemplateResponse(
        "iaw/incident_action_window.html",
        {
            "request": request,
            "incident": dict(incident),
            "units": [dict(u) for u in units],
            "narrative": [dict(n) for n in narrative]
        }
    )


# ------------------------------------------------
# INCIDENT TIMELINE (WAVE 4B)
# ------------------------------------------------
@app.get("/incident/{incident_id}/timeline", response_class=HTMLResponse)
def ford_incident_timeline_view(request: Request, incident_id: int):
    ensure_phase3_schema()

    timeline = get_incident_timeline(incident_id)

    return templates.TemplateResponse(
        "incident_timeline.html",
        {
            "request": request,
            "timeline": timeline,
            "incident_id": incident_id
        }
    )


@app.get("/iaw/{incident_id}/timeline", response_class=HTMLResponse)
def ford_iaw_timeline_partial(request: Request, incident_id: int):
    ensure_phase3_schema()
    timeline = get_incident_timeline(incident_id)

    return templates.TemplateResponse(
        "partials/iaw_timeline.html",
        {
            "request": request,
            "timeline": timeline
        }
    )

# ======================================================================
# BLOCK U2 — UNIT EDITOR WRITER (Writes unit roster back to UnitLog.txt)
# Runtime-only (NO import-time execution)
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
            str(int(u.get("is_mutual_aid", 0))),
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
    ensure_phase3_schema()

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
    ensure_phase3_schema()

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
# UNIT EDIT ACTIONS (RUNTIME ONLY)
# ======================================================================

@app.post("/units/editor/update")
async def units_editor_update(request: Request):
    data = await request.json()

    unit_id = data.get("unit_id", "").strip()
    if not unit_id:
        return {"ok": False, "error": "Missing unit_id"}

    if unit_is_assigned(unit_id):
        return {"ok": False, "error": "Unit is active on an incident — cannot modify"}

    ensure_phase3_schema()

    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        UPDATE Units
        SET name=?,
            unit_type=?,
            icon=?,
            is_command=?,
            is_apparatus=?,
            is_mutual_aid=?,
            aliases=?
        WHERE unit_id=?
    """, (
        data.get("name", unit_id),
        data.get("unit_type", "PERSONNEL").upper(),
        data.get("icon", "unknown.png"),
        int(data.get("is_command", 0)),
        int(data.get("is_apparatus", 0)),
        int(data.get("is_mutual_aid", 0)),
        data.get("aliases", ""),  # CSV of aliases, e.g. "e1,eng1,engine1"
        unit_id
    ))

    conn.commit()
    conn.close()

    units = fetch_units_metadata_only()
    write_unitlog_file(units)
    sync_units_table()

    return {"ok": True}


@app.post("/units/editor/add")
async def units_editor_add(request: Request):
    data = await request.json()

    unit_id = data.get("unit_id", "").strip()
    if not unit_id:
        return {"ok": False, "error": "Missing unit_id"}

    ensure_phase3_schema()

    conn = get_conn()
    c = conn.cursor()

    exists = c.execute(
        "SELECT 1 FROM Units WHERE unit_id=?",
        (unit_id,)
    ).fetchone()

    if exists:
        conn.close()
        return {"ok": False, "error": "Unit already exists"}

    c.execute("""
        INSERT INTO Units (
            unit_id, name, unit_type, status, last_updated,
            icon, is_command, is_apparatus, is_mutual_aid, aliases
        )
        VALUES (?, ?, ?, 'AVAILABLE', ?, ?, ?, ?, ?, ?)
    """, (
        unit_id,
        data.get("name", unit_id),
        data.get("unit_type", "PERSONNEL").upper(),
        _ts(),
        data.get("icon", "unknown.png"),
        int(data.get("is_command", 0)),
        int(data.get("is_apparatus", 0)),
        int(data.get("is_mutual_aid", 0)),
        data.get("aliases", "")  # CSV of aliases, e.g. "e1,eng1,engine1"
    ))

    conn.commit()
    conn.close()

    units = fetch_units_metadata_only()
    write_unitlog_file(units)
    sync_units_table()

    return {"ok": True}


@app.post("/units/editor/delete")
async def units_editor_delete(request: Request):
    data = await request.json()
    unit_id = data.get("unit_id", "").strip()

    if not unit_id:
        return {"ok": False, "error": "Missing unit_id"}

    if unit_is_assigned(unit_id):
        return {"ok": False, "error": "Cannot delete — unit is active on an incident"}

    ensure_phase3_schema()

    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        UPDATE Units
        SET status='INACTIVE', last_updated=?
        WHERE unit_id=?
    """, (_ts(), unit_id))

    conn.commit()
    conn.close()

    units = [u for u in fetch_units_metadata_only() if u["unit_id"] != unit_id]
    write_unitlog_file(units)
    sync_units_table()

    return {"ok": True}
# ======================================================================
# BLOCK U3 — REAL-TIME UNIT REFRESH ENGINE (PHASE-3)
# ======================================================================

@app.get("/api/units/refresh", response_class=HTMLResponse)
async def api_units_refresh(request: Request):
    """Returns a fully-rendered Units Panel HTML block (shift-scoped)."""
    ctx = _build_units_panel_context(request)
    return templates.TemplateResponse(
        "units.html",
        {
            "request": request,
            "units": ctx["units"],
            "crew_map": ctx["crew_map"],
            "login_required": ctx["login_required"],
            "shift_letter": ctx["shift_letter"],
            "shift_effective": ctx["shift_effective"],
        },
    )




@app.get("/api/dispatch_picker/refresh/{incident_id}", response_class=HTMLResponse)
async def api_dispatch_picker_refresh(request: Request, incident_id: int):
    """
    Rebuilds Dispatch Picker lists in canonical CAD order.
    Phase-3: Shift-scoped eligible units (roster + overrides + availability).
    """
    if not session_is_initialized(request):
        return templates.TemplateResponse(
            "modals/dispatch_picker.html",
            {
                "request": request,
                "incident_id": incident_id,
                "command_units": [],
                "personnel_units": [],
                "apparatus_units": [],
                "mutual_aid_units": [],
                "login_required": True,
            },
        )

    shift_letter = get_session_shift_letter(request)

    # Start with the canonical ordered set
    units = fetch_units() or []

    # Availability: block duplicates (units already assigned to any active incident)
    conn = get_conn()
    c = conn.cursor()
    try:
        assigned_to_incident = {
            (r["unit_id"] or "").strip()
            for r in c.execute(
                """
                SELECT unit_id
                FROM UnitAssignments
                WHERE cleared IS NULL
                """
            ).fetchall()
        }
    finally:
        conn.close()

    # Roster personnel (shift letter) + overrides
    view_mode = get_session_roster_view_mode(request)
    if view_mode == "ALL":
        roster_personnel = roster_personnel_ids_all_shifts()
    else:
        roster_personnel = get_active_personnel_ids_for_request(request)

    allowed_commands = visible_command_unit_ids(get_session_shift_letter(request), get_session_shift_effective(request))


    eligible: list[dict] = []
    for u in units:
        uid = (u.get("unit_id") or "").strip()
        if not uid:
            continue

        is_command = int(u.get("is_command") or 0) == 1
        is_apparatus = int(u.get("is_apparatus") or 0) == 1
        is_mutual_aid = int(u.get("is_mutual_aid") or 0) == 1
        is_personnel = uid.isdigit() and len(uid) == 2

        # Command visibility: 1578/Car1 always; Battalion chiefs shift-scoped
        if is_command and uid not in allowed_commands:
            continue

        # Shift roster: personnel must be on-duty roster in CURRENT mode; ALL mode includes all
        if is_personnel and uid not in roster_personnel:
            continue


        # Eligible means not already assigned
        if uid in assigned_to_incident:
            continue

        # Command/Apparatus/Mutual Aid always eligible to display; personnel filtered above
        if is_command or is_apparatus or is_mutual_aid or is_personnel:
            eligible.append(u)

    groups = split_units_for_picker(eligible)

    return templates.TemplateResponse(
        "modals/dispatch_picker.html",
        {
            "request": request,
            "incident_id": incident_id,
            "command_units": groups["command"],
            "personnel_units": groups["personnel"],
            "apparatus_units": groups["apparatus"],
            "mutual_aid_units": groups["mutual_aid"],
            "login_required": False,
            "shift_letter": shift_letter,
        },
    )


@app.get("/api/unit/{unit_id}/metadata_refresh", response_class=HTMLResponse)
async def api_unit_metadata_refresh(request: Request, unit_id: str):
    """
    Reloads unit metadata inside an open UAW.
    """
    unit, active_incident_id = _load_unit_for_uaw(unit_id)
    if not unit:
        return HTMLResponse("Unit not found", status_code=404)

    return templates.TemplateResponse(
        "units/unit_action_window.html",
        {
            "request": request,
            "unit": unit,
            "active_incident_id": active_incident_id
        }
    )


@app.get("/unit/{unit_id}/uaw", response_class=HTMLResponse)
async def unit_action_window(request: Request, unit_id: str):
    """
    Opens the Unit Action Window modal.
    """
    unit, active_incident_id = _load_unit_for_uaw(unit_id)
    if not unit:
        return HTMLResponse("Unit not found", status_code=404)

    return templates.TemplateResponse(
        "units/unit_action_window.html",
        {
            "request": request,
            "unit": unit,
            "active_incident_id": active_incident_id
        }
    )

@app.get("/unit/{unit_id}/uaw_full", response_class=HTMLResponse)
async def unit_action_window_full(request: Request, unit_id: str):
    """
    Opens the Full Unit Details modal (larger view).
    """
    unit, active_incident_id = _load_unit_for_uaw(unit_id)
    if not unit:
        return HTMLResponse("Unit not found", status_code=404)

    return templates.TemplateResponse(
        "units/unit_action_window_full.html",
        {
            "request": request,
            "unit": unit,
            "active_incident_id": active_incident_id
        }
    )

def _incident_needs_disposition(incident_id: int) -> bool:
    """
    True only when:
      - no active (uncleared) units remain
      - AND incident final_disposition is blank
    """
    conn = get_conn()
    c = conn.cursor()

    active = c.execute("""
        SELECT 1
        FROM UnitAssignments
        WHERE incident_id = ?
          AND cleared IS NULL
        LIMIT 1
    """, (incident_id,)).fetchone()

    dispo = c.execute("""
        SELECT COALESCE(final_disposition,'') AS final_disposition
        FROM Incidents
        WHERE incident_id = ?
    """, (incident_id,)).fetchone()

    conn.close()

    if active:
        return False

    return not (dispo and (dispo["final_disposition"] or "").strip())


def _unit_has_disposition(incident_id: int, unit_id: str) -> bool:
    conn = get_conn()
    c = conn.cursor()
    row = c.execute("""
        SELECT COALESCE(disposition,'') AS disposition
        FROM UnitAssignments
        WHERE incident_id = ?
          AND unit_id = ?
        LIMIT 1
    """, (incident_id, unit_id)).fetchone()
    conn.close()
    return bool(row and (row["disposition"] or "").strip())


# NOTE: Duplicate /api/uaw/clear_all endpoint was removed - using the one with command unit enforcement


# ================================================================
# SHIFT / ROTATION LOGIC (PRESENTATION ONLY)
# ================================================================

def determine_current_shift() -> str:
    """
    Ford KTP 4-shift rotation:
      - A/C work days (0600-1800), B/D work nights (1800-0600)
      - Shifts rotate every other day:
        Even days: A (day), B (night)
        Odd days: C (day), D (night)

    This uses day-of-year to determine which pair is on duty.
    """
    now_dt = datetime.datetime.now()
    hour = now_dt.hour
    day_of_year = now_dt.timetuple().tm_yday

    # Determine if it's day shift (6am-6pm) or night shift (6pm-6am)
    is_day_shift = 6 <= hour < 18

    # Even days: A/B rotation, Odd days: C/D rotation
    # Note: night shift belongs to the day it started (e.g., night of Jan 1 = Jan 1's rotation)
    if hour < 6:
        # After midnight but before 6am - belongs to previous day's night shift
        day_of_year -= 1

    is_even_day = (day_of_year % 2) == 0

    if is_even_day:
        return "A" if is_day_shift else "B"
    else:
        return "C" if is_day_shift else "D"


# ================================================================
# UNIT ORDER & SHIFT VISIBILITY HELPERS (FORD-CAD CANON)
# ================================================================

# Canonical command units (fixed order, always pinned in lists/pickers)
COMMAND_IDS = ["1578", "Car1", "Batt1", "Batt2", "Batt3", "Batt4"]
# Back-compat alias (older code / templates may still reference COMMAND_UNITS)
COMMAND_UNITS = COMMAND_IDS

# ================================================================
# PHASE-3 LOGIN (SESSION INITIALIZER) + SHIFT OVERRIDES
# ================================================================

def _is_admin_unit(unit_id: str) -> bool:
    """
    Admins = command staff + Troy (17).
    Command staff includes 1578, Car1, Batt1–Batt4 by canon.
    """
    uid = (unit_id or "").strip()
    return uid in {"1578", "Car1", "Batt1", "Batt2", "Batt3", "Batt4", "17"}


def _pw_hash(password: str) -> str:
    """
    PBKDF2-HMAC-SHA256, stored as: pbkdf2$iters$salt_b64$hash_b64
    """
    pw = (password or "").encode("utf-8")
    salt = os.urandom(16)
    iters = 200_000
    dk = hashlib.pbkdf2_hmac("sha256", pw, salt, iters)
    return "pbkdf2$%d$%s$%s" % (
        iters,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(dk).decode("ascii"),
    )


def _pw_verify(password: str, stored: str) -> bool:
    try:
        algo, iters_s, salt_b64, hash_b64 = (stored or "").split("$", 3)
        if algo != "pbkdf2":
            return False
        iters = int(iters_s)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(hash_b64.encode("ascii"))
        dk = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"), salt, iters)
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def _get_user_account(unit_id: str) -> dict | None:
    ensure_phase3_schema()
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT unit_id, display_name, password_hash, require_password, is_admin FROM UserAccounts WHERE unit_id = ?",
            (unit_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _upsert_user_account(unit_id: str, display_name: str, is_admin: bool, require_password: bool, password: str | None) -> dict:
    """
    Upsert user account. If password provided, set/replace password_hash.
    """
    ensure_phase3_schema()
    ts = _ts()
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("BEGIN IMMEDIATE")

        existing = c.execute(
            "SELECT unit_id, password_hash FROM UserAccounts WHERE unit_id = ?",
            (unit_id,),
        ).fetchone()

        pw_hash = None
        if password is not None and (password or "").strip() != "":
            pw_hash = _pw_hash(password)

        if existing:
            if pw_hash:
                c.execute(
                    """
                    UPDATE UserAccounts
                    SET display_name = ?, password_hash = ?, require_password = ?, is_admin = ?, updated = ?
                    WHERE unit_id = ?
                    """,
                    (display_name, pw_hash, 1 if require_password else 0, 1 if is_admin else 0, ts, unit_id),
                )
            else:
                c.execute(
                    """
                    UPDATE UserAccounts
                    SET display_name = ?, require_password = ?, is_admin = ?, updated = ?
                    WHERE unit_id = ?
                    """,
                    (display_name, 1 if require_password else 0, 1 if is_admin else 0, ts, unit_id),
                )
        else:
            c.execute(
                """
                INSERT INTO UserAccounts (unit_id, display_name, password_hash, require_password, is_admin, created, updated)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (unit_id, display_name, pw_hash, 1 if require_password else 0, 1 if is_admin else 0, ts, ts),
            )

        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()

    return _get_user_account(unit_id) or {}

def _dispatcher_options() -> list[dict]:
    """
    Login selector options.
    Phase-3 intent: resolve dispatcher identity from roster/units.
    """
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()
    try:
        rows = c.execute(
            """
            SELECT unit_id, name
            FROM Units
            WHERE (unit_type = 'PERSONNEL' AND unit_id GLOB '[0-9][0-9]')
               OR is_command = 1
            ORDER BY unit_id
            """
        ).fetchall()

        out = []
        for r in (rows or []):
            uid = (r["unit_id"] or "").strip()
            nm = (r["name"] or "").strip()
            if not uid:
                continue
            label = f"{uid} - {nm}" if nm else uid
            out.append({"unit_id": uid, "label": label})
        return out
    finally:
        conn.close()


@app.get("/api/session/status")
async def api_session_status(request: Request):
    sh = get_session_shift_letter(request)
    return {
        "logged_in": bool(sh),
        "user": (request.session.get("user") or "").strip(),
        "dispatcher_unit": (request.session.get("dispatcher_unit") or request.session.get("unit") or "").strip(),
        "shift_letter": sh,
        "shift_effective": get_session_shift_effective(request),
        "shift_start_ts": (request.session.get("shift_start_ts") or "").strip(),
        "roster_view_mode": (request.session.get("roster_view_mode") or "CURRENT").strip().upper(),
    }



@app.post("/api/session/login")
async def api_session_login(request: Request, payload: dict):
    """
    Phase-3 Login:
      - identify dispatcher/operator (label)
      - set shift context (A/B/C/D + effective A/B)
      - unlock shift-scoped unit views
    """
    dispatcher_unit = (payload.get("dispatcher_unit") or "").strip()
    user = (payload.get("user") or "").strip() or dispatcher_unit or "Dispatcher"

    shift_letter = (payload.get("shift_letter") or "").strip().upper()
    if shift_letter not in ("A", "B", "C", "D"):
        shift_letter = determine_current_shift()

    shift_effective = (payload.get("shift_effective") or "").strip().upper()
    if shift_effective not in ("A", "B"):
        shift_effective = _shift_effective_from_letter(shift_letter)

    request.session["user"] = user
    request.session["dispatcher_unit"] = dispatcher_unit or user
    request.session["shift_letter"] = shift_letter
    request.session["shift_effective"] = shift_effective
    request.session["shift_start_ts"] = _ts()

    # Legacy compatibility keys (older templates/blocks)
    request.session["shift"] = shift_letter
    request.session["unit"] = dispatcher_unit or user

    try:
        log_master("SESSION_LOGIN", f"LOGIN: {user} • shift {shift_letter} (effective {shift_effective})")
    except Exception:
        pass

    return {"ok": True, "shift_letter": shift_letter, "shift_effective": shift_effective, "user": user}


@app.post("/api/session/logout")
async def api_session_logout(request: Request):
    user = (request.session.get("user") or "").strip() or "Dispatcher"
    shift_letter = (request.session.get("shift_letter") or request.session.get("shift") or "").strip()

    try:
        log_master("SESSION_LOGOUT", f"LOGOUT: {user} • shift {shift_letter}")
    except Exception:
        pass

    # Clear the entire session
    request.session.clear()

    return {"ok": True}


@app.get("/logout")
async def logout_and_redirect(request: Request):
    """GET endpoint for logout - clears session and redirects to login page."""
    user = (request.session.get("user") or "").strip() or "Dispatcher"
    shift_letter = (request.session.get("shift_letter") or request.session.get("shift") or "").strip()

    try:
        log_master("SESSION_LOGOUT", f"LOGOUT: {user} • shift {shift_letter}")
    except Exception:
        pass

    # Clear the entire session
    request.session.clear()

    # Redirect to login page
    return RedirectResponse(url="/login", status_code=302)

@app.post("/api/session/view_mode")
async def api_session_view_mode(request: Request, payload: dict):
    if not session_is_initialized(request):
        return reject_and_log("LOGIN_REQUIRED", "View mode requires login/shift context.")

    mode = (payload.get("roster_view_mode") or "CURRENT").strip().upper()
    if mode not in ("CURRENT", "ALL"):
        return reject_and_log("BAD_REQUEST", "roster_view_mode must be CURRENT or ALL.")

    request.session["roster_view_mode"] = mode
    try:
        log_master("SESSION_VIEW_MODE", f"VIEW MODE: {mode}")
    except Exception:
        pass

    return {"ok": True, "roster_view_mode": mode}


@app.post("/api/session/roster_view_mode")
async def api_session_roster_view_mode(request: Request, payload: dict):
    """
    Simple endpoint for CLI/context menu to toggle roster view mode.
    Accepts: { "mode": "ALL" } or { "mode": "CURRENT" }
    """
    if not session_is_initialized(request):
        return reject_and_log("LOGIN_REQUIRED", "View mode requires login/shift context.")

    mode = (payload.get("mode") or "CURRENT").strip().upper()
    if mode not in ("CURRENT", "ALL"):
        return reject_and_log("BAD_REQUEST", "mode must be CURRENT or ALL.")

    request.session["roster_view_mode"] = mode
    try:
        log_master("SESSION_VIEW_MODE", f"VIEW MODE: {mode}")
    except Exception:
        pass

    return {"ok": True, "mode": mode}


# ================================================================
# USER SETTINGS (Persisted per dispatcher unit)
# ================================================================

@app.get("/api/settings")
async def api_get_settings(request: Request):
    """
    Get user settings. Returns settings from database or defaults.
    """
    dispatcher_unit = (request.session.get("dispatcher_unit") or request.session.get("unit") or "").strip()
    if not dispatcher_unit:
        # Return defaults if not logged in (fromUser: false so client keeps localStorage)
        return {
            "ok": True,
            "fromUser": False,
            "settings": {
                "theme": "light",
                "fontSize": "medium",
                "soundEnabled": True,
                "autoRefresh": True,
                "autoRefreshInterval": 30,
                "panelCalltakerWidth": "38%",
                "panelUnitsWidth": "22%",
            }
        }

    conn = get_conn()
    c = conn.cursor()

    # Ensure UserSettings table exists
    c.execute("""
        CREATE TABLE IF NOT EXISTS UserSettings (
            dispatcher_unit TEXT PRIMARY KEY,
            settings_json TEXT,
            updated TEXT
        )
    """)
    conn.commit()

    row = c.execute("SELECT settings_json FROM UserSettings WHERE dispatcher_unit=?", (dispatcher_unit,)).fetchone()
    conn.close()

    if row and row["settings_json"]:
        import json
        try:
            settings = json.loads(row["settings_json"])
            return {"ok": True, "fromUser": True, "settings": settings}
        except Exception:
            pass

    # Return defaults (fromUser: false so client knows these are defaults)
    return {
        "ok": True,
        "fromUser": False,
        "settings": {
            "theme": "light",
            "fontSize": "medium",
            "soundEnabled": True,
            "autoRefresh": True,
            "autoRefreshInterval": 30,
            "panelCalltakerWidth": "38%",
            "panelUnitsWidth": "22%",
        }
    }


@app.post("/api/settings")
async def api_save_settings(request: Request):
    """
    Save user settings. Stores settings JSON in database.
    """
    dispatcher_unit = (request.session.get("dispatcher_unit") or request.session.get("unit") or "").strip()
    if not dispatcher_unit:
        return {"ok": False, "error": "Login required to save settings"}

    import json
    try:
        payload = await request.json()
    except Exception:
        return {"ok": False, "error": "Invalid JSON body"}
    settings_json = json.dumps(payload.get("settings", {}))

    conn = get_conn()
    c = conn.cursor()

    # Ensure UserSettings table exists
    c.execute("""
        CREATE TABLE IF NOT EXISTS UserSettings (
            dispatcher_unit TEXT PRIMARY KEY,
            settings_json TEXT,
            updated TEXT
        )
    """)

    c.execute("""
        INSERT OR REPLACE INTO UserSettings (dispatcher_unit, settings_json, updated)
        VALUES (?, ?, ?)
    """, (dispatcher_unit, settings_json, _ts()))

    conn.commit()
    conn.close()

    return {"ok": True}


@app.get("/modals/login", response_class=HTMLResponse)
async def modal_login(request: Request):
    """
    Login / Select Shift modal (Phase-3).
    """
    suggested = determine_current_shift()
    current_letter = get_session_shift_letter(request) or suggested
    current_effective = get_session_shift_effective(request) or _shift_effective_from_letter(current_letter)

    return templates.TemplateResponse(
        "modals/login_modal.html",
        {
            "request": request,
            "dispatcher_options": _dispatcher_options(),
            "suggested_shift_letter": suggested,
            "current_shift_letter": current_letter,
            "current_shift_effective": current_effective,
            "current_user": (request.session.get("user") or "").strip(),
            "current_dispatcher_unit": (request.session.get("dispatcher_unit") or request.session.get("unit") or "").strip(),
        },
    )


@app.post("/api/shift_override/start")
async def api_shift_override_start(request: Request, payload: dict):
    """
    Temporary movement of a unit across shifts (Phase-3 requirement).
    Does NOT rewrite UnitRoster; writes ShiftOverrides instead.
    """
    if not session_is_initialized(request):
        return reject_and_log("LOGIN_REQUIRED", "Shift override requires login/shift context.")

    unit_id = (payload.get("unit_id") or "").strip()
    to_shift_letter = (payload.get("to_shift_letter") or "").strip().upper()
    reason = (payload.get("reason") or "Shift coverage").strip()

    if not unit_id:
        return reject_and_log("BAD_REQUEST", "unit_id is required.")

    # Default to current session's shift if not specified
    if not to_shift_letter:
        to_shift_letter = get_session_shift_letter(request) or ""

    if to_shift_letter not in ("A", "B", "C", "D"):
        return reject_and_log("BAD_REQUEST", "to_shift_letter must be A/B/C/D (or login to set session shift).")

    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()
    try:
        existing = c.execute(
            """
            SELECT id
            FROM ShiftOverrides
            WHERE unit_id = ?
              AND end_ts IS NULL
            """,
            (unit_id,),
        ).fetchone()
        if existing:
            return reject_and_log("OVERRIDE_EXISTS", f"{unit_id} already has an active shift override.")

        home = c.execute(
            "SELECT home_shift_letter FROM UnitRoster WHERE unit_id = ?",
            (unit_id,),
        ).fetchone()
        from_shift_letter = (home["home_shift_letter"] if home else "") or get_session_shift_letter(request)

        c.execute(
            """
            INSERT INTO ShiftOverrides (unit_id, from_shift_letter, to_shift_letter, reason, start_ts, end_ts, created_by)
            VALUES (?, ?, ?, ?, ?, NULL, ?)
            """,
            (unit_id, from_shift_letter, to_shift_letter, reason, _ts(), (request.session.get("user") or "").strip()),
        )
        conn.commit()
    finally:
        conn.close()

    try:
        log_master("SHIFT_OVERRIDE_START", f"SHIFT OVERRIDE: {unit_id} {from_shift_letter} -> {to_shift_letter} • {reason}")
    except Exception:
        pass

    return {"ok": True}


@app.post("/api/shift_override/end")
async def api_shift_override_end(request: Request, payload: dict):
    """
    End a temporary shift override (Return to Home Shift).
    """
    if not session_is_initialized(request):
        return reject_and_log("LOGIN_REQUIRED", "Shift override requires login/shift context.")

    unit_id = (payload.get("unit_id") or "").strip()
    if not unit_id:
        return reject_and_log("BAD_REQUEST", "unit_id is required.")

    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute(
            """
            UPDATE ShiftOverrides
               SET end_ts = ?
             WHERE unit_id = ?
               AND end_ts IS NULL
            """,
            (_ts(), unit_id),
        )
        conn.commit()
        updated = c.rowcount
    finally:
        conn.close()

    if updated:
        try:
            log_master("SHIFT_OVERRIDE_END", f"SHIFT OVERRIDE END: {unit_id}")
        except Exception:
            pass

    return {"ok": True, "ended": bool(updated)}


# Battalion chiefs are SHIFT-SCOPED (visibility + defaults).
# 1578 and Car1 are always visible on every shift (handled elsewhere).
# NOTE: BATTALION_BY_SHIFT is defined earlier in the file (line ~1225)
# This duplicate has been removed to prevent overwrite issues


# Canonical apparatus order (fixed)
# Spec: Engine2, Medic2, Engine1, Medic1, Tower1, UTV1, UTV2, SQ1
APPARATUS_ORDER = [
    "Engine2",
    "Medic2",
    "Engine1",
    "Medic1",
    "Tower1",
    "UTV1",
    "UTV2",
    "SQ1",
]


def fetch_units() -> list[dict]:
    """
    Fetch all units from SQLite (no filtering).
    Ordering is handled by get_units_for_panel() / split_units_for_picker().
    """
    conn = get_conn()
    c = conn.cursor()
    rows = c.execute("""
        SELECT unit_id, name, unit_type, status, last_updated,
               icon,
               COALESCE(is_apparatus,0) AS is_apparatus,
               COALESCE(is_command,0) AS is_command,
               COALESCE(is_mutual_aid,0) AS is_mutual_aid,
               COALESCE(custom_status,'') AS custom_status
        FROM Units
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def split_units_for_picker(units: list[dict]) -> dict:
    """
    Dispatch picker ordering (FORD-CAD CANON):

      - Command units pinned and always shown (1578, Car1, Batt1–Batt4)
      - Personnel (two-digit IDs / PERSONNEL type)
      - Apparatus (APPARATUS_ORDER)
      - Mutual aid last

    Shift note:
      - Battalion rotates with shift, but all Batt1–Batt4 still appear.
      - The "active batt" may be used by the UI to preselect/highlight, but is not hidden.
    """
    current_shift = determine_current_shift()
    active_batt = BATTALION_BY_SHIFT.get(current_shift)

    command = []
    personnel = []
    apparatus = []
    mutual_aid = []

    apparatus_index = {uid: i for i, uid in enumerate(APPARATUS_ORDER)}
    command_index = {uid: i for i, uid in enumerate(COMMAND_IDS)}

    def is_personnel_id(uid: str) -> bool:
        return uid.isdigit() and len(uid) == 2

    for u in units or []:
        uid = (u.get("unit_id") or "").strip()
        utype = (u.get("unit_type") or "").upper().strip()

        is_cmd = int(u.get("is_command") or 0)
        is_app = int(u.get("is_apparatus") or 0)
        is_ma  = int(u.get("is_mutual_aid") or 0)

        if is_ma:
            mutual_aid.append(u)
            continue

        # Canonical pinned command
        if uid in command_index or is_cmd:
            command.append(u)
            continue

        # Personnel
        if utype == "PERSONNEL" or is_personnel_id(uid):
            personnel.append(u)
            continue

        # Apparatus
        if is_app or uid in apparatus_index:
            apparatus.append(u)
            continue

        # Fallback: treat unknowns as apparatus-like for pickers
        apparatus.append(u)

    # Sort command strictly by canonical order
    command_sorted = sorted(
        command,
        key=lambda x: command_index.get((x.get("unit_id") or "").strip(), 999)
    )

    # Optional: bubble the active batt to the top among battalions (without hiding others)
    # This keeps the pinned order but nudges the active batt right after Car1.
    if active_batt and active_batt in COMMAND_IDS:
        def _cmd_bubble_key(x: dict) -> tuple:
            uid = (x.get("unit_id") or "").strip()
            # 0:1578, 1:Car1, 2:active batt, then remaining in canonical order
            if uid == "1578":
                return (0, 0)
            if uid == "Car1":
                return (1, 0)
            if uid == active_batt:
                return (2, 0)
            return (3, command_index.get(uid, 999))
        command_sorted = sorted(command_sorted, key=_cmd_bubble_key)

    def _personnel_key(x: dict) -> int:
        uid = (x.get("unit_id") or "").strip()
        if uid.isdigit() and len(uid) == 2:
            return int(uid)
        return 9999

    personnel_sorted = sorted(personnel, key=_personnel_key)

    apparatus_sorted = sorted(
        apparatus,
        key=lambda x: apparatus_index.get((x.get("unit_id") or "").strip(), 999)
    )

    mutual_aid_sorted = sorted(mutual_aid, key=lambda x: (x.get("unit_id") or ""))

    return {
        "command": command_sorted,
        "personnel": personnel_sorted,
        "apparatus": apparatus_sorted,
        "mutual_aid": mutual_aid_sorted,
        "active_batt": active_batt,
        "shift": current_shift
    }


def get_units_for_panel() -> list[dict]:
    """
    FORD-CAD Units Panel order (CANON):
      1) Command units pinned (fixed order): 1578, Car1, Batt1–Batt4
      2) Personnel (two-digit IDs) ascending
      3) Apparatus in fixed order (APPARATUS_ORDER)
      4) Mutual aid last
      5) Any other units (fallback) last

    Notes:
      - This function ONLY orders units; filtering for "available" happens in /panel/units.
      - Always attaches metadata so templates can rely on keys.
    """
    units = fetch_units() or []

    # Always attach metadata so templates can rely on keys (icon, status, etc.)
    for u in units:
        attach_unit_metadata(u)

    cmd: list[dict] = []
    personnel: list[dict] = []
    apparatus: list[dict] = []
    mutual: list[dict] = []
    other: list[dict] = []

    apparatus_index = {uid: i for i, uid in enumerate(APPARATUS_ORDER)}
    command_index = {uid: i for i, uid in enumerate(COMMAND_IDS)}

    def is_personnel_id(uid: str) -> bool:
        return uid.isdigit() and len(uid) == 2

    for u in units:
        uid = (u.get("unit_id") or "").strip()

        if uid in command_index:
            cmd.append(u)
        elif int(u.get("is_mutual_aid", 0) or 0) == 1:
            mutual.append(u)
        elif is_personnel_id(uid) or (u.get("unit_type") or "").upper().strip() == "PERSONNEL":
            personnel.append(u)
        elif uid in apparatus_index or int(u.get("is_apparatus", 0) or 0) == 1:
            apparatus.append(u)
        else:
            other.append(u)

    cmd.sort(key=lambda x: command_index.get((x.get("unit_id") or "").strip(), 999))

    def _personnel_sort_key(x: dict) -> int:
        uid = (x.get("unit_id") or "").strip()
        if uid.isdigit() and len(uid) == 2:
            return int(uid)
        return 999

    personnel.sort(key=_personnel_sort_key)
    apparatus.sort(key=lambda x: apparatus_index.get((x.get("unit_id") or "").strip(), 999))
    mutual.sort(key=lambda x: (x.get("unit_id") or ""))
    other.sort(key=lambda x: (x.get("unit_id") or ""))

    ordered: list[dict] = []
    ordered.extend(cmd)
    ordered.extend(personnel)
    ordered.extend(apparatus)
    ordered.extend(mutual)
    ordered.extend(other)

    return ordered



# ======================================================================
# BLOCK 1A — CORE MODELS + UNIT ASSIGNMENT ENGINE (PHASE-3 CANON)
# ======================================================================

def attach_unit_metadata(unit: dict):
    """
    Attaches safe presentation defaults.

    IMPORTANT:
      - This function expects a Units row (unit_id/name/status/icon/...).
      - Do NOT pass a UnitAssignments row to this function.
    """
    unit_id = (unit.get("unit_id") or "").strip()

    # Normalize status
    status = (unit.get("status") or "AVAILABLE").upper().strip()
    if status in ("A", "AVL"):
        status = "AVAILABLE"

    # Accept DISPATCHED as a first-class state (FORD-CAD canon)
    # (No remapping needed; just preserve)
    unit["status"] = status

    # Safe defaults
    unit.setdefault("unit_id", unit_id)
    unit.setdefault("name", unit_id)
    unit.setdefault("role", "")
    unit.setdefault("last_updated", "")
    unit.setdefault("icon", "unknown.png")

    unit.setdefault("unit_type", unit.get("unit_type"))
    unit.setdefault("is_apparatus", int(unit.get("is_apparatus") or 0))
    unit.setdefault("is_command", int(unit.get("is_command") or 0))
    unit.setdefault("is_mutual_aid", int(unit.get("is_mutual_aid") or 0))

    # Optional custom status / misc tag support (safe if missing)
    unit.setdefault("custom_status", unit.get("custom_status") or "")

    return unit


def get_incident_units(incident_id: int):
    """
    Return units assigned to an incident with joined Units metadata.

    This MUST join Units, otherwise unit status/icon/name will be wrong
    (UnitAssignments does not contain those fields).
    """
    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT
            ua.*,
            u.name,
            u.unit_type,
            u.status,
            u.last_updated,
            u.icon,
            COALESCE(u.is_apparatus,0) AS is_apparatus,
            COALESCE(u.is_command,0) AS is_command,
            COALESCE(u.is_mutual_aid,0) AS is_mutual_aid,
            COALESCE(u.custom_status,'') AS custom_status
        FROM UnitAssignments ua
        LEFT JOIN Units u
          ON u.unit_id = ua.unit_id
        WHERE ua.incident_id=?
          AND ua.cleared IS NULL
        ORDER BY
          COALESCE(ua.dispatched, ua.assigned, ua.enroute, ua.arrived, ua.transporting) ASC
    """, (incident_id,)).fetchall()

    results = []
    for r in rows:
        d = dict(r)

        # Normalize unit metadata (Units fields)
        attach_unit_metadata(d)

        # Ensure assignment timestamps exist as strings for templates
        for f in ("assigned", "dispatched", "enroute", "arrived", "transporting", "at_medical", "cleared"):
            d[f] = d.get(f) or ""

        # Convenience flags (many templates use these)
        d["dispatched"] = d["dispatched"] or ""
        d["enroute"] = d["enroute"] or ""
        d["arrived"] = d["arrived"] or ""
        d["transporting"] = d["transporting"] or ""
        d["at_medical"] = d["at_medical"] or ""
        d["cleared"] = d["cleared"] or ""

        results.append(d)

    conn.close()
    return {"ok": bool(result_ok)}


def get_apparatus_crew(parent_unit_id: str):
    # Safe on older DBs: if table doesn't exist yet, return no crew.
    conn = get_conn()
    c = conn.cursor()

    try:
        exists = c.execute("""
            SELECT 1
            FROM sqlite_master
            WHERE type='table' AND name='PersonnelAssignments'
            LIMIT 1
        """).fetchone()

        if not exists:
            return []

        rows = c.execute("""
            SELECT personnel_id
            FROM PersonnelAssignments
            WHERE apparatus_id=?
            ORDER BY personnel_id ASC
        """, (parent_unit_id,)).fetchall()

        return [r["personnel_id"] for r in rows]
    finally:
        conn.close()

# ================================================================
# APPARATUS CREW ASSIGNMENTS (PERSONNEL ↔ APPARATUS)
# PersonnelAssignments is the canonical, persistent apparatus crew table.
# ================================================================

def _personnel_assignments_table_exists_tx(c) -> bool:
    row = c.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type='table' AND name='PersonnelAssignments'
        LIMIT 1
        """
    ).fetchone()
    return bool(row)


def get_personnel_parent_apparatus(personnel_id: str) -> str | None:
    """Returns the apparatus_id this personnel_id is assigned to (or None)."""
    ensure_phase3_schema()
    pid = (personnel_id or "").strip()
    if not pid:
        return None

    conn = get_conn()
    c = conn.cursor()
    try:
        if not _personnel_assignments_table_exists_tx(c):
            return None
        row = c.execute(
            """
            SELECT apparatus_id
            FROM PersonnelAssignments
            WHERE personnel_id = ?
            LIMIT 1
            """,
            (pid,),
        ).fetchone()
        return (row["apparatus_id"] if row else None)
    finally:
        conn.close()


def get_apparatus_crew_details(apparatus_id: str) -> list[dict]:
    """Returns crew rows with optional role/shift + joined Units metadata."""
    ensure_phase3_schema()
    aid = (apparatus_id or "").strip()
    if not aid:
        return []

    conn = get_conn()
    c = conn.cursor()
    try:
        if not _personnel_assignments_table_exists_tx(c):
            return []

        rows = c.execute(
            """
            SELECT
                pa.personnel_id,
                COALESCE(pa.role,'')  AS role,
                COALESCE(pa.shift,'') AS shift,
                COALESCE(pa.updated,'') AS updated,
                COALESCE(u.icon,'')   AS icon,
                COALESCE(u.status,'') AS status,
                COALESCE(u.custom_status,'') AS custom_status
            FROM PersonnelAssignments pa
            LEFT JOIN Units u ON u.unit_id = pa.personnel_id
            WHERE pa.apparatus_id = ?
            ORDER BY pa.personnel_id ASC
            """,
            (aid,),
        ).fetchall()
        return [dict(r) for r in rows] if rows else []
    finally:
        conn.close()


def get_all_apparatus_crew_map() -> dict[str, list[dict]]:
    """Map: apparatus_id -> [ {personnel_id, role, shift, icon, status, custom_status} ]"""
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()
    try:
        if not _personnel_assignments_table_exists_tx(c):
            return {}

        rows = c.execute(
            """
            SELECT
                pa.apparatus_id,
                pa.personnel_id,
                COALESCE(pa.role,'')  AS role,
                COALESCE(pa.shift,'') AS shift,
                COALESCE(pa.updated,'') AS updated,
                COALESCE(u.icon,'')   AS icon,
                COALESCE(u.status,'') AS status,
                COALESCE(u.custom_status,'') AS custom_status
            FROM PersonnelAssignments pa
            LEFT JOIN Units u ON u.unit_id = pa.personnel_id
            ORDER BY pa.apparatus_id ASC, pa.personnel_id ASC
            """
        ).fetchall()

        m: dict[str, list[dict]] = {}
        for r in (rows or []):
            aid = (r["apparatus_id"] or "").strip()
            if not aid:
                continue
            m.setdefault(aid, []).append(dict(r))
        return m
    finally:
        conn.close()


def set_personnel_assignment(
    apparatus_id: str,
    personnel_id: str,
    role: str | None = None,
    shift: str | None = None,
    user: str = "System",
) -> dict:
    """Assign personnel to apparatus (move semantics: personnel can only be on one apparatus)."""
    ensure_phase3_schema()
    aid = (apparatus_id or "").strip()
    pid = (personnel_id or "").strip()
    role = (role or "").strip()
    shift = (shift or "").strip()

    if not aid or not pid:
        return {"ok": False, "error": "Missing apparatus_id or personnel_id"}

    conn = get_conn()
    c = conn.cursor()
    try:
        if not _personnel_assignments_table_exists_tx(c):
            return {"ok": False, "error": "PersonnelAssignments table missing"}

        # Validate apparatus exists + is_apparatus
        row = c.execute(
            "SELECT unit_id, COALESCE(is_apparatus,0) AS is_apparatus FROM Units WHERE unit_id=?",
            (aid,),
        ).fetchone()
        if not row:
            return {"ok": False, "error": f"Unknown apparatus {aid}"}
        if int(row["is_apparatus"] or 0) != 1:
            return {"ok": False, "error": f"{aid} is not an apparatus"}

        # Validate personnel exists (must be a known unit, but cannot be apparatus)
        prow = c.execute(
            "SELECT unit_id, COALESCE(is_apparatus,0) AS is_apparatus FROM Units WHERE unit_id=?",
            (pid,),
        ).fetchone()
        if not prow:
            return {"ok": False, "error": f"Unknown unit {pid}"}
        if int(prow["is_apparatus"] or 0) == 1:
            return {"ok": False, "error": f"Cannot assign apparatus {pid} as crew"}

        ts = _ts()
        c.execute("BEGIN IMMEDIATE")

        # Move semantics: remove personnel from any current apparatus assignment
        c.execute(
            "DELETE FROM PersonnelAssignments WHERE personnel_id = ?",
            (pid,),
        )

        c.execute(
            """
            INSERT OR REPLACE INTO PersonnelAssignments (apparatus_id, personnel_id, role, shift, updated)
            VALUES (?, ?, ?, ?, ?)
            """,
            (aid, pid, role or None, shift or None, ts),
        )

        conn.commit()

    except Exception as ex:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"ok": False, "error": f"Crew assignment failed: {ex}"}
    finally:
        conn.close()

    try:
        masterlog(
            event_type="CREW_ASSIGN",
            user=user,
            unit_id=pid,
            details=f"{pid} assigned to {aid}{(' ('+role+')') if role else ''}",
        )
    except Exception:
        pass

    return {"ok": True, "apparatus_id": aid, "personnel_id": pid}


def clear_personnel_assignment(
    personnel_id: str,
    apparatus_id: str | None = None,
    user: str = "System",
) -> dict:
    """Unassign personnel from an apparatus. If apparatus_id omitted, unassign from any."""
    ensure_phase3_schema()
    pid = (personnel_id or "").strip()
    aid = (apparatus_id or "").strip() if apparatus_id else None
    if not pid:
        return {"ok": False, "error": "Missing personnel_id"}

    conn = get_conn()
    c = conn.cursor()
    try:
        if not _personnel_assignments_table_exists_tx(c):
            return {"ok": False, "error": "PersonnelAssignments table missing"}

        if aid:
            c.execute(
                "DELETE FROM PersonnelAssignments WHERE personnel_id=? AND apparatus_id=?",
                (pid, aid),
            )
        else:
            c.execute(
                "DELETE FROM PersonnelAssignments WHERE personnel_id=?",
                (pid,),
            )

        conn.commit()
    except Exception as ex:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"ok": False, "error": f"Crew unassign failed: {ex}"}
    finally:
        conn.close()

    try:
        masterlog(
            event_type="CREW_UNASSIGN",
            user=user,
            unit_id=pid,
            details=f"{pid} unassigned{(' from '+aid) if aid else ''}",
        )
    except Exception:
        pass

    return {"ok": True, "personnel_id": pid, "apparatus_id": aid}


@app.get("/api/apparatus/list")
async def api_apparatus_list():
    """Ordered list of apparatus for pickers/UAW."""
    ensure_phase3_schema()
    units = fetch_units() or []
    groups = split_units_for_picker(units)
    apparatus = groups.get("apparatus") or []
    return {
        "ok": True,
        "apparatus": [
            {"unit_id": (u.get("unit_id") or "").strip(), "name": (u.get("name") or "").strip()}
            for u in apparatus
            if (u.get("unit_id") or "").strip()
        ],
    }


@app.get("/api/crew/for_personnel/{personnel_id}")
async def api_crew_for_personnel(personnel_id: str):
    ensure_phase3_schema()
    aid = get_personnel_parent_apparatus(personnel_id)
    return {"ok": True, "personnel_id": personnel_id, "apparatus_id": aid}


@app.get("/api/crew/for_apparatus/{apparatus_id}")
async def api_crew_for_apparatus(apparatus_id: str):
    ensure_phase3_schema()
    crew = get_apparatus_crew_details(apparatus_id)
    return {"ok": True, "apparatus_id": apparatus_id, "crew": crew}


@app.post("/api/crew/assign")
async def api_crew_assign(request: Request):
    ensure_phase3_schema()
    data = await request.json()

    apparatus_id = (data.get("apparatus_id") or "").strip()
    personnel_id = (data.get("personnel_id") or "").strip()
    role = (data.get("role") or "").strip()
    shift = (data.get("shift") or "").strip()
    if not shift:
        shift = get_session_shift_effective(request)


    user = request.session.get("user", "Dispatcher")
    return set_personnel_assignment(
        apparatus_id=apparatus_id,
        personnel_id=personnel_id,
        role=role,
        shift=shift,
        user=user,
    )


@app.post("/api/crew/unassign")
async def api_crew_unassign(request: Request):
    ensure_phase3_schema()
    data = await request.json()

    personnel_id = (data.get("personnel_id") or "").strip()
    apparatus_id = (data.get("apparatus_id") or "").strip() or None

    user = request.session.get("user", "Dispatcher")
    return clear_personnel_assignment(
        personnel_id=personnel_id,
        apparatus_id=apparatus_id,
        user=user,
    )


@app.post("/api/unit/transfer_assignment")
async def api_unit_transfer_assignment(request: Request):
    """Move an ACTIVE unit assignment from one incident to another (drag-drop transfer)."""
    ensure_phase3_schema()
    data = await request.json()
    unit_id = (data.get("unit_id") or "").strip()
    from_incident_id = int(data.get("from_incident_id") or 0)
    to_incident_id = int(data.get("to_incident_id") or 0)

    if not unit_id or from_incident_id <= 0 or to_incident_id <= 0:
        return {"ok": False, "error": "Missing unit_id/from_incident_id/to_incident_id"}
    if from_incident_id == to_incident_id:
        return {"ok": False, "error": "from_incident_id equals to_incident_id"}

    user = request.session.get("user", "Dispatcher")

    conn = get_conn()
    c = conn.cursor()
    try:
        # Block apparatus transfer (too much implicit side-effect)
        row = c.execute(
            "SELECT COALESCE(is_apparatus,0) AS is_apparatus FROM Units WHERE unit_id=?",
            (unit_id,),
        ).fetchone()
        if row and int(row["is_apparatus"] or 0) == 1:
            return {"ok": False, "error": "Use dispatch/clear flows for apparatus (transfer disabled)"}

        # Validate target incident is dispatchable
        inc = c.execute(
            "SELECT status FROM Incidents WHERE incident_id=?",
            (to_incident_id,),
        ).fetchone()
        if not inc:
            return {"ok": False, "error": "Target incident not found"}
        if (inc["status"] or "").upper().strip() in ("HELD", "CLOSED"):
            return {"ok": False, "error": f"Cannot transfer into {inc['status']} incident"}

        # Validate assignment exists on from_incident
        exists = c.execute(
            """
            SELECT 1
            FROM UnitAssignments
            WHERE incident_id=? AND unit_id=? AND cleared IS NULL
            LIMIT 1
            """,
            (from_incident_id, unit_id),
        ).fetchone()
        if not exists:
            return {"ok": False, "error": "Unit not actively assigned to from_incident"}

        # Ensure not already assigned to target
        already = c.execute(
            """
            SELECT 1
            FROM UnitAssignments
            WHERE incident_id=? AND unit_id=? AND cleared IS NULL
            LIMIT 1
            """,
            (to_incident_id, unit_id),
        ).fetchone()
        if already:
            return {"ok": False, "error": "Unit already assigned to target incident"}

        c.execute("BEGIN IMMEDIATE")
        c.execute(
            """
            UPDATE UnitAssignments
            SET incident_id=?
            WHERE incident_id=? AND unit_id=? AND cleared IS NULL
            """,
            (to_incident_id, from_incident_id, unit_id),
        )
        c.execute("UPDATE Incidents SET updated=? WHERE incident_id IN (?, ?)", (_ts(), from_incident_id, to_incident_id))
        conn.commit()

    except Exception as ex:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"ok": False, "error": f"Transfer failed: {ex}"}
    finally:
        conn.close()

    try:
        incident_history(from_incident_id, "UNIT_TRANSFER_OUT", user=user, unit_id=unit_id, details=f"Transferred to incident {to_incident_id}")
        incident_history(to_incident_id, "UNIT_TRANSFER_IN", user=user, unit_id=unit_id, details=f"Transferred from incident {from_incident_id}")
    except Exception:
        pass

    return {"ok": True, "unit_id": unit_id, "from_incident_id": from_incident_id, "to_incident_id": to_incident_id}


def update_unit_status(unit_id: str, new_status: str):
    new_status = (new_status or "").upper().strip()
    ts = _ts()

    conn = get_conn()
    c = conn.cursor()

    row = c.execute(
        "SELECT status FROM Units WHERE unit_id=?",
        (unit_id,)
    ).fetchone()

    if not row:
        conn.close()
        return

    current = (row["status"] or "").upper().strip()
    if current == new_status:
        conn.close()
        return

    # When a unit returns to AVAILABLE, also clear any misc/custom status.
    if new_status == "AVAILABLE":
        c.execute("""
            UPDATE Units
            SET status=?, custom_status='', last_updated=?
            WHERE unit_id=?
        """, (new_status, ts, unit_id))
    else:
        c.execute("""
            UPDATE Units
            SET status=?, last_updated=?
            WHERE unit_id=?
        """, (new_status, ts, unit_id))

    conn.commit()
    conn.close()

    dailylog_event(
        event_type="STATUS_CHANGE",
        details=f"{unit_id} → {new_status}",
        unit_id=unit_id
    )

    masterlog(
        action="UNIT_STATUS_UPDATE",
        unit_id=unit_id,
        details=new_status
    )





def set_unit_status_pipeline(unit_id: str, status: str):
    """
    Phase-3 rule:
    Status propagation does NOT create or assign units.
    Dispatch handles crew following.
    """
    update_unit_status(unit_id, status)


def assign_unit_to_incident(incident_id: int, unit_id: str):
    """
    Legacy wrapper used by older code paths.

    FORD-CAD canon:
      - Assignment created with assigned + dispatched timestamps
      - Unit status becomes DISPATCHED (NOT ENROUTE)
      - Apparatus mirrors to crew (DISPATCHED)
    """
    ts = _ts()

    conn = get_conn()
    c = conn.cursor()

    # Block dispatch to HELD/CLOSED
    inc = c.execute("""
        SELECT status FROM Incidents WHERE incident_id=?
    """, (incident_id,)).fetchone()
    if not inc or inc["status"] in ("HELD", "CLOSED"):
        conn.close()
        return

    # Already assigned?
    exists = c.execute("""
        SELECT 1 FROM UnitAssignments
        WHERE incident_id=? AND unit_id=? AND cleared IS NULL
    """, (incident_id, unit_id)).fetchone()

    if exists:
        conn.close()
        return

    # Create assignment (assigned + dispatched)
    c.execute("""
        INSERT INTO UnitAssignments (incident_id, unit_id, assigned, dispatched)
        VALUES (?, ?, ?, ?)
    """, (incident_id, unit_id, ts, ts))

    # Unit status becomes DISPATCHED (orange)
    update_unit_status(unit_id, "DISPATCHED")

    masterlog(
        event_type="UNIT_DISPATCHED",
        incident_id=incident_id,
        unit_id=unit_id
    )

    # Apparatus auto-dispatches crew (DISPATCHED)
    row = c.execute("""
        SELECT COALESCE(is_apparatus,0) AS is_apparatus
        FROM Units
        WHERE unit_id=?
    """, (unit_id,)).fetchone()

    if row and row["is_apparatus"] == 1:
        crew = c.execute("""
            SELECT personnel_id
            FROM PersonnelAssignments
            WHERE apparatus_id=?
            ORDER BY personnel_id ASC
        """, (unit_id,)).fetchall()

        for m in crew:
            pid = m["personnel_id"]
            if not pid:
                continue

            pexists = c.execute("""
                SELECT 1 FROM UnitAssignments
                WHERE incident_id=? AND unit_id=? AND cleared IS NULL
            """, (incident_id, pid)).fetchone()
            if pexists:
                continue

            c.execute("""
                INSERT INTO UnitAssignments (incident_id, unit_id, assigned, dispatched)
                VALUES (?, ?, ?, ?)
            """, (incident_id, pid, ts, ts))

            update_unit_status(pid, "DISPATCHED")

    # Promote incident to ACTIVE if needed
    if inc["status"] == "OPEN":
        c.execute("""
            UPDATE Incidents
            SET status='ACTIVE', updated=?
            WHERE incident_id=?
        """, (ts, incident_id))

    conn.commit()
    conn.close()


# ======================================================================
# BLOCK 1B — DISPATCH ENGINE (PHASE-3 CANON)
# ======================================================================

def incident_promote_to_active(incident_id: int):
    """
    Promote an incident from OPEN → ACTIVE.
    This is ONLY allowed after at least one unit is dispatched.
    """
    conn = get_conn()
    c = conn.cursor()

    row = c.execute(
        "SELECT status FROM Incidents WHERE incident_id=?",
        (incident_id,)
    ).fetchone()

    if row and row["status"] == "OPEN":
        c.execute("""
            UPDATE Incidents
            SET status='ACTIVE',
                updated=?
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

    return bool(row and row["status"] == "AVAILABLE")


@app.post("/incident/{incident_id}/dispatch_units")
async def dispatch_units(incident_id: int, request: Request):
    """
    Dispatch units to incident - delegates to canonical dispatch_units_to_incident function.
    """
    data = await request.json()
    units = data.get("units", [])
    user = request.session.get("user", "Dispatcher")

    if not units:
        return {"ok": False, "error": "No units provided"}

    # Use the canonical dispatch function which handles transactions properly
    result = dispatch_units_to_incident(incident_id, units, user)

    # Map response to expected format for backward compatibility
    if result.get("ok"):
        return {"ok": True, "units": result.get("assigned", [])}
    else:
        return result


def legacy_add_narrative_v1(incident_id: int, text: str, unit_id: str = None):
    """
    Legacy compatibility wrapper.
    """
    add_narrative(
        incident_id=incident_id,
        user="SYSTEM",
        text=text,
        entry_type="LEGACY",
        unit_id=unit_id
    )


def get_narrative_for_incident(incident_id: int):
    """
    Returns a fully normalized narrative timeline.
    """
    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT
            timestamp,
            entry_type,
            text,
            user,
            unit_id
        FROM Narrative
        WHERE incident_id=?
        ORDER BY timestamp ASC
    """, (incident_id,)).fetchall()

    conn.close()

    results = []
    for r in rows:
        d = dict(r)
        d.setdefault("entry_type", "REMARK")
        d.setdefault("user", "")
        d.setdefault("unit_id", "")
        results.append(d)

    return {"ok": bool(result_ok)}
# =====================================================================
# BLOCK 4 — ISSUE FOUND SYSTEM (PHASE-3 CANON)
# =====================================================================

def record_issue_found(
    incident_id: int | None,
    category: str,
    description: str,
    user: str
):
    """
    Canonical Issue Found handler.
    """

    details = f"{category}: {description}".strip()

    dailylog_event(
        event_type="ISSUE_FOUND",
        details=details,
        user=user,
        incident_id=incident_id,
        unit_id=None,
        issue_found=1
    )

    if incident_id:
        conn = get_conn()
        c = conn.cursor()
        c.execute("""
            UPDATE Incidents
            SET issue_flag=1, issue_found=1, updated=?
            WHERE incident_id=?
        """, (_ts(), incident_id))
        conn.commit()
        conn.close()


@app.post("/issue_found")
async def issue_found_submit(request: Request):
    """
    Issue Found modal submit.
    """

    data = await request.json()

    category    = (data.get("category") or "").strip()
    description = (data.get("description") or "").strip()
    incident_id = data.get("incident_id")

    if isinstance(incident_id, str) and incident_id.isdigit():
        incident_id = int(incident_id)
    elif incident_id in ("", None):
        incident_id = None

    if not category or not description:
        return {"ok": False, "error": "Missing category or description"}

    user = request.session.get("user", "Dispatcher")

    record_issue_found(
        incident_id=incident_id,
        category=category,
        description=description,
        user=user
    )

    return {"ok": True}


def incident_has_issue(incident_id: int) -> bool:
    """
    Used ONLY for showing ⚠ in incident lists.
    """
    conn = get_conn()
    c = conn.cursor()

    row = c.execute("""
        SELECT issue_flag
        FROM Incidents
        WHERE incident_id=?
    """, (incident_id,)).fetchone()

    conn.close()
    return bool(row and row["issue_flag"] == 1)

# =====================================================================
# BLOCK 5 — REMARK SYSTEM (PHASE-3 CANON)
# =====================================================================


@app.get("/incident/{incident_id}/remarks", response_class=HTMLResponse)
async def iaw_remarks_panel(request: Request, incident_id: int):
    """
    Loads remark list for IAW Remarks tab.
    """

    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT timestamp, text, user, unit_id
        FROM Narrative
        WHERE incident_id=?
          AND entry_type='REMARK'
        ORDER BY timestamp ASC
    """, (incident_id,)).fetchall()

    conn.close()

    # Note: This template may not exist - using narrative fragment as fallback
    return templates.TemplateResponse(
        "iaw/iaw_narrative_fragment.html",
        {
            "request": request,
            "incident_id": incident_id,
            "remarks": [dict(r) for r in rows]
        }
    )

# =====================================================================
# BLOCK 6 — UNIT STATUS + DISPOSITION ENGINE (FORD-CAD CANON)
# =====================================================================

VALID_UNIT_STATUSES = {
    "DISPATCHED",
    "ENROUTE",
    "ARRIVED",
    "TRANSPORTING",
    "AT_MEDICAL",
    "CLEARED",
    "EMERGENCY",
    "UNAVAILABLE",
}

VALID_DISPOSITIONS = {"R", "NA", "NF", "C", "CT", "O", "FA", "FF", "MF", "MT", "PR"}


def mark_assignment(incident_id: int, unit_id: str, field: str):
    """
    Safely timestamps a UnitAssignments field (assigned/dispatched/enroute/arrived/...).
    """
    conn = get_conn()
    c = conn.cursor()

    c.execute(
        f"""
        UPDATE UnitAssignments
        SET {field} = ?
        WHERE incident_id = ? AND unit_id = ? AND cleared IS NULL
        """,
        (_ts(), incident_id, unit_id)
    )

    conn.commit()
    conn.close()


def ensure_assignment_row(incident_id: int, unit_id: str):
    """
    Guarantees an active UnitAssignments row exists for this incident/unit.
    If missing, creates one with assigned timestamp (not dispatched).
    """
    ts = _ts()
    conn = get_conn()
    c = conn.cursor()

    exists = c.execute("""
        SELECT 1
        FROM UnitAssignments
        WHERE incident_id = ? AND unit_id = ? AND cleared IS NULL
        LIMIT 1
    """, (incident_id, unit_id)).fetchone()

    if not exists:
        c.execute("""
            INSERT INTO UnitAssignments (incident_id, unit_id, assigned)
            VALUES (?, ?, ?)
        """, (incident_id, unit_id, ts))

    conn.commit()
    conn.close()


@app.post("/incident/{incident_id}/unit/{unit_id}/status")
async def unit_status_update(
    request: Request,
    incident_id: int,
    unit_id: str
):
    data = await request.json()
    new_status = (data.get("status") or "").upper().strip()
    user = request.session.get("user", "Dispatcher")
    ensure_phase3_schema()

    # Only apparatus should attempt crew mirroring
    conn = get_conn()
    c = conn.cursor()
    row = c.execute(
        "SELECT COALESCE(is_apparatus,0) AS is_apparatus FROM Units WHERE unit_id=?",
        (unit_id,)
    ).fetchone()
    conn.close()
    _is_apparatus = bool(row and int(row["is_apparatus"] or 0) == 1)


    if new_status not in VALID_UNIT_STATUSES:
        return {"ok": False, "error": f"Invalid status {new_status}"}

    def _has_disposition() -> bool:
        conn = get_conn()
        c = conn.cursor()
        row = c.execute("""
            SELECT disposition
            FROM UnitAssignments
            WHERE incident_id = ? AND unit_id = ? AND cleared IS NULL
            LIMIT 1
        """, (incident_id, unit_id)).fetchone()
        conn.close()
        if not row:
            return False
        dispo = (row[0] or "").strip()
        return bool(dispo)

    # Ensure assignment exists for incident-scoped unit status changes
    ensure_assignment_row(incident_id, unit_id)

    # Canon: apparatus status mirrors to assigned crew (personnel) automatically.
    # Mirror only to crew that already has an active assignment on THIS incident.
    def _mirror_to_crew(field: str | None = None):
        if not _is_apparatus:
            return

        crew = get_apparatus_crew(unit_id)
        if not crew:
            return

        conn = get_conn()
        c = conn.cursor()
        try:
            for pid in crew:
                exists = c.execute(
                    """
                    SELECT 1
                    FROM UnitAssignments
                    WHERE incident_id = ? AND unit_id = ? AND cleared IS NULL
                    LIMIT 1
                    """,
                    (incident_id, pid),
                ).fetchone()
                if not exists:
                    continue

                set_unit_status_pipeline(pid, new_status)
                if field:
                    mark_assignment(incident_id, pid, field)
        finally:
            conn.close()


    # DISPATCHED
    if new_status == "DISPATCHED":
        set_unit_status_pipeline(unit_id, "DISPATCHED")
        mark_assignment(incident_id, unit_id, "dispatched")
        incident_history(incident_id, "DISPATCHED", user=user, unit_id=unit_id)
        _mirror_to_crew("dispatched")
        return {"ok": True}

    if new_status == "ENROUTE":
        set_unit_status_pipeline(unit_id, "ENROUTE")
        mark_assignment(incident_id, unit_id, "enroute")
        incident_history(incident_id, "ENROUTE", user=user, unit_id=unit_id)
        _mirror_to_crew("enroute")

    elif new_status == "ARRIVED":
        set_unit_status_pipeline(unit_id, "ARRIVED")
        mark_assignment(incident_id, unit_id, "arrived")
        incident_history(incident_id, "ARRIVED", user=user, unit_id=unit_id)
        _mirror_to_crew("arrived")

        # Auto-command: first ARRIVED unit becomes command (if supported)
        conn = get_conn()
        c = conn.cursor()

        ua_cols = [r["name"] for r in c.execute("PRAGMA table_info(UnitAssignments)").fetchall()]
        has_cmd_col = "commanding_unit" in ua_cols

        if has_cmd_col:
            has_cmd = c.execute("""
                SELECT 1
                FROM UnitAssignments
                WHERE incident_id = ?
                  AND cleared IS NULL
                  AND COALESCE(commanding_unit, 0) = 1
                LIMIT 1
            """, (incident_id,)).fetchone()

            if not has_cmd:
                c.execute("""
                    UPDATE UnitAssignments
                    SET commanding_unit = 0
                    WHERE incident_id = ?
                      AND cleared IS NULL
                """, (incident_id,))
                c.execute("""
                    UPDATE UnitAssignments
                    SET commanding_unit = 1
                    WHERE incident_id = ?
                      AND unit_id = ?
                      AND cleared IS NULL
                """, (incident_id, unit_id))

            conn.commit()

        conn.close()

    elif new_status == "TRANSPORTING":
        set_unit_status_pipeline(unit_id, "TRANSPORTING")
        mark_assignment(incident_id, unit_id, "transporting")
        incident_history(incident_id, "TRANSPORTING", user=user, unit_id=unit_id)
        _mirror_to_crew("transporting")

    elif new_status == "AT_MEDICAL":
        set_unit_status_pipeline(unit_id, "AT_MEDICAL")
        mark_assignment(incident_id, unit_id, "at_medical")
        incident_history(incident_id, "AT_MEDICAL", user=user, unit_id=unit_id)
        _mirror_to_crew("at_medical")

    elif new_status == "EMERGENCY":
        set_unit_status_pipeline(unit_id, "EMERGENCY")
        incident_history(incident_id, "EMERGENCY", user=user, unit_id=unit_id)
        _mirror_to_crew()

    elif new_status == "UNAVAILABLE":
        set_unit_status_pipeline(unit_id, "UNAVAILABLE")
        incident_history(incident_id, "UNAVAILABLE", user=user, unit_id=unit_id)
        _mirror_to_crew()

    elif new_status == "CLEARED":
        conn = get_conn()
        c = conn.cursor()

        ua_cols = [r[1] for r in c.execute("PRAGMA table_info(UnitAssignments)").fetchall()]
        has_cmd = "commanding_unit" in ua_cols

        is_cmd = False
        if has_cmd:
            row = c.execute("""
                SELECT 1
                FROM UnitAssignments
                WHERE incident_id = ?
                  AND unit_id = ?
                  AND cleared IS NULL
                  AND COALESCE(commanding_unit,0) = 1
                LIMIT 1
            """, (incident_id, unit_id)).fetchone()
            is_cmd = bool(row)

        remaining_after = c.execute("""
            SELECT COUNT(1)
            FROM UnitAssignments
            WHERE incident_id = ?
              AND cleared IS NULL
              AND unit_id <> ?
        """, (incident_id, unit_id)).fetchone()[0]

        conn.close()

        requires_dispo = is_cmd or (int(remaining_after) == 0)

        if requires_dispo and not _has_disposition():
            return {
                "ok": False,
                "error": "Disposition required before clearing (command unit or last unit)."
            }

        mark_assignment(incident_id, unit_id, "cleared")
        set_unit_status_pipeline(unit_id, "AVAILABLE")
        incident_history(incident_id, "CLEARED", user=user, unit_id=unit_id)

        if int(remaining_after) == 0:
            return {"ok": True, "last_unit_cleared": True, "requires_event_disposition": True}

        conn = get_conn()
        c = conn.cursor()
        remaining = c.execute("""
            SELECT COUNT(1)
            FROM UnitAssignments
            WHERE incident_id = ?
              AND cleared IS NULL
        """, (incident_id,)).fetchone()[0]
        conn.close()

        if remaining == 0:
            return {"ok": True, "last_unit_cleared": True, "requires_event_disposition": True}

    return {"ok": True}



@app.post("/incident/{incident_id}/unit/{unit_id}/disposition")
async def unit_disposition_submit(
    request: Request,
    incident_id: int,
    unit_id: str
):
    try:
        data = await request.json()
    except Exception:
        data = {}

    disposition = (data.get("disposition") or "").upper().strip()
    remark = (data.get("remark") or "").strip()
    user = request.session.get("user", "Dispatcher")

    if disposition not in VALID_DISPOSITIONS:
        return {"ok": False, "error": "Invalid disposition"}

    # Ensure assignment exists so disposition always has a row
    ensure_assignment_row(incident_id, unit_id)

    conn = get_conn()
    c = conn.cursor()

    # Optional remark column support (non-breaking)
    cols = [r["name"] for r in c.execute("PRAGMA table_info(UnitAssignments)").fetchall()]
    has_remark_col = "disposition_remark" in cols

    if has_remark_col:
        c.execute("""
            UPDATE UnitAssignments
            SET disposition = ?, disposition_remark = ?
            WHERE incident_id = ? AND unit_id = ? AND cleared IS NULL
        """, (disposition, remark, incident_id, unit_id))
    else:
        c.execute("""
            UPDATE UnitAssignments
            SET disposition = ?
            WHERE incident_id = ? AND unit_id = ? AND cleared IS NULL
        """, (disposition, incident_id, unit_id))

    conn.commit()
    conn.close()

    # Log disposition + optional remark
    details = f"Disposition set to {disposition}"
    if remark:
        details += f" | Remark: {remark}"

    incident_history(
        incident_id,
        "UNIT_DISPOSITION",
        user=user,
        unit_id=unit_id,
        details=details
    )

    # Optional: mirror to MasterLog / DailyLog if you want (keeping minimal for now)
    masterlog(
        action="UNIT_DISPOSITION",
        user=user,
        incident_id=incident_id,
        unit_id=unit_id,
        details=details
    )

    return {"ok": True}



# =====================================================================
# BLOCK 7 — INCIDENT DISPOSITION (FORD-CAD CANON)
#   - Inline expansion in IAW (no blocking modal required)
#   - Event disposition can be entered even if units still active
#   - Incident may only CLOSE when:
#       (1) final_disposition is set AND
#       (2) all units are cleared
# =====================================================================

VALID_EVENT_DISPO = {
    # Primary Disposition Codes
    "R":    "Report",
    "C":    "Clear",
    "X":    "Cancel",
    "FA":   "False Alarm",
    "NR":   "No Report",
    "UF":   "Unfounded",
    "NC":   "Negative Contact",
    "T":    "Transported",
    "PRTT": "Patient Refused Treatment/Transport",
    "H":    "Held",
    "O":    "Other",

    # Aliases and variations (all normalize to primary codes)
    "RT": "Report",
    "REP": "Report",
    "REPORT": "Report",
    "CLR": "Clear",
    "CLEAR": "Clear",
    "CAN": "Cancel",
    "CANCEL": "Cancel",
    "CANCELLED": "Cancel",
    "CANCELED": "Cancel",
    "FALSE ALARM": "False Alarm",
    "NO REPORT": "No Report",
    "NF": "Unfounded",
    "UNFOUNDED": "Unfounded",
    "NO FINDING": "Unfounded",
    "NOT FOUND": "Unfounded",
    "NOTHING FOUND": "Unfounded",
    "NEG CONTACT": "Negative Contact",
    "NEGATIVE CONTACT": "Negative Contact",
    "TR": "Transported",
    "TRANSPORT": "Transported",
    "TRANSPORTED": "Transported",
    "TRANSFERRED": "Transported",
    "TRANSFER": "Transported",
    "CT": "Transported",
    "PR": "Patient Refused Treatment/Transport",
    "REFUSAL": "Patient Refused Treatment/Transport",
    "REFUSED": "Patient Refused Treatment/Transport",
    "PATIENT REFUSAL": "Patient Refused Treatment/Transport",
    "PATIENT REFUSED": "Patient Refused Treatment/Transport",
    "HELD": "Held",
    "HOLD": "Held",
    "OTHER": "Other",
    "NA": "No Action",
    "NO ACTION": "No Action",

    # Legacy
    "CLOSED": "Closed",
    "CLOSE": "Closed",
}
@app.get("/incident/{incident_id}/disposition", response_class=HTMLResponse)
async def load_disposition_modal(request: Request, incident_id: int):
    """
    Legacy endpoint kept for compatibility.
    The UI is now inline in IAW; this template may still be used by older code paths.
    """
    return templates.TemplateResponse(
        "modals/event_disposition_modal.html",
        {
            "request": request,
            "incident_id": incident_id,
            "valid_codes": VALID_EVENT_DISPO
        }
    )


@app.post("/incident/{incident_id}/disposition")
async def submit_incident_disposition(incident_id: int, request: Request):
    """
    Event Disposition submission (Phase-3 Canon):
      • Required when the LAST unit clears an incident
      • On submit:
          - Persist final_disposition + note
          - If disposition is HOLD (H): mark incident HELD and store held_reason (note required)
          - Else, if there are no active units remaining: mark incident CLOSED
      • Never auto-closes while units remain assigned
    """
    ensure_phase3_schema()

    # Parse JSON payload (UI uses postJSON)
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    # Accept multiple key names (UI drift happens; harden the API)
    raw_dispo = (
        payload.get("disposition")
        or payload.get("final_disposition")
        or payload.get("event_disposition")
        or payload.get("code")
        or ""
    )

    note = (
        payload.get("note")
        or payload.get("final_disposition_note")
        or payload.get("held_reason")
        or ""
    )
    note = str(note).strip()

    raw_dispo = str(raw_dispo).strip()
    if not raw_dispo:
        raise HTTPException(
            status_code=400,
            detail="Invalid event disposition (missing disposition/code).",
        )

    key = re.sub(r"\s+", " ", raw_dispo.upper().strip())

    normalize = {
        # Report - R
        "R": "R",
        "RT": "R",
        "REP": "R",
        "REPORT": "R",

        # Clear - C
        "C": "C",
        "CLR": "C",
        "CLEAR": "C",

        # Cancel - X
        "X": "X",
        "CAN": "X",
        "CANCEL": "X",
        "CANCELLED": "X",
        "CANCELED": "X",

        # False Alarm - FA
        "FA": "FA",
        "FALSE ALARM": "FA",

        # No Report - NR
        "NR": "NR",
        "NO REPORT": "NR",

        # Unfounded - UF
        "UF": "UF",
        "NF": "UF",
        "UNFOUNDED": "UF",
        "NO FINDING": "UF",
        "NOT FOUND": "UF",
        "NOTHING FOUND": "UF",

        # Negative Contact - NC
        "NC": "NC",
        "NEG CONTACT": "NC",
        "NEGATIVE CONTACT": "NC",

        # Transported - T
        "T": "T",
        "TR": "T",
        "TRANSPORT": "T",
        "TRANSPORTED": "T",
        "TRANSFERRED": "T",
        "TRANSFER": "T",
        "CT": "T",  # Care Transferred -> T

        # Patient Refused Treatment/Transport - PRTT
        "PRTT": "PRTT",
        "PR": "PRTT",
        "REFUSAL": "PRTT",
        "REFUSED": "PRTT",
        "PATIENT REFUSAL": "PRTT",
        "PATIENT REFUSED": "PRTT",

        # Hold
        "H": "H",
        "HELD": "H",
        "HOLD": "H",

        # Other / Legacy
        "O": "O",
        "OTHER": "O",
        "NA": "NA",
        "NO ACTION": "NA",
    }

    dispo = normalize.get(key, key)

    # If it's not a known code, store normalized text (cap for DB)
    if dispo not in VALID_EVENT_DISPO:
        dispo = dispo[:24]

    # HOLD requires a note
    if dispo == "H" and not note:
        raise HTTPException(status_code=400, detail="Held disposition requires a note/reason.")

    conn = get_conn()
    c = conn.cursor()

    try:
        # ---- Detect schema columns (older DBs drift) ------------------------
        inc_cols = {r["name"] for r in c.execute("PRAGMA table_info(Incidents)").fetchall()}
        ua_cols  = {r["name"] for r in c.execute("PRAGMA table_info(UnitAssignments)").fetchall()}

        # Pick the correct "cleared" column name for UnitAssignments
        if "cleared_at" in ua_cols:
            cleared_expr = "(cleared_at IS NULL OR cleared_at = '')"
        elif "cleared" in ua_cols:
            cleared_expr = "(cleared IS NULL OR cleared = '')"
        else:
            # Defensive fallback: if we can't tell, assume units remain (never auto-close).
            cleared_expr = "1=1"

        # ---- Update Incidents safely (only columns that exist) --------------
        set_parts = []
        params = []

        if "final_disposition" in inc_cols:
            set_parts.append("final_disposition = ?")
            params.append(dispo)

        if "final_disposition_note" in inc_cols:
            set_parts.append("final_disposition_note = ?")
            params.append(note)

        if "held_reason" in inc_cols:
            set_parts.append("held_reason = CASE WHEN ? = 'H' THEN ? ELSE held_reason END")
            params.extend([dispo, note])

        if not set_parts:
            raise HTTPException(status_code=500, detail="Incidents table missing final disposition columns.")

        params.append(incident_id)

        c.execute(
            f"""
            UPDATE Incidents
            SET {", ".join(set_parts)}
            WHERE incident_id = ?
            """,
            tuple(params),
        )

        # ---- Count remaining uncleared unit assignments ---------------------
        remaining = c.execute(
            f"""
            SELECT COUNT(*)
            FROM UnitAssignments
            WHERE incident_id = ?
              AND {cleared_expr}
            """,
            (incident_id,),
        ).fetchone()[0]

        # ---- Lifecycle transition rules ------------------------------------
        if dispo == "H":
            c.execute("UPDATE Incidents SET status='HELD' WHERE incident_id=?", (incident_id,))
            resulting_status = "HELD"
        else:
            if int(remaining) == 0:
                # Bulletproof timestamp: do not depend on how datetime was imported elsewhere
                import datetime as _dt
                now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                if "closed_at" in inc_cols:
                    c.execute(
                        "UPDATE Incidents SET status='CLOSED', closed_at=? WHERE incident_id=?",
                        (now, incident_id),
                    )
                else:
                    c.execute(
                        "UPDATE Incidents SET status='CLOSED' WHERE incident_id=?",
                        (incident_id,),
                    )
                resulting_status = "CLOSED"
            else:
                # Never close while units remain
                resulting_status = "ACTIVE"

        conn.commit()

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail={"ok": False, "error": str(e)})
    finally:
        conn.close()

    return {
        "ok": True,
        "incident_id": incident_id,
        "disposition": dispo,
        "remaining_units": int(remaining),
        "status": resulting_status,
    }


@app.get("/incident/{incident_id}/remark", response_class=HTMLResponse)
async def load_remark_modal(request: Request, incident_id: int):
    return templates.TemplateResponse(
        "modals/remark_modal.html",  # ✅ FIXED PATH
        {
            "request": request,
            "incident_id": incident_id
        }
    )


@app.post("/remark")
async def submit_remark(request: Request):
    """
    Routing handled entirely by process_remark().
    """

    data = await request.json()

    text        = (data.get("text") or "").strip()
    unit_id     = data.get("unit_id")
    incident_id = data.get("incident_id")

    if isinstance(incident_id, str) and incident_id.isdigit():
        incident_id = int(incident_id)

    user = request.session.get("user", "Dispatcher")

    result = process_remark(
        user=user,
        text=text,
        unit_id=unit_id,
        incident_id=incident_id
    )

    return result
@app.get("/incident_has_data/{incident_id}")
def incident_has_data_api(incident_id: int):
    return {
        "has_data": incident_has_data(incident_id)
    }
# ================================================================
# HISTORY (LIST + DETAIL) — used by toolbar + modal
# ================================================================

@app.get("/history", response_class=HTMLResponse)
async def history_list(request: Request):
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT
            incident_id,
            incident_number,
            type,
            location,
            status,
            SUBSTR(COALESCE(created,''), 1, 10) AS incident_date
        FROM Incidents
        WHERE is_draft = 0
        ORDER BY updated DESC
        LIMIT 300
    """).fetchall()

    conn.close()

    return templates.TemplateResponse(
        "history.html",
        {"request": request, "incidents": [dict(r) for r in (rows or [])]},
    )


@app.get("/history/{incident_id}", response_class=HTMLResponse)
async def history_detail(request: Request, incident_id: int):
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()

    inc = c.execute("""
        SELECT
            *,
            SUBSTR(COALESCE(created,''), 1, 10) AS incident_date,
            SUBSTR(COALESCE(created,''), 12, 5) AS incident_time
        FROM Incidents
        WHERE incident_id = ?
    """, (incident_id,)).fetchone()

    if not inc:
        conn.close()
        raise HTTPException(status_code=404, detail="Incident not found")

    narrative = c.execute("""
        SELECT timestamp, user, text
        FROM Narrative
        WHERE incident_id = ?
        ORDER BY timestamp ASC
    """, (incident_id,)).fetchall()

    events = c.execute("""
        SELECT timestamp, user, event_type, unit_id, details
        FROM IncidentHistory
        WHERE incident_id = ?
        ORDER BY timestamp ASC, id ASC
    """, (incident_id,)).fetchall()

    conn.close()

    return templates.TemplateResponse(
        "history_detail.html",
        {
            "request": request,
            "incident": dict(inc),
            "events": [dict(e) for e in (events or [])],
            "narrative": [dict(n) for n in (narrative or [])],
        },
    )

# ================================================================
# INCIDENT COMMANDS — REOPEN (History/Daily Log parity)
# ================================================================

@app.post("/api/incident/reopen")
async def api_incident_reopen(request: Request):
    """Reopen a CLOSED incident back to OPEN.

    Commercial-CAD behavior:
      • Only CLOSED incidents may be reopened
      • Reopen returns the incident to OPEN (no units assigned)
      • Audit trails: IncidentHistory + MasterLog + DailyLog
    """
    ensure_phase3_schema()

    try:
        data = await request.json()
    except Exception:
        data = {}

    raw_id = data.get("incident_id")
    try:
        incident_id = int(raw_id)
    except Exception:
        return JSONResponse({"ok": False, "error": "incident_id must be an integer"}, status_code=400)

    user = request.session.get("user") or request.session.get("username") or "Dispatcher"

    conn = get_conn()
    c = conn.cursor()

    inc = c.execute("""
        SELECT incident_id, status
        FROM Incidents
        WHERE incident_id = ?
    """, (incident_id,)).fetchone()

    if not inc:
        conn.close()
        return JSONResponse({"ok": False, "error": "Incident not found"}, status_code=404)

    status = (inc["status"] or "").upper().strip()
    if status != "CLOSED":
        conn.close()
        return JSONResponse({"ok": False, "error": f"Only CLOSED incidents can be reopened (current: {status or 'UNKNOWN'})"}, status_code=400)

    # Reopen to OPEN. Clear final_disposition so a new close requires a new event disposition.
    c.execute("""
        UPDATE Incidents
        SET status = 'OPEN', final_disposition = NULL, updated = ?
        WHERE incident_id = ?
    """, (_ts(), incident_id))

    conn.commit()
    conn.close()

    # Audit trails
    try:
        incident_history(incident_id, "INCIDENT_REOPENED", user=user, details="Reopened")
    except Exception:
        pass
    try:
        masterlog(event_type="INCIDENT_REOPENED", user=user, incident_id=incident_id, details="Reopened")
    except Exception:
        pass
    try:
        dailylog_event(action="INCIDENT_REOPENED", user=user, incident_id=incident_id, details="Reopened")
    except Exception:
        pass

    return {"ok": True, "incident_id": incident_id}

# =====================================================================
# BLOCK 10 — DAILY LOG ENGINE (Phase-3 Canon — FINAL)
# =====================================================================

SYSTEM_NARRATIVE_WHITELIST = {
    "DISPATCH_GROUPED",
    "INCIDENT_OPENED",
    "INCIDENT_CLOSED",
    "INCIDENT_DISPOSITION",
}


def system_narrative_allowed(event: str, incident_id: int | None) -> bool:
    """
    Determines whether a SYSTEM event is allowed to write to Narrative.
    """
    if not incident_id:
        return False

    if incident_is_dailylog(incident_id):
        return event == "ISSUE_FOUND"

    return event in SYSTEM_NARRATIVE_WHITELIST


def log_system_event(
    event: str,
    details: str,
    incident_id: int | None = None,
    unit_id: str | None = None,
    user: str | None = None,
):
    """
    Logs a system event correctly.
    """
    dailylog_event(
        action=event,
        details=details,
        incident_id=incident_id,
        unit_id=unit_id,
        user=user,
    )

    if incident_id and system_narrative_allowed(event, incident_id):
        conn = get_conn()
        c = conn.cursor()

        c.execute("""
            INSERT INTO Narrative (incident_id, timestamp, entry_type, text)
            VALUES (?, ?, 'SYSTEM', ?)
        """, (
            incident_id,
            _ts(),
            f"{event}: {details}",
        ))

        conn.commit()
        conn.close()


@app.get("/panel/dailylog", response_class=HTMLResponse)
async def panel_dailylog(request: Request):
    """
    Loads the Daily Log table rows (HTML partial) — DAILYLOG entries ONLY.
    Optional query param: ?date=YYYY-MM-DD
    """
    ensure_phase3_schema()

    date = (request.query_params.get("date") or "").strip()

    conn = get_conn()
    c = conn.cursor()

    if date:
        rows = c.execute("""
            SELECT
                id AS log_id,
                timestamp,
                incident_id,
                unit_id,
                action,
                event_type,
                details,
                user
            FROM DailyLog
            WHERE action = 'DAILYLOG'
              AND substr(timestamp, 1, 10) = ?
            ORDER BY id DESC
            LIMIT 500
        """, (date,)).fetchall()
    else:
        rows = c.execute("""
            SELECT
                id AS log_id,
                timestamp,
                incident_id,
                unit_id,
                action,
                event_type,
                details,
                user
            FROM DailyLog
            WHERE action = 'DAILYLOG'
            ORDER BY id DESC
            LIMIT 500
        """).fetchall()

    conn.close()

    entries = [dict(r) for r in (rows or [])]

    return templates.TemplateResponse(
        "partials/dailylog_rows.html",
        {
            "request": request,
            "log_entries": entries,
        },
    )



# =====================================================================
# BLOCK 11 — DISPATCH ENGINE (FORD-CAD CANON)
#   - Dispatch sets DISPATCHED (orange) and does NOT auto-set ENROUTE
#   - UnitAssignments.assigned + dispatched are populated
#   - Apparatus dispatch mirrors to crew personnel
#   - OPEN -> ACTIVE only if at least one unit assigned
#   - Incidents.updated refreshed on any successful dispatch
#   - NO extra DB connections inside transaction (prevents sqlite lock issues)
# =====================================================================

def unit_is_dispatchable(unit: dict) -> bool:
    status = (unit.get("status") or "").upper().strip()
    return status in ("AVAILABLE", "A", "AVL")


def dispatch_units_to_incident(incident_id: int, units: list[str], user: str):
    ts = _ts()

    conn = get_conn()
    c = conn.cursor()

    inc = c.execute(
        """
        SELECT status
        FROM Incidents
        WHERE incident_id=?
        """,
        (incident_id,),
    ).fetchone()

    if not inc:
        conn.close()
        return {"ok": False, "error": "Incident not found"}

    if (inc["status"] or "").upper() in ("HELD", "CLOSED"):
        conn.close()
        return {"ok": False, "error": f"Cannot dispatch to {inc['status']} incident"}

    assigned: list[str] = []
    skipped: list[str] = []

    def _fetch_unit_tx(unit_id: str) -> dict | None:
        row = c.execute(
            """
            SELECT unit_id, name, unit_type, status,
                   icon,
                   COALESCE(is_apparatus,0) AS is_apparatus,
                   COALESCE(is_command,0) AS is_command,
                   COALESCE(is_mutual_aid,0) AS is_mutual_aid
            FROM Units
            WHERE unit_id = ?
            """,
            (unit_id,),
        ).fetchone()
        return attach_unit_metadata(dict(row)) if row else None

    def _get_apparatus_crew_tx(parent_unit_id: str) -> list[str]:
        rows = c.execute(
            """
            SELECT personnel_id
            FROM PersonnelAssignments
            WHERE apparatus_id=?
            ORDER BY personnel_id ASC
            """,
            (parent_unit_id,),
        ).fetchall()
        return [r["personnel_id"] for r in rows] if rows else []

    def _is_committed_elsewhere_tx(unit_id: str) -> bool:
        # Block being assigned to a DIFFERENT incident while still active somewhere
        row = c.execute(
            """
            SELECT 1
            FROM UnitAssignments
            WHERE unit_id = ?
              AND cleared IS NULL
              AND incident_id <> ?
            LIMIT 1
            """,
            (unit_id, incident_id),
        ).fetchone()
        return bool(row)

    try:
        c.execute("BEGIN IMMEDIATE")

        def _assign_one(unit_id: str) -> bool:
            nonlocal assigned, skipped

            unit_id = (unit_id or "").strip()
            if not unit_id:
                return False

            # Idempotent for same incident
            exists_here = c.execute(
                """
                SELECT 1
                FROM UnitAssignments
                WHERE incident_id=? AND unit_id=? AND cleared IS NULL
                LIMIT 1
                """,
                (incident_id, unit_id),
            ).fetchone()
            if exists_here:
                return False

            unit = _fetch_unit_tx(unit_id)
            if not unit:
                skipped.append(f"{unit_id} (not found)")
                return False

            if not unit_is_dispatchable(unit):
                skipped.append(f"{unit_id} (not available)")
                return False

            if _is_committed_elsewhere_tx(unit_id):
                skipped.append(f"{unit_id} (already assigned)")
                return False

            c.execute(
                """
                INSERT INTO UnitAssignments (incident_id, unit_id, assigned, dispatched)
                VALUES (?, ?, ?, ?)
                """,
                (incident_id, unit_id, ts, ts),
            )

            c.execute(
                """
                UPDATE Units
                SET status='DISPATCHED', last_updated=?
                WHERE unit_id=?
                """,
                (ts, unit_id),
            )

            assigned.append(unit_id)
            return True

        for unit_id in (units or []):
            did_assign = _assign_one(unit_id)
            if not did_assign:
                continue

            unit = _fetch_unit_tx(unit_id)
            if unit and int(unit.get("is_apparatus") or 0) == 1:
                for pid in _get_apparatus_crew_tx(unit_id):
                    if pid:
                        _assign_one(pid)

        if assigned:
            c.execute(
                """
                UPDATE Incidents
                SET status = CASE
                                WHEN UPPER(COALESCE(status,'')) = 'OPEN' THEN 'ACTIVE'
                                ELSE status
                             END,
                    updated = ?
                WHERE incident_id = ?
                """,
                (ts, incident_id),
            )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    if not assigned:
        # Nothing actually went out; treat as a command failure so UI can warn.
        return {"ok": False, "error": "No units dispatched", "assigned": [], "skipped": skipped}

    unit_list = ", ".join(assigned)
    incident_history(incident_id, "DISPATCH", user=user, details=f"Units dispatched: {unit_list}")
    dailylog_event(action="DISPATCH", details=f"{user} dispatched {unit_list}", incident_id=incident_id)

    return {"ok": True, "assigned": assigned, "skipped": skipped}



@app.post("/dispatch/unit_to_incident")
async def dispatch_unit_endpoint(request: Request):
    data = await request.json()

    incident_id = data.get("incident_id")
    units = data.get("units", [])

    if not incident_id or not isinstance(units, list) or not units:
        return {"ok": False, "error": "Invalid dispatch payload"}

    user = request.session.get("user", "Dispatcher")

    return dispatch_units_to_incident(
        incident_id=int(incident_id),
        units=units,
        user=user,
    )


# ================================================================
# BLOCK 12 — IAW FEEDS (UNITS + NARRATIVE)
# ================================================================

@app.get("/incident/{incident_id}/units", response_class=HTMLResponse)
async def iaw_units_feed(request: Request, incident_id: int):

    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT 
            ua.unit_id,
            ua.assigned,
            ua.enroute,
            ua.arrived,
            ua.transporting,
            ua.cleared,
            u.name,
            u.unit_type,
            u.status,
            u.icon,
            COALESCE(u.is_apparatus,0) AS is_apparatus,
            COALESCE(u.is_command,0)   AS is_command,
            COALESCE(u.is_mutual_aid,0) AS is_mutual_aid
        FROM UnitAssignments ua
        JOIN Units u ON u.unit_id = ua.unit_id
        WHERE ua.incident_id = ?
        ORDER BY ua.assigned ASC
    """, (incident_id,)).fetchall()

    conn.close()

    units = []
    for r in rows:
        d = attach_unit_metadata(dict(r))

        for f in ("assigned", "enroute", "arrived", "transporting", "cleared"):
            d[f] = d.get(f) or ""

        units.append(d)

    ordered = []
    groups = split_units_for_picker(units)

    ordered.extend(groups["command"])
    ordered.extend(groups["personnel"])
    ordered.extend(groups["apparatus"])

    return templates.TemplateResponse(
        "iaw/iaw_units_fragment.html",  # ✅ FIXED PATH
        {
            "request": request,
            "units": ordered,
            "incident_id": incident_id
        }
    )


@app.get("/incident/{incident_id}/narrative", response_class=HTMLResponse)
async def iaw_narrative_feed(request: Request, incident_id: int):

    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT timestamp, entry_type, text, user, unit_id
        FROM Narrative
        WHERE incident_id = ?
        ORDER BY timestamp ASC
    """, (incident_id,)).fetchall()

    conn.close()

    narrative = []
    for r in rows:
        narrative.append({
            "timestamp": r["timestamp"],
            "entry_type": r["entry_type"],
            "text": r["text"],
            "user": r["user"],
            "unit_id": r["unit_id"]
        })

    return templates.TemplateResponse(
        "iaw/iaw_narrative_fragment.html",  # ✅ FIXED PATH
        {
            "request": request,
            "incident_id": incident_id,
            "narrative": narrative
        }
    )

# ================================================================
# BLOCK 13 — UNIT STATUS ENGINE (Phase-3 CANONICAL)
# ================================================================

VALID_UNIT_STATUSES = {
    "ENROUTE",
    "ARRIVED",
    "TRANSPORT",
    "CLEARED"
}


@app.post("/unit_status")
async def unit_status_api(request: Request):
    """
    Handles unit status changes from IAW.
    """

    data = await request.json()

    unit_id     = data.get("unit_id")
    incident_id = data.get("incident_id")
    status      = (data.get("status") or "").upper().strip()

    if not unit_id or not incident_id or not status:
        return {"ok": False, "error": "Missing parameters"}

    if status not in VALID_UNIT_STATUSES:
        return {"ok": False, "error": f"Invalid status '{status}'"}

    try:
        incident_id = int(incident_id)
    except ValueError:
        return {"ok": False, "error": "Invalid incident_id"}

    result = await update_unit_status_route(
        incident_id=incident_id,
        unit_id=unit_id,
        new_status=status
    )

    return {"ok": bool(result_ok)}

# ================================================================
# BLOCK 14 — DISPATCH ENGINE BRIDGE (Phase-3 Canonical)
# ================================================================

# ================================================================
# BLOCK 15 — UNIT CLEAR / DISPOSITION ENGINE (Phase-3 Canon)
# ================================================================

VALID_DISPOSITIONS_LEGACY_CLEAR = {
    # Unit disposition codes for clearing units from incidents
    # Aligned with VALID_DISPOSITIONS and Fire/EMS standards
    "R":  "Released",
    "NA": "No Action",
    "NF": "No Finding",
    "C":  "Cancelled",
    "CT": "Cancelled Enroute",
    "FA": "False Alarm",
    "FF": "Fire Found",
    "MF": "Medical First Aid",
    "MT": "Medical Transport",
    "PR": "Patient Refusal",
    "O":  "Other",
}




def mark_unit_cleared(incident_id: int, unit_id: str):
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        UPDATE UnitAssignments
        SET cleared=?
        WHERE incident_id=? AND unit_id=?
    """, (_ts(), incident_id, unit_id))

    conn.commit()
    conn.close()


def remaining_units_on_incident(incident_id: int) -> int:
    conn = get_conn()
    c = conn.cursor()

    row = c.execute("""
        SELECT COUNT(*) AS n
        FROM UnitAssignments
        WHERE incident_id=? AND cleared IS NULL
    """, (incident_id,)).fetchone()

    conn.close()
    return row["n"] if row else 0


def enter_disposition_stage_if_last(incident_id: int):
    if remaining_units_on_incident(incident_id) > 0:
        return

    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        UPDATE Incidents
        SET status='DISPOSITION_PENDING', updated=?
        WHERE incident_id=?
    """, (_ts(), incident_id))

    conn.commit()
    conn.close()


@app.post("/incident/{incident_id}/unit/{unit_id}/clear")
async def clear_unit_api(request: Request, incident_id: int, unit_id: str):

    data = await request.json()
    disposition = (data.get("disposition") or "").upper().strip()
    user = request.session.get("user", "Dispatcher")

    if disposition not in VALID_DISPOSITIONS_LEGACY_CLEAR:
        return {"ok": False, "error": "Invalid disposition code."}

    set_unit_disposition(incident_id, unit_id, disposition)
    mark_unit_cleared(incident_id, unit_id)
    set_unit_status_pipeline(unit_id, "AVAILABLE")

    add_narrative(
        incident_id,
        user,
        f"{unit_id} cleared — {disposition} ({VALID_DISPOSITIONS_LEGACY_CLEAR[disposition]})"
    )

    dailylog_event(
        "UNIT_CLEARED",
        f"{unit_id} cleared with disposition {disposition}",
        user=user,
        incident_id=incident_id,
        unit_id=unit_id
    )

    enter_disposition_stage_if_last(incident_id)

    return {
        "ok": True,
        "unit_id": unit_id,
        "disposition": disposition
    }
# ---------------------------------------------------------------
# CALLTAKER — EDIT EXISTING INCIDENT (IAW button target)
# ---------------------------------------------------------------
@app.get("/calltaker/edit/{incident_id}", response_class=HTMLResponse)
async def calltaker_edit(request: Request, incident_id: int):
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()

    row = c.execute("""
        SELECT *
        FROM Incidents
        WHERE incident_id = ?
    """, (incident_id,)).fetchone()

    conn.close()

    if not row:
        return HTMLResponse("Incident not found", status_code=404)

    return templates.TemplateResponse(
        "calltaker.html",
        {"request": request, "incident": dict(row)}
    )
# ---------------------------------------------------------------
# CALLTAKER — GET INCIDENT DATA FOR EDITING (JSON)
# ---------------------------------------------------------------
@app.get("/incident/{incident_id}/edit_data")
async def incident_edit_data(request: Request, incident_id: int):
    """Return incident data as JSON for populating the calltaker form."""
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()

    try:
        row = c.execute("""
            SELECT *
            FROM Incidents
            WHERE incident_id = ?
        """, (incident_id,)).fetchone()

        if not row:
            return {"ok": False, "error": "Incident not found"}

        # Convert row to dict
        data = dict(row) if hasattr(row, "keys") else {}

        # Parse created timestamp for date/time fields
        created = data.get("created") or ""
        date_str = ""
        time_str = ""
        if created:
            try:
                # Assuming format like "2026-01-28 14:30:00" or ISO format
                if "T" in created:
                    parts = created.split("T")
                    date_str = parts[0]
                    time_str = parts[1][:5] if len(parts) > 1 else ""
                elif " " in created:
                    parts = created.split(" ")
                    date_str = parts[0]
                    time_str = parts[1][:5] if len(parts) > 1 else ""
                else:
                    date_str = created[:10]
            except Exception:
                pass

        # Parse caller name into first/last
        caller_name = data.get("caller_name") or ""
        caller_first = ""
        caller_last = ""
        if caller_name:
            parts = caller_name.strip().split(" ", 1)
            caller_first = parts[0] if parts else ""
            caller_last = parts[1] if len(parts) > 1 else ""

        return {
            "ok": True,
            "incident_id": incident_id,
            "incident_number": data.get("incident_number") or "",
            "date": date_str,
            "time": time_str,
            "location": data.get("location") or "",
            "node": data.get("node") or "",
            "pole_alpha": data.get("pole_alpha") or data.get("pole") or "",
            "pole_alpha_dec": data.get("pole_alpha_dec") or "",
            "pole_number": data.get("pole_number") or "",
            "pole_number_dec": data.get("pole_number_dec") or "",
            "type": data.get("type") or "",
            "dailylog_subtype": data.get("dailylog_subtype") or "",
            "narrative": data.get("narrative") or "",
            "caller_first": caller_first,
            "caller_last": caller_last,
            "caller_phone": data.get("caller_phone") or "",
            "caller_location": data.get("address") or "",
            "status": data.get("status") or "",
        }
    finally:
        conn.close()


# ---------------------------------------------------------------
# ISSUE FOUND — MODAL (IAW button target)
# ---------------------------------------------------------------
@app.get("/incident/{incident_id}/issue", response_class=HTMLResponse)
async def issue_modal(request: Request, incident_id: int):
    ensure_phase3_schema()

    conn = get_conn()
    c = conn.cursor()

    row = c.execute("""
        SELECT *
        FROM Incidents
        WHERE incident_id = ?
    """, (incident_id,)).fetchone()

    conn.close()

    if not row:
        return HTMLResponse("Incident not found", status_code=404)

    # Template name varies across your snapshots. Use the first one that exists.
    for tpl in (
        "modals/issue_found_modal.html",
        "modals/issue_found.html",
        "modals/issue_modal.html",
        "issue_found_modal.html",
        "issue_modal.html",
    ):
        try:
            templates.env.get_template(tpl)
            return templates.TemplateResponse(
                tpl,
                {
                    "request": request,
                    "incident": dict(row),
                    "incident_id": int(incident_id),
                    "mode": "new",
                    "issue": None
                }
            )
        except Exception:
            continue

    # If none exist, return a clear 500 with the expected path list
    return HTMLResponse(
        "Issue modal template not found. Expected one of: "
        "modals/issue_found_modal.html, modals/issue_found.html, modals/issue_modal.html, "
        "issue_found_modal.html, issue_modal.html",
        status_code=500
    )


# ================================================================
# BLOCK 16 — EVENT DISPOSITION ENGINE (Phase-3 Canon)
# ================================================================

EVENT_OUTCOME_MAP = {
    # Canonical Fire/EMS Event Disposition Codes
    "FA": "False Alarm",
    "FF": "Fire Found",
    "MF": "Medical First Aid",
    "MT": "Medical Transport",
    "PR": "Patient Refusal",
    "NF": "No Finding",
    "C":  "Cancelled",
    "CT": "Cancelled Enroute",
    "O":  "Other",
    "H":  "Held",
    # Legacy codes (backward compatibility)
    "R":  "Refused",
    "NA": "No Action",
}


def write_event_disposition(incident_id: int, code: str, user: str, notes: str = ""):
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        INSERT INTO IncidentDispositions (
            incident_id, disposition, comment, timestamp
        )
        VALUES (?, ?, ?, ?)
    """, (incident_id, code, notes, _ts()))

    conn.commit()
    conn.close()


def close_incident_with_disposition(incident_id: int, code: str):
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        UPDATE Incidents
        SET status='CLOSED',
            final_disposition=?,
            updated=?
        WHERE incident_id=?
    """, (code, _ts(), incident_id))

    conn.commit()
    conn.close()


def log_event_disposition(incident_id: int, code: str, user: str, notes: str):
    detail = f"{code} — {notes or EVENT_OUTCOME_MAP.get(code, '')}"

    dailylog_event(
        "EVENT_DISPOSITION",
        detail,
        user=user,
        incident_id=incident_id,
        unit_id=None
    )


@app.post("/incident/{incident_id}/event_disposition")
async def event_disposition_submit(request: Request, incident_id: int):
    """
    Finalizes an incident with an official outcome.
    """
    try:
        data = await request.json()
    except Exception:
        data = {}

    code  = (data.get("code") or "").upper().strip()
    notes = (data.get("notes") or "").strip()
    user  = request.session.get("user", "Dispatcher")

    if code not in EVENT_OUTCOME_MAP:
        return {"ok": False, "error": "Invalid event disposition code."}

    write_event_disposition(incident_id, code, user, notes)

    text = f"Event disposition set to {code} ({EVENT_OUTCOME_MAP[code]})"
    if notes:
        text += f": {notes}"

    add_narrative(incident_id, user, text)
    log_event_disposition(incident_id, code, user, notes)
    close_incident_with_disposition(incident_id, code)

    return {"ok": True, "incident_id": incident_id, "closed": True}


@app.get(
    "/incident/{incident_id}/event_disposition_modal",
    response_class=HTMLResponse
)
async def event_disposition_modal(request: Request, incident_id: int):
    # Get incident info for the modal header
    incident = get_incident(incident_id) if incident_id else None
    return templates.TemplateResponse(
        "modals/event_disposition_modal.html",
        {
            "request": request,
            "incident_id": incident_id,
            "incident": incident,
            "outcomes": EVENT_OUTCOME_MAP
        }
    )

# ================================================================
# BLOCK 17 — ISSUE FOUND ENGINE (Phase-3 Canon)
# ================================================================

def ensure_issue_flag_column():
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("ALTER TABLE Incidents ADD COLUMN issue_flag INTEGER DEFAULT 0")
        conn.commit()
    except Exception:
        pass
    conn.close()


ensure_issue_flag_column()


def incident_is_dailylog(incident_id: int) -> bool:
    conn = get_conn()
    c = conn.cursor()

    row = c.execute("""
        SELECT type
        FROM Incidents
        WHERE incident_id=?
    """, (incident_id,)).fetchone()

    conn.close()

    return bool(row and (row["type"] or "").upper().strip() == "DAILY LOG")


def add_issue_daily(
    incident_id: int,
    category: str,
    description: str,
    resolution: str,
    followup_required: int,
    user: str
):
    ts = _ts()
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        INSERT INTO Issues (
            incident_id, timestamp, category,
            description, resolution,
            followup_required, reported_by
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        incident_id, ts, category,
        description, resolution,
        followup_required, user
    ))

    c.execute("""
        UPDATE Incidents
        SET issue_flag=1, updated=?
        WHERE incident_id=?
    """, (ts, incident_id))

    conn.commit()
    conn.close()

    add_narrative(
        incident_id=incident_id,
        user="SYSTEM",
        text=f"Issue Found — {category}: {description}",
        entry_type="ISSUE"
    )

    dailylog_event(
        "ISSUE_FOUND",
        f"{category}: {description}",
        user=user,
        incident_id=incident_id
    )


@app.post("/incident/{incident_id}/issue_found")
async def issue_found_submit(request: Request, incident_id: int):
    data = await request.json()

    category    = (data.get("category") or "Other").strip()
    description = (data.get("description") or "").strip()
    resolution  = (data.get("resolution") or "").strip()

    # accept either key
    followup = data.get("followup_required", data.get("followup", 0))
    try:
        followup = int(followup)
    except Exception:
        followup = 0

    user = request.session.get("user", "Dispatcher")

    if not description:
        return {"ok": False, "error": "Description required"}

    if not incident_is_dailylog(incident_id):
        reject_and_log(
            "ISSUE_FOUND_REJECTED",
            reason="Issue Found applies to Daily Log incidents only",
            user=user,
            incident_id=incident_id
        )
        return {"ok": False, "error": "Issue Found is allowed only for Daily Log incidents"}

    add_issue_daily(
        incident_id,
        category,
        description,
        resolution,
        followup,
        user
    )

    # Audit (explicit)
    details = f"{category}: {description}".strip()
    masterlog(event_type="ISSUE_FOUND", user=user, incident_id=incident_id, unit_id=None, details=details, ok=1, reason=None)
    incident_history(incident_id=incident_id, event_type="ISSUE_FOUND", user=user, unit_id=None, details=details)

    return {"ok": True, "incident_id": incident_id}

@app.post("/api/incident/{incident_id}/issue_found")
async def issue_found_submit_v2(request: Request, incident_id: int):
    """Canonical JSON alias."""
    return await issue_found_submit(request=request, incident_id=incident_id)



@app.get("/incident/{incident_id}/issues", response_class=HTMLResponse)
async def incident_issues_panel(request: Request, incident_id: int):

    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT timestamp, category, description,
               resolution, followup_required, reported_by
        FROM Issues
        WHERE incident_id=?
        ORDER BY timestamp ASC
    """, (incident_id,)).fetchall()

    conn.close()

    # Note: This template path may not exist
    return templates.TemplateResponse(
        "iaw/iaw_narrative_fragment.html",  # Using existing template as fallback
        {
            "request": request,
            "incident_id": incident_id,
            "issues": [dict(r) for r in rows]
        }
    )


@app.post("/legacy/incident/{incident_id}/dispatch_units__v3")
async def dispatch_units_handler(request: Request, incident_id: int):

    data = await request.json()
    units = data.get("units", [])
    user = request.session.get("user", "Dispatcher")

    if not units:
        return {"ok": False, "error": "No units selected."}

    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        UPDATE Incidents
        SET status='ACTIVE', updated=?
        WHERE incident_id=? AND status='OPEN'
    """, (_ts(), incident_id))

    conn.commit()
    conn.close()

    for uid in units:
        assign_unit_to_incident(incident_id, uid)
        set_unit_status_pipeline(uid, "ENROUTE")

    unit_list = ", ".join(units)
    incident_history(incident_id, "DISPATCH", user=user, details=f"Dispatched units: {unit_list}")
    masterlog("UNITS_DISPATCHED", user=user, incident_id=incident_id, details=f"Units: {unit_list}")

    return {"ok": True}


@app.post("/legacy/incident/{incident_id}/remark__v6")
async def iaw_remark(request: Request, incident_id: int):

    data = await request.json()
    remark = data.get("text", "").strip()
    user = request.session.get("user", "Dispatcher")

    if not remark:
        return {"ok": False, "error": "Empty remark not allowed."}

    add_narrative(incident_id, user, f"Remark — {remark}")

    return {"ok": True}


@app.post("/incident/{incident_id}/unit_clear/{unit_id}")
async def clear_unit(request: Request, incident_id: int, unit_id: str):
    """
    Clear a unit from an incident.

    CANON REQUIREMENT: Unit disposition is REQUIRED before clearing.
    If no disposition is provided, returns requires_disposition flag.
    Use /incident/{id}/unit/{unit_id}/disposition to set disposition first.
    """
    user = request.session.get("user", "Dispatcher")

    # Check if unit has a disposition set
    conn = get_conn()
    c = conn.cursor()

    row = c.execute("""
        SELECT disposition
        FROM UnitAssignments
        WHERE incident_id=? AND unit_id=? AND cleared IS NULL
    """, (incident_id, unit_id)).fetchone()
    conn.close()

    if not row:
        return {"ok": False, "error": "Unit not assigned to this incident or already cleared"}

    # Check if disposition is set
    disposition = row["disposition"] if row else None
    if not disposition or not str(disposition).strip():
        # Return flag indicating disposition is required
        return {
            "ok": False,
            "error": "Unit disposition required before clearing",
            "requires_disposition": True,
            "incident_id": incident_id,
            "unit_id": unit_id
        }

    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        UPDATE UnitAssignments
        SET cleared=?
        WHERE incident_id=? AND unit_id=?
    """, (_ts(), incident_id, unit_id))

    conn.commit()
    conn.close()

    set_unit_status_pipeline(unit_id, "AVAILABLE")

    disp_label = VALID_DISPOSITIONS_LEGACY_CLEAR.get(disposition, disposition)
    add_narrative(incident_id, user, f"Unit {unit_id} cleared — {disposition} ({disp_label})")

    # Check if this was the last unit
    conn = get_conn()
    c = conn.cursor()
    remaining = c.execute("""
        SELECT COUNT(*)
        FROM UnitAssignments
        WHERE incident_id=? AND cleared IS NULL
    """, (incident_id,)).fetchone()
    conn.close()

    if remaining[0] == 0:
        # Last unit cleared - require event disposition (DO NOT auto-close)
        return {
            "ok": True,
            "last_unit_cleared": True,
            "requires_event_disposition": True,
            "incident_id": incident_id
        }

    return {"ok": True}


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

    c = get_conn().cursor()
    c.execute("""
        INSERT INTO DailyLog (timestamp, action, details)
        VALUES (?, 'INCIDENT_CLOSED', ?)
    """, (_ts(), f"Incident {incident_id} closed"))
    c.connection.commit()
    c.connection.close()

# ================================================================
# BLOCK 19 — DISPOSITION VALIDATION
# ================================================================

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


def add_disposition_record(incident_id: int, user: str, code: str, notes: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO IncidentDispositions (incident_id, timestamp, disposition_code, notes, user)
        VALUES (?, ?, ?, ?, ?)
    """, (incident_id, _ts(), code, notes, user))
    conn.commit()
    conn.close()


@app.post("/legacy/incident/{incident_id}/disposition__v7")
async def incident_disposition(request: Request, incident_id: int):

    data = await request.json()
    code  = (data.get("code") or "").upper().strip()
    notes = (data.get("notes") or "").strip()
    user  = request.session.get("user", "Dispatcher")

    if not is_valid_disposition(code):
        return {"ok": False, "error": "Invalid disposition code."}

    conn = get_conn()
    c = conn.cursor()
    inc = c.execute("""
        SELECT status FROM Incidents WHERE incident_id=?
    """, (incident_id,)).fetchone()
    conn.close()

    if not inc:
        return {"ok": False, "error": "Incident does not exist."}

    status = inc["status"].upper()

    if status == "HELD":
        return {"ok": False, "error": "Cannot close a HELD incident."}

    if incident_has_active_units(incident_id):
        return {"ok": False, "error": "Units are still assigned — cannot close incident."}

    add_disposition_record(incident_id, user, code, notes)
    close_incident_with_disposition(incident_id, code, user)

    return {"ok": True}

# ================================================================
# BLOCK 20 — DAILY LOG VIEWER (CANONICAL / REBUILT)
# Paste this whole block in place of your current BLOCK 20 area.
# ================================================================

from fastapi import Body, Form

# ----------------------------------------------------------------
# SECTION 20.1 — SMALL HELPERS
# ----------------------------------------------------------------

def _int_or_none(v):
    try:
        if v is None:
            return None
        s = str(v).strip()
        if s == "":
            return None
        return int(s)
    except Exception:
        return None


def normalize_date(datestr: str) -> str:
    """
    Accepts: 12/07/2025 or 2025-12-07
    Returns: 2025-12-07 (ISO)
    """
    if not datestr:
        return datetime.datetime.now().strftime("%Y-%m-%d")

    datestr = str(datestr).strip()

    if "-" in datestr:
        return datestr

    try:
        m, d, y = datestr.split("/")
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    except Exception:
        return datetime.datetime.now().strftime("%Y-%m-%d")


def _dailylog_label_expr(alias: str = "dl") -> str:
    """
    SQL label used for filtering + display.

    • manual journal rows: action='DAILYLOG' -> label = event_type (or OTHER)
    • system/incident rows: label = action (or OTHER)
    """
    return f"""
        CASE
            WHEN UPPER({alias}.action) = 'DAILYLOG'
                THEN COALESCE(NULLIF({alias}.event_type, ''), 'OTHER')
            ELSE
                COALESCE(NULLIF({alias}.action, ''), 'OTHER')
        END
    """


# ----------------------------------------------------------------
# SECTION 20.2 — FEED QUERY (SHARED BY PANEL + API)
# ----------------------------------------------------------------

def fetch_daily_log_feed(
    *,
    date_iso: str | None = None,
    subtype: str | None = None,
    unit_id: str | None = None,
    incident_id: int | None = None,
    q: str | None = None,
    limit: int = 750
) -> list[dict]:
    """
    Daily Log Viewer feed.

    Canon:
      • Shows ALL rows in DailyLog (manual DAILYLOG + system/incident events).
      • Optional filters only (no default date gating).
    """
    ensure_phase3_schema()

    # Normalize
    date_iso = normalize_date(date_iso) if date_iso else None

    subtype = (subtype or "").strip()
    if subtype.upper() in ("", "ALL", "*"):
        subtype = ""

    unit_id = (unit_id or "").strip() or ""

    q = (q or "").strip() or ""

    try:
        limit = int(limit or 750)
    except Exception:
        limit = 750
    limit = max(50, min(limit, 2000))

    label_expr = _dailylog_label_expr("dl")

    where = ["1=1"]
    params: list = []

    if date_iso:
        where.append("substr(dl.timestamp, 1, 10) = ?")
        params.append(date_iso)

    if subtype:
        # subtype filter applies to the ONE visible label
        where.append(f"UPPER({label_expr}) = UPPER(?)")
        params.append(subtype)

    if unit_id:
        where.append("dl.unit_id = ?")
        params.append(unit_id)

    if incident_id is not None:
        where.append("dl.incident_id = ?")
        params.append(int(incident_id))

    if q:
        like = f"%{q}%"
        where.append(f"""
            (
                IFNULL(dl.details,'') LIKE ?
                OR IFNULL(dl.user,'') LIKE ?
                OR IFNULL(dl.unit_id,'') LIKE ?
                OR CAST(IFNULL(dl.incident_id,'') AS TEXT) LIKE ?
                OR {label_expr} LIKE ?
            )
        """)
        params.extend([like, like, like, like, like])

    sql = f"""
        SELECT
            dl.id AS log_id,
            dl.timestamp,
            dl.user,
            dl.incident_id,
            dl.unit_id,
            dl.action,
            dl.event_type,
            dl.details,
            {label_expr} AS label,
            i.incident_number,
            i.status AS incident_status
        FROM DailyLog dl
        LEFT JOIN Incidents i ON i.incident_id = dl.incident_id
        WHERE {' AND '.join(where)}
        ORDER BY dl.id DESC
        LIMIT ?
    """

    conn = get_conn()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    rows = c.execute(sql, tuple(params + [limit])).fetchall()
    conn.close()

    return [dict(r) for r in (rows or [])]

# ================================================================
# BLOCK 20 — DAILY LOG VIEWER (ROWS PARTIAL)
# Canon:
#   • ALWAYS show entries on open
#   • ONLY DailyLog journal entries (dl.action='DAILYLOG')
#   • Optional filters: subtype, unit_id, incident_id, keyword, limit
#   • Join Incidents for incident_number + status (Reopen button logic)
# ================================================================

@app.get("/panel/dailylog_rows", response_class=HTMLResponse)
async def panel_dailylog_rows(
    request: Request,
    subtype: str | None = None,
    unit_id: str | None = None,
    incident_id: str | None = None,
    q: str | None = None,
    limit: int | None = 750,
):
    ensure_phase3_schema()

    # ---------------------------
    # Normalize filters
    # ---------------------------
    subtype = (subtype or "").strip()
    if subtype.upper() in ("", "ALL", "*"):
        subtype = ""

    unit_id = (unit_id or "").strip()

    q = (q or "").strip()

    iid = None
    try:
        if incident_id is not None and str(incident_id).strip() != "":
            iid = int(str(incident_id).strip())
    except Exception:
        iid = None

    try:
        limit = int(limit or 750)
    except Exception:
        limit = 750
    limit = max(50, min(limit, 2000))

    # ---------------------------
    # SQL (ONLY DAILYLOG rows)
    # label = subtype (event_type) fallback OTHER
    # ---------------------------
    where = ["dl.action = 'DAILYLOG'"]
    params: list = []

    if subtype:
        where.append("UPPER(COALESCE(NULLIF(dl.event_type,''),'OTHER')) = UPPER(?)")
        params.append(subtype)

    if unit_id:
        where.append("dl.unit_id = ?")
        params.append(unit_id)

    if iid is not None:
        where.append("dl.incident_id = ?")
        params.append(iid)

    if q:
        like = f"%{q}%"
        where.append("""
            (
                IFNULL(dl.details,'') LIKE ?
                OR IFNULL(dl.user,'') LIKE ?
                OR IFNULL(dl.event_type,'') LIKE ?
                OR IFNULL(dl.unit_id,'') LIKE ?
                OR CAST(IFNULL(dl.incident_id,'') AS TEXT) LIKE ?
            )
        """)
        params.extend([like, like, like, like, like])

    sql = f"""
        SELECT
            dl.id AS log_id,
            dl.timestamp,
            dl.user,
            dl.incident_id,
            dl.unit_id,
            dl.action,
            dl.event_type,
            dl.details,
            COALESCE(NULLIF(dl.event_type,''),'OTHER') AS label,
            i.incident_number,
            i.status AS incident_status
        FROM DailyLog dl
        LEFT JOIN Incidents i ON i.incident_id = dl.incident_id
        WHERE {' AND '.join(where)}
        ORDER BY dl.id DESC
        LIMIT ?
    """

    conn = get_conn()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    rows = c.execute(sql, tuple(params + [limit])).fetchall()
    conn.close()

    return templates.TemplateResponse(
        "partials/dailylog_rows.html",
        {
            "request": request,
            "rows": [dict(r) for r in (rows or [])],
            "filters": {
                "subtype": subtype,
                "unit_id": unit_id,
                "incident_id": iid,
                "q": q,
                "limit": limit,
            },
        },
    )



# ----------------------------------------------------------------
# SECTION 20.5 — API: READ FEED (JSON)
# ----------------------------------------------------------------

@app.get("/api/dailylog")
async def api_dailylog(
    date: str | None = None,
    subtype: str | None = None,
    unit_id: str | None = None,
    incident_id: str | None = None,
    q: str | None = None,
    limit: int = 750,
):
    """
    JSON feed. Optional:
      • date (YYYY-MM-DD or MM/DD/YYYY) — if omitted, returns latest across all dates
      • subtype, unit_id, incident_id, q, limit
    """
    iid = _int_or_none(incident_id)
    date_iso = normalize_date(date) if date else None

    rows = fetch_daily_log_feed(
        date_iso=date_iso,
        subtype=subtype,
        unit_id=unit_id,
        incident_id=iid,
        q=q,
        limit=limit,
    )

    return {"ok": True, "date": date_iso, "entries": rows}


# ----------------------------------------------------------------
# SECTION 20.6 — WRITE: ONE CANONICAL ADD HELPER + ALL ENDPOINTS USE IT
# ----------------------------------------------------------------

def _dailylog_add_entry(
    *,
    request: Request | None,
    subtype: str | None,
    details: str | None,
    user: str | None,
    unit_id: str | None,
    incident_id,
    timestamp: str | None = None,
) -> tuple[bool, str | None]:
    """
    Writes ONE row into DailyLog as action='DAILYLOG'.
    Returns: (ok, error_message)
    """
    ensure_phase3_schema()

    details = (details or "").strip()
    if not details:
        return False, "Details required"

    # Session username wins
    sess_user = None
    if request is not None:
        try:
            sess_user = request.session.get("username") or request.session.get("user")
        except Exception:
            sess_user = None

    final_user = (sess_user or user or "CLI").strip()
    final_subtype = (subtype or "OTHER").strip()

    unit_id = (unit_id or "").strip() or None
    iid = _int_or_none(incident_id)

    ts = (timestamp or "").strip() or None

    try:
        ok = dailylog_event(
            action="DAILYLOG",
            event_type=final_subtype,
            details=details,
            user=final_user,
            incident_id=iid,
            unit_id=unit_id,
            timestamp=ts,
        )
        return bool(ok), None
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


@app.post("/api/dailylog/add")
async def api_dailylog_add(request: Request):
    """
    Canonical Daily Log add.
    Accepts JSON or Form.
    Emits HX-Trigger: dailylog-updated on success.
    """
    ctype = (request.headers.get("content-type") or "").lower()

    data = {}
    if ctype.startswith("application/json"):
        try:
            data = await request.json()
        except Exception:
            data = {}
    else:
        try:
            form = await request.form()
            data = dict(form)
        except Exception:
            data = {}

    ok, err = _dailylog_add_entry(
        request=request,
        subtype=(data.get("subtype") or data.get("event_type") or "OTHER"),
        details=data.get("details"),
        user=data.get("user"),
        unit_id=data.get("unit_id"),
        incident_id=data.get("incident_id"),
        timestamp=data.get("timestamp"),
    )

    if not ok:
        return JSONResponse({"ok": False, "error": err}, status_code=400)

    # HTMX contract
    if request.headers.get("HX-Request") == "true":
        resp = Response(content="", media_type="text/plain")
        resp.headers["HX-Trigger"] = "dailylog-updated"
        return resp

    resp = JSONResponse({"ok": True})
    resp.headers["HX-Trigger"] = "dailylog-updated"
    return resp


@app.post("/api/dailylog/add__legacy_json_v1")
async def api_dailylog_add__legacy_json_v1(request: Request, payload: dict = Body(...)):
    """
    Legacy JSON endpoint (kept for compatibility).
    """
    ok, err = _dailylog_add_entry(
        request=request,
        subtype=(payload.get("subtype") or payload.get("event_type") or "OTHER"),
        details=payload.get("details"),
        user=payload.get("user"),
        unit_id=payload.get("unit_id"),
        incident_id=payload.get("incident_id"),
        timestamp=payload.get("timestamp"),
    )
    if not ok:
        return {"ok": False, "error": err}
    return {"ok": True}


@app.post("/api/dailylog/add__legacy_json_v2")
async def api_dailylog_add__legacy_json_v2(request: Request):
    """
    Legacy JSON endpoint (kept for compatibility).
    """
    try:
        data = await request.json()
    except Exception:
        data = {}

    ok, err = _dailylog_add_entry(
        request=request,
        subtype=(data.get("subtype") or data.get("event_type") or "OTHER"),
        details=data.get("details"),
        user=data.get("user"),
        unit_id=data.get("unit_id"),
        incident_id=data.get("incident_id"),
        timestamp=data.get("timestamp"),
    )
    if not ok:
        return {"ok": False, "error": err}
    return {"ok": True}


@app.post("/api/dailylog/add__legacy_form_v1")
async def api_dailylog_add__legacy_form_v1(
    request: Request,
    subtype: str = Form(None),
    details: str = Form(None),
    user: str = Form(None),
    unit_id: str = Form(None),
    incident_id: str = Form(None),
):
    """
    Legacy form endpoint (kept for compatibility).
    Accepts HTMX form-posts; also accepts JSON if posted as application/json.
    Emits HX-Trigger: dailylog-updated on success.
    """
    # allow JSON too
    if (request.headers.get("content-type") or "").lower().startswith("application/json"):
        try:
            data = await request.json()
        except Exception:
            data = {}
        subtype = data.get("subtype") or data.get("event_type") or subtype
        details = data.get("details") or details
        user = data.get("user") or user
        unit_id = data.get("unit_id") or unit_id
        incident_id = data.get("incident_id") or incident_id

    ok, err = _dailylog_add_entry(
        request=request,
        subtype=subtype,
        details=details,
        user=user,
        unit_id=unit_id,
        incident_id=incident_id,
        timestamp=None,
    )

    if not ok:
        return {"ok": False, "error": err}

    resp = Response(content="", media_type="text/plain")
    resp.headers["HX-Trigger"] = "dailylog-updated"
    return resp


# ================================================================
# HELPER FUNCTION IMPLEMENTATIONS
# ================================================================

def incident_history(
    incident_id: int,
    event_type: str,
    user: str = "SYSTEM",
    unit_id: str | None = None,
    details: str = ""
):
    """
    Canonical incident history logger (Phase-3)
    """
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        INSERT INTO IncidentHistory (
            incident_id,
            timestamp,
            event_type,
            user,
            unit_id,
            details
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        incident_id,
        _ts(),
        event_type,
        user,
        unit_id,
        details
    ))

    conn.commit()
    conn.close()


def masterlog(
    event_type: str | None = None,
    user: str = "System",
    incident_id: int | None = None,
    details: str | None = None,
    unit_id: str | None = None,
    action: str | None = None,
    ok: int = 1,
    reason: str | None = None
):
    """
    Canonical MasterLog writer (compat).
      - Works with masterlog("EVENT")
      - Works with masterlog(event_type="EVENT")
      - Works with legacy masterlog(action="EVENT") without event_type
    """
    ensure_phase3_schema()
    MASTERLOG_WRITTEN.set(True)

    event = ((event_type or action) or "SYSTEM").strip() or "SYSTEM"
    ts = _ts()

    conn = get_conn()
    c = conn.cursor()

    cols = [row[1] for row in c.execute("PRAGMA table_info(MasterLog)").fetchall()]
    has = set(cols)

    insert_cols = ["timestamp", "user"]
    insert_vals = [ts, user]

    # action is NOT NULL in your schema
    if "action" in has:
        insert_cols.append("action")
        insert_vals.append(event)

    if "event_type" in has:
        insert_cols.append("event_type")
        insert_vals.append(event)

    if "incident_id" in has:
        insert_cols.append("incident_id")
        insert_vals.append(incident_id)

    if "unit_id" in has:
        insert_cols.append("unit_id")
        insert_vals.append(unit_id)

    if "ok" in has:
        insert_cols.append("ok")
        insert_vals.append(ok)

    if "reason" in has:
        insert_cols.append("reason")
        insert_vals.append(reason)

    if "details" in has:
        insert_cols.append("details")
        insert_vals.append(details)

    q_cols = ", ".join(insert_cols)
    q_q = ", ".join(["?"] * len(insert_cols))

    _sqlite_exec_retry(c, f"INSERT INTO MasterLog ({q_cols}) VALUES ({q_q})", insert_vals)


    conn.commit()
    conn.close()



def finalize_incident_if_clear(incident_id: int):
    """
    Finalizes incident only when no active unit assignments remain.
    """
    conn = get_conn()
    c = conn.cursor()

    active = c.execute("""
        SELECT 1
        FROM UnitAssignments
        WHERE incident_id = ?
          AND cleared IS NULL
    """, (incident_id,)).fetchone()

    if active:
        conn.close()
        return

    c.execute("""
        UPDATE Incidents
        SET status = 'CLOSED',
            updated = ?
        WHERE incident_id = ?
          AND status != 'CLOSED'
    """, (_ts(), incident_id))

    conn.commit()
    conn.close()

    incident_history(
        incident_id,
        "INCIDENT_CLOSED",
        details="Incident automatically closed (all units cleared)"
    )

    masterlog(
        "INCIDENT_CLOSED",
        incident_id=incident_id
    )

    dailylog_event(
        action="INCIDENT_CLOSED",
        details="Incident closed automatically",
        incident_id=incident_id
    )


def process_remark(user: str, text: str, unit_id: str = None, incident_id: int = None) -> dict:
    """
    Canon routing:
      1) If incident_id provided -> Narrative on that incident
      2) Else if unit_id provided AND unit has an uncleared assignment -> Narrative on that incident
      3) Else -> DailyLog row with action='REMARK' so it appears in the Event Log viewer

    NOTE:
      - Do NOT call dailylog_event(action='REMARK') because dailylog_event is hard-gated to action='DAILYLOG'.
      - This function must not return ok=True unless a write actually occurred.
    """
    text = (text or "").strip()
    unit_id = (unit_id or "").strip() or None

    # normalize incident_id (accept str digits)
    try:
        if isinstance(incident_id, str) and incident_id.isdigit():
            incident_id = int(incident_id)
    except Exception:
        pass

    if not text:
        return {"ok": False, "error": "Remark text required"}

    try:
        # 1) Explicit incident target
        if incident_id:
            add_narrative(
                incident_id=int(incident_id),
                user=user,
                text=text,
                entry_type="REMARK",
                unit_id=unit_id
            )
            return {"ok": True, "routed": "INCIDENT", "incident_id": int(incident_id), "unit_id": unit_id}

        # 2) Unit-only: if unit is currently assigned (uncleared), route to that incident
        if unit_id:
            inc = None
            try:
                inc = _active_incident_id_for_unit(unit_id)
            except Exception:
                inc = None

            if inc:
                add_narrative(
                    incident_id=int(inc),
                    user=user,
                    text=text,
                    entry_type="REMARK",
                    unit_id=unit_id
                )
                return {"ok": True, "routed": "INCIDENT", "incident_id": int(inc), "unit_id": unit_id}

            # 3) Unit not on an incident -> write to DailyLog as REMARK (viewer expects this)
            ensure_phase3_schema()
            ts = _ts()

            conn = get_conn()
            c = conn.cursor()

            # issue_found column exists in Phase-3, but guard just in case
            dl_cols = [r[1] for r in c.execute("PRAGMA table_info('DailyLog')").fetchall()]
            has_issue = "issue_found" in set(dl_cols)

            if has_issue:
                _sqlite_exec_retry(c, """
                    INSERT INTO DailyLog (timestamp, user, incident_id, unit_id, action, event_type, details, issue_found)
                    VALUES (?, ?, NULL, ?, 'REMARK', NULL, ?, 0)
                """, (ts, user, unit_id, text))
            else:
                _sqlite_exec_retry(c, """
                    INSERT INTO DailyLog (timestamp, user, incident_id, unit_id, action, event_type, details)
                    VALUES (?, ?, NULL, ?, 'REMARK', NULL, ?)
                """, (ts, user, unit_id, text))

            conn.commit()
            conn.close()

            # mirror to MasterLog for audit visibility
            try:
                masterlog(action="REMARK", user=user, incident_id=None, unit_id=unit_id, details=text)
            except Exception:
                pass

            return {"ok": True, "routed": "EVENTLOG", "unit_id": unit_id}

        # 4) No incident, no unit -> still write to DailyLog as REMARK
        ensure_phase3_schema()
        ts = _ts()
        conn = get_conn()
        c = conn.cursor()

        dl_cols = [r[1] for r in c.execute("PRAGMA table_info('DailyLog')").fetchall()]
        has_issue = "issue_found" in set(dl_cols)

        if has_issue:
            _sqlite_exec_retry(c, """
                INSERT INTO DailyLog (timestamp, user, incident_id, unit_id, action, event_type, details, issue_found)
                VALUES (?, ?, NULL, NULL, 'REMARK', NULL, ?, 0)
            """, (ts, user, text))
        else:
            _sqlite_exec_retry(c, """
                INSERT INTO DailyLog (timestamp, user, incident_id, unit_id, action, event_type, details)
                VALUES (?, ?, NULL, NULL, 'REMARK', NULL, ?)
            """, (ts, user, text))

        conn.commit()
        conn.close()

        try:
            masterlog(action="REMARK", user=user, incident_id=None, unit_id=None, details=text)
        except Exception:
            pass

        return {"ok": True, "routed": "EVENTLOG"}

    except Exception as e:
        return {"ok": False, "error": str(e)}

def get_narrative(incident_id: int) -> list[dict]:
    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT timestamp, entry_type, text, user, unit_id
        FROM Narrative
        WHERE incident_id = ?
        ORDER BY timestamp ASC
    """, (incident_id,)).fetchall()

    conn.close()
    return [dict(r) for r in rows]


async def update_unit_status_route(
    incident_id: int,
    unit_id: str,
    new_status: str
) -> dict:
    try:
        update_unit_status(unit_id, new_status)

        field_map = {
            "ENROUTE": "enroute",
            "ARRIVED": "arrived",
            "TRANSPORTING": "transporting",
            "CLEARED": "cleared"
        }

        if new_status in field_map:
            mark_assignment(incident_id, unit_id, field_map[new_status])

        incident_history(
            incident_id,
            new_status,
            user="SYSTEM",
            unit_id=unit_id
        )

        if new_status == "CLEARED":
            set_unit_status_pipeline(unit_id, "AVAILABLE")
            finalize_incident_if_clear(incident_id)

        return {"ok": True, "status": new_status}

    except Exception as e:
        return {"ok": False, "error": str(e)}


def perform_dispatch(incident_id: int, units: list[str]) -> dict:
    return dispatch_units_to_incident(
        incident_id=incident_id,
        units=units,
        user="Dispatcher"
    )


def get_incident_timeline(incident_id: int) -> list[dict]:
    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT timestamp, entry_type, text, user, unit_id
        FROM Narrative
        WHERE incident_id = ?
        ORDER BY timestamp ASC
    """, (incident_id,)).fetchall()

    conn.close()
    return [dict(r) for r in rows]
# ================================================================
# UAW INLINE API (NO MODAL) — REQUIRED ROUTES
# ================================================================

# Define only if missing (prevents duplicates if it exists elsewhere)
try:
    _active_incident_id_for_unit
except NameError:
    def _active_incident_id_for_unit(unit_id: str) -> int | None:
        ensure_phase3_schema()
        conn = get_conn()
        c = conn.cursor()
        row = c.execute("""
            SELECT ua.incident_id
            FROM UnitAssignments ua
            JOIN Incidents i ON i.incident_id = ua.incident_id
            WHERE ua.unit_id = ?
              AND ua.cleared IS NULL
              AND UPPER(COALESCE(i.status,'')) = 'ACTIVE'
            ORDER BY COALESCE(ua.arrived, ua.enroute, ua.dispatched, ua.assigned) DESC
            LIMIT 1
        """, (unit_id,)).fetchone()
        conn.close()
        return int(row[0]) if row else None


def _ua_has_column(c, table: str, col: str) -> bool:
    try:
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]
        return col in cols
    except Exception:
        return False


def _unit_is_command_on_incident_tx(c, incident_id: int, unit_id: str) -> bool:
    if not _ua_has_column(c, "UnitAssignments", "commanding_unit"):
        return False
    row = c.execute("""
        SELECT 1
        FROM UnitAssignments
        WHERE incident_id = ?
          AND unit_id = ?
          AND cleared IS NULL
          AND COALESCE(commanding_unit,0) = 1
        LIMIT 1
    """, (incident_id, unit_id)).fetchone()
    return bool(row)


def _assignment_has_disposition_tx(c, incident_id: int, unit_id: str) -> bool:
    if not _ua_has_column(c, "UnitAssignments", "disposition"):
        return False
    row = c.execute("""
        SELECT COALESCE(disposition,'') AS dispo
        FROM UnitAssignments
        WHERE incident_id = ?
          AND unit_id = ?
        LIMIT 1
    """, (incident_id, unit_id)).fetchone()
    if not row:
        return False
    return bool((row[0] or "").strip())


def _would_be_last_unit_tx(c, incident_id: int, unit_id: str) -> bool:
    row = c.execute("""
        SELECT COUNT(1)
        FROM UnitAssignments
        WHERE incident_id = ?
          AND cleared IS NULL
          AND unit_id <> ?
    """, (incident_id, unit_id)).fetchone()
    remaining_after = int(row[0]) if row else 0
    return remaining_after == 0


def _requires_disposition_for_clear_tx(c, incident_id: int, unit_id: str) -> bool:
    # Your rule: only command unit OR last clearing unit requires disposition.
    if _unit_is_command_on_incident_tx(c, incident_id, unit_id):
        return True
    if _would_be_last_unit_tx(c, incident_id, unit_id):
        return True
    return False

# ================================================================
# CLI (COMMAND LINE) — INCIDENT PICKER + DISPATCH
# ================================================================

def _cli_picker_lists():
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT
            incident_id,
            incident_number,
            status,
            COALESCE(type,'') AS type,
            COALESCE(location,'') AS location,
            COALESCE(updated,'') AS updated,
            COALESCE(issue_flag,0) AS issue_flag
        FROM Incidents
        WHERE is_draft = 0
          AND status IN ('OPEN','ACTIVE','HELD','CLOSED')
        ORDER BY
          CASE status
            WHEN 'OPEN' THEN 1
            WHEN 'ACTIVE' THEN 2
            WHEN 'HELD' THEN 3
            WHEN 'CLOSED' THEN 4
            ELSE 9
          END,
          updated DESC
    """).fetchall()

    conn.close()

    open_list, active_list, held_list, closed_list = [], [], [], []
    for r in rows:
        d = dict(r)
        st = (d.get("status") or "").upper().strip()
        if st == "OPEN":
            open_list.append(d)
        elif st == "ACTIVE":
            active_list.append(d)
        elif st == "HELD":
            held_list.append(d)
        elif st == "CLOSED":
            closed_list.append(d)

    return open_list, active_list, held_list, closed_list


@app.get("/api/incidents/dispatchable")
async def api_incidents_dispatchable():
    """Return open and active incidents for CLI dispatch selection."""
    open_list, active_list, held_list, _ = _cli_picker_lists()
    return {
        "open": open_list,
        "active": active_list,
        "held": held_list
    }


@app.get("/api/incident/{incident_id}/unit_count")
async def api_incident_unit_count(incident_id: int):
    """Return count of units still assigned (not cleared) to this incident."""
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()

    count = c.execute("""
        SELECT COUNT(*) FROM UnitAssignments
        WHERE incident_id = ? AND cleared IS NULL
    """, (incident_id,)).fetchone()[0]

    conn.close()
    return {"ok": True, "incident_id": incident_id, "count": count}


@app.post("/api/incident/{incident_id}/clear_all_and_close")
async def api_clear_all_and_close(incident_id: int, request: Request):
    """
    Clear all units with the given disposition, then close the incident.
    This is a convenience endpoint for the right-click "Close Incident" flow.
    """
    ensure_phase3_schema()

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    disposition = (payload.get("disposition") or "").strip()
    comment = (payload.get("comment") or "").strip()

    if not disposition:
        raise HTTPException(status_code=400, detail="Disposition required")

    user = request.session.get("user", "Dispatcher")

    conn = get_conn()
    c = conn.cursor()

    try:
        # Get all assigned units
        units = c.execute("""
            SELECT unit_id FROM UnitAssignments
            WHERE incident_id = ? AND cleared IS NULL
        """, (incident_id,)).fetchall()

        # Clear each unit with disposition
        import datetime as _dt
        now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for row in units:
            unit_id = row["unit_id"]
            # Set disposition and clear the unit
            c.execute("""
                UPDATE UnitAssignments
                SET disposition = ?, cleared = ?
                WHERE incident_id = ? AND unit_id = ? AND cleared IS NULL
            """, (disposition, now, incident_id, unit_id))

            # Set unit status to AVAILABLE
            c.execute("""
                UPDATE Units SET status = 'AVAILABLE', last_updated = ?
                WHERE unit_id = ?
            """, (now, unit_id))

            # Log history
            c.execute("""
                INSERT INTO IncidentHistory (incident_id, timestamp, event_type, user, unit_id, details)
                VALUES (?, ?, 'CLEARED', ?, ?, ?)
            """, (incident_id, now, user, unit_id, f"Disposition: {disposition}"))

        # Now close the incident
        # Check if final_disposition_note column exists
        inc_cols = [r[1] for r in c.execute("PRAGMA table_info(Incidents)").fetchall()]
        if "final_disposition_note" in inc_cols:
            c.execute("""
                UPDATE Incidents
                SET status = 'CLOSED', final_disposition = ?, final_disposition_note = ?, closed_at = ?
                WHERE incident_id = ?
            """, (disposition, comment, now, incident_id))
        else:
            c.execute("""
                UPDATE Incidents
                SET status = 'CLOSED', final_disposition = ?, closed_at = ?
                WHERE incident_id = ?
            """, (disposition, now, incident_id))

        # Log close event
        c.execute("""
            INSERT INTO IncidentHistory (incident_id, timestamp, event_type, user, details)
            VALUES (?, ?, 'CLOSED', ?, ?)
        """, (incident_id, now, user, f"Closed with disposition: {disposition}"))

        conn.commit()

    except Exception as e:
        conn.rollback()
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))

    conn.close()

    return {
        "ok": True,
        "incident_id": incident_id,
        "disposition": disposition,
        "units_cleared": len(units),
        "status": "CLOSED"
    }


@app.post("/api/admin/cleanup_stale_units")
async def api_cleanup_stale_units(request: Request):
    """
    Clear any stale unit assignments (units where the unit doesn't exist in Units table
    or units assigned to non-existent incidents).
    """
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()

    import datetime as _dt
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user = request.session.get("user", "System")

    cleaned = 0

    try:
        # Find unit assignments for units that don't exist in Units table
        c.execute("""
            SELECT ua.id, ua.incident_id, ua.unit_id FROM UnitAssignments ua
            LEFT JOIN Units u ON ua.unit_id = u.unit_id
            WHERE u.unit_id IS NULL AND ua.cleared IS NULL
        """)
        orphan_units = c.fetchall()

        for row in orphan_units:
            c.execute("UPDATE UnitAssignments SET cleared = ? WHERE id = ?", (now, row["id"]))
            cleaned += 1

        # Find unit assignments for incidents that don't exist
        c.execute("""
            SELECT ua.id, ua.incident_id, ua.unit_id FROM UnitAssignments ua
            LEFT JOIN Incidents i ON ua.incident_id = i.incident_id
            WHERE i.incident_id IS NULL AND ua.cleared IS NULL
        """)
        orphan_incidents = c.fetchall()

        for row in orphan_incidents:
            c.execute("UPDATE UnitAssignments SET cleared = ? WHERE id = ?", (now, row["id"]))
            cleaned += 1

        # Find unit assignments for closed incidents that weren't cleared
        c.execute("""
            SELECT ua.id, ua.incident_id, ua.unit_id FROM UnitAssignments ua
            JOIN Incidents i ON ua.incident_id = i.incident_id
            WHERE i.status = 'CLOSED' AND ua.cleared IS NULL
        """)
        closed_incident_units = c.fetchall()

        for row in closed_incident_units:
            c.execute("""
                UPDATE UnitAssignments SET cleared = ?, disposition = 'X'
                WHERE id = ?
            """, (now, row["id"]))
            # Also set unit to AVAILABLE if it exists
            c.execute("""
                UPDATE Units SET status = 'AVAILABLE', last_updated = ?
                WHERE unit_id = ?
            """, (now, row["unit_id"]))
            cleaned += 1

        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))

    conn.close()

    return {
        "ok": True,
        "cleaned": cleaned,
        "message": f"Cleaned {cleaned} stale unit assignment(s)"
    }


@app.get("/api/incident/{incident_id}/assignments")
async def api_incident_assignments(incident_id: int, request: Request):
    """View all unit assignments for an incident (for debugging)."""
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()

    assignments = c.execute("""
        SELECT ua.id, ua.unit_id, ua.assigned, ua.dispatched, ua.enroute,
               ua.arrived, ua.cleared, ua.disposition,
               u.status as unit_status, u.name as unit_name
        FROM UnitAssignments ua
        LEFT JOIN Units u ON ua.unit_id = u.unit_id
        WHERE ua.incident_id = ?
        ORDER BY ua.assigned DESC
    """, (incident_id,)).fetchall()

    conn.close()

    return {
        "ok": True,
        "incident_id": incident_id,
        "assignments": [dict(r) for r in assignments],
        "active_count": sum(1 for a in assignments if a["cleared"] is None)
    }


@app.post("/api/incident/{incident_id}/force_clear_units")
async def api_force_clear_units(incident_id: int, request: Request):
    """Force-clear all unit assignments for an incident (admin only)."""
    ensure_phase3_schema()

    user = request.session.get("user", "Dispatcher")
    if not _is_admin(user):
        return JSONResponse(status_code=403, content={"ok": False, "error": "Admin only"})

    conn = get_conn()
    c = conn.cursor()

    import datetime as _dt
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Get active assignments before clearing
    active = c.execute("""
        SELECT unit_id FROM UnitAssignments
        WHERE incident_id = ? AND cleared IS NULL
    """, (incident_id,)).fetchall()

    cleared_units = [r["unit_id"] for r in active]

    # Force clear all assignments
    c.execute("""
        UPDATE UnitAssignments
        SET cleared = ?, disposition = COALESCE(disposition, 'X')
        WHERE incident_id = ? AND cleared IS NULL
    """, (now, incident_id))

    # Reset unit statuses to AVAILABLE
    for unit_id in cleared_units:
        c.execute("""
            UPDATE Units SET status = 'AVAILABLE', last_updated = ?
            WHERE unit_id = ?
        """, (now, unit_id))

    conn.commit()
    conn.close()

    masterlog(
        action="ADMIN_FORCE_CLEAR_UNITS",
        user=user,
        incident_id=incident_id,
        details=f"Force-cleared {len(cleared_units)} units: {', '.join(cleared_units)}"
    )

    return {
        "ok": True,
        "incident_id": incident_id,
        "cleared_count": len(cleared_units),
        "cleared_units": cleared_units
    }


@app.get("/api/cli/incident_picker", response_class=HTMLResponse)
async def cli_incident_picker(request: Request):
    units_csv = (request.query_params.get("units") or "").strip()
    mode = (request.query_params.get("mode") or "D").strip().upper()

    open_list, active_list, held_list, closed_list = _cli_picker_lists()

    return templates.TemplateResponse(
        "modals/cli_incident_picker.html",
        {
            "request": request,
            "units_csv": units_csv,
            "mode": mode,
            "open_incidents": open_list,
            "active_incidents": active_list,
            "held_incidents": held_list,
            "closed_incidents": closed_list,
        }
    )


def _resolve_incident_ref_tx(c, ref: str):
    ref = (ref or "").strip()
    if not ref:
        return None
    if ref.isdigit():
        return int(ref)

    row = c.execute("""
        SELECT incident_id
        FROM Incidents
        WHERE incident_number = ?
        LIMIT 1
    """, (ref,)).fetchone()
    return int(row["incident_id"]) if row else None


@app.get("/api/incident/resolve/{ref}")
async def api_incident_resolve(ref: str):
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()
    incident_id = _resolve_incident_ref_tx(c, ref)
    conn.close()
    if not incident_id:
        return {"ok": False, "error": "Incident not found"}
    return {"ok": True, "incident_id": incident_id}


@app.post("/api/cli/dispatch")
async def api_cli_dispatch(request: Request):
    ensure_phase3_schema()
    data = await request.json()

    units = data.get("units") or []
    if isinstance(units, str):
        units = [u.strip() for u in units.split(",") if u.strip()]
    units = [str(u).strip() for u in units if str(u).strip()]

    mode = (data.get("mode") or "D").strip().upper()

    incident_id = data.get("incident_id")
    incident_ref = (data.get("incident_ref") or data.get("incident_number") or "").strip()

    conn = get_conn()
    c = conn.cursor()

    if not incident_id:
        incident_id = _resolve_incident_ref_tx(c, incident_ref)

    if not incident_id:
        conn.close()
        return {"ok": False, "error": "No incident selected"}

    # Reopen if closed (CLI can dispatch to closed incidents)
    row = c.execute("SELECT status FROM Incidents WHERE incident_id=?", (incident_id,)).fetchone()
    if not row:
        conn.close()
        return {"ok": False, "error": "Incident not found"}

    if (row["status"] or "").upper().strip() == "CLOSED":
        c.execute("""
            UPDATE Incidents
            SET status='OPEN',
                closed_at=NULL,
                final_disposition=NULL,
                cancel_reason=NULL,
                updated=?
            WHERE incident_id=?
        """, (_ts(), incident_id))
        conn.commit()

    conn.close()

    # Dispatch
    res = dispatch_units_to_incident(int(incident_id), units, user="CLI")

    # If the dispatch failed (or dispatched nothing), propagate failure to the UI.
    if not isinstance(res, dict) or not res.get("ok"):
        err = res.get("error") if isinstance(res, dict) else "Dispatch failed"
        return {"ok": False, "incident_id": int(incident_id), "error": err or "Dispatch failed", "result": res}

    # DE = dispatch + enroute
    if mode == "DE" and res and res.get("ok"):
        assigned = res.get("assigned") or []
        for uid in assigned:
            # timestamp UA + set unit status (also promotes incident to ACTIVE if needed)
            mark_assignment(int(incident_id), uid, "enroute")
            update_unit_status(uid, "ENROUTE")

    return {"ok": True, "incident_id": int(incident_id), "result": res}


@app.get("/api/uaw/context/{unit_id}")
async def uaw_context(unit_id: str):
    ensure_phase3_schema()
    active_incident_id = _active_incident_id_for_unit(unit_id)

    conn = get_conn()
    c = conn.cursor()
    row = c.execute("""
        SELECT unit_id,
               status,
               COALESCE(custom_status,'') AS custom_status,
               COALESCE(is_apparatus,0)   AS is_apparatus
        FROM Units
        WHERE unit_id = ?
    """, (unit_id,)).fetchone()
    conn.close()

    is_apparatus = bool(row and int(row["is_apparatus"] or 0) == 1)
    parent_apparatus_id = None
    crew = []

    try:
        if is_apparatus:
            crew = get_apparatus_crew_details(unit_id)
        else:
            parent_apparatus_id = get_personnel_parent_apparatus(unit_id)
    except Exception:
        pass

    return {
        "ok": True,
        "unit_id": unit_id,
        "active_incident_id": active_incident_id,
        "is_apparatus": is_apparatus,
        "parent_apparatus_id": parent_apparatus_id,
        "crew": crew,
        "status": (row["status"] if row else None),
        "custom_status": (row["custom_status"] if row else "")
    }



@app.get("/api/uaw/dispatch_targets")
async def uaw_dispatch_targets():
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT incident_id,
               COALESCE(incident_number,'') AS incident_number,
               COALESCE(type,'') AS type,
               COALESCE(location,'') AS location,
               status
        FROM Incidents
        WHERE status IN ('OPEN','ACTIVE')
          AND COALESCE(is_draft,0) = 0
        ORDER BY updated DESC
        LIMIT 50
    """).fetchall()

    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/uaw/misc/{unit_id}")
async def uaw_misc_status(request: Request, unit_id: str):
    ensure_phase3_schema()
    data = await request.json()
    text = (data.get("text") or "").strip()

    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        UPDATE Units
        SET custom_status = ?, last_updated = ?
        WHERE unit_id = ?
    """, (text, _ts(), unit_id))
    conn.commit()
    conn.close()

    masterlog(event_type="UNIT_MISC_STATUS", unit_id=unit_id, details=(text or "CLEARED"))
    dailylog_event(action="UNIT_MISC_STATUS", unit_id=unit_id, details=(text or "CLEARED"))

    return {"ok": True}


@app.get("/api/uaw/scene_units/{incident_id}")
async def uaw_scene_units(incident_id: int):
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT ua.unit_id
        FROM UnitAssignments ua
        WHERE ua.incident_id = ?
          AND ua.cleared IS NULL
        ORDER BY COALESCE(ua.arrived, ua.enroute, ua.dispatched, ua.assigned) DESC
    """, (incident_id,)).fetchall()

    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/uaw/transfer_command")
async def uaw_transfer_command(request: Request):
    ensure_phase3_schema()
    data = await request.json()
    incident_id = int(data.get("incident_id") or 0)
    unit_id = (data.get("unit_id") or "").strip()
    if not incident_id or not unit_id:
        return {"ok": False, "error": "incident_id and unit_id required"}

    user = request.session.get("user", "Dispatcher")

    conn = get_conn()
    c = conn.cursor()

    # Clear existing command flag on active assignments
    if _ua_has_column(c, "UnitAssignments", "commanding_unit"):
        c.execute("""
            UPDATE UnitAssignments
            SET commanding_unit = 0
            WHERE incident_id = ?
              AND cleared IS NULL
        """, (incident_id,))

        # Set new command flag
        c.execute("""
            UPDATE UnitAssignments
            SET commanding_unit = 1
            WHERE incident_id = ?
              AND unit_id = ?
              AND cleared IS NULL
        """, (incident_id, unit_id))

    conn.commit()
    conn.close()

    incident_history(incident_id, "TRANSFER_COMMAND", user=user, unit_id=unit_id, details="Command transferred")
    masterlog(event_type="TRANSFER_COMMAND", incident_id=incident_id, unit_id=unit_id)
    dailylog_event(action="TRANSFER_COMMAND", incident_id=incident_id, unit_id=unit_id, details=f"Command → {unit_id}")

    return {"ok": True}


@app.post("/api/uaw/clear_unit")
async def uaw_clear_unit(request: Request):
    """
    Clears one unit. Enforces your disposition rule:
      - command unit requires disposition before clearing
      - last clearing unit requires disposition before clearing
      - all other clears do NOT require disposition

    If disposition is provided in request, it will be saved before clearing.
    """
    ensure_phase3_schema()
    data = await request.json()
    incident_id = int(data.get("incident_id") or 0)
    unit_id = (data.get("unit_id") or "").strip()
    disposition = (data.get("disposition") or "").strip()
    comment = (data.get("comment") or data.get("remark") or "").strip()

    if not incident_id or not unit_id:
        return {"ok": False, "error": "incident_id and unit_id required"}

    user = request.session.get("user", "Dispatcher")

    conn = get_conn()
    c = conn.cursor()

    # Check if this unit requires disposition
    requires = _requires_disposition_for_clear_tx(c, incident_id, unit_id)

    # If disposition is provided, save it first
    if disposition:
        try:
            c.execute("""
                UPDATE UnitAssignments
                SET disposition = ?, disposition_note = ?
                WHERE incident_id = ? AND unit_id = ?
            """, (disposition, comment, incident_id, unit_id))
            conn.commit()
        except Exception as e:
            # Column might not exist, try without note
            try:
                c.execute("""
                    UPDATE UnitAssignments
                    SET disposition = ?
                    WHERE incident_id = ? AND unit_id = ?
                """, (disposition, incident_id, unit_id))
                conn.commit()
            except Exception:
                pass

    # Re-check disposition requirement after potentially saving one
    if requires and not disposition and not _assignment_has_disposition_tx(c, incident_id, unit_id):
        conn.close()
        return {
            "ok": False,
            "requires_disposition": True,
            "error": "Disposition required for command unit or last clearing unit."
        }

    conn.close()

    # Proceed with clear
    mark_assignment(incident_id, unit_id, "cleared")
    set_unit_status_pipeline(unit_id, "AVAILABLE")
    incident_history(incident_id, "CLEARED", user=user, unit_id=unit_id, detail=f"Disposition: {disposition}" if disposition else None)

    # If you have finalize logic, keep it
    try:
        finalize_incident_if_clear(incident_id)
    except Exception:
        pass

    return {"ok": True, "requires_disposition": False, "disposition": disposition}


@app.post("/api/uaw/clear_all")
async def uaw_clear_all(request: Request):
    """
    Clears all units on an incident.
    Enforces your disposition rule by requiring the CURRENT command unit (if any) to have disposition.
    """
    ensure_phase3_schema()
    data = await request.json()
    incident_id = int(data.get("incident_id") or 0)
    if not incident_id:
        return {"ok": False, "error": "incident_id required"}

    user = request.session.get("user", "Dispatcher")

    conn = get_conn()
    c = conn.cursor()

    # Identify command unit if schema supports it
    cmd_unit = None
    if _ua_has_column(c, "UnitAssignments", "commanding_unit"):
        row = c.execute("""
            SELECT unit_id
            FROM UnitAssignments
            WHERE incident_id = ?
              AND cleared IS NULL
              AND COALESCE(commanding_unit,0) = 1
            LIMIT 1
        """, (incident_id,)).fetchone()
        cmd_unit = (row[0] if row else None)

    # Pull all active units
    unit_rows = c.execute("""
        SELECT unit_id
        FROM UnitAssignments
        WHERE incident_id = ?
          AND cleared IS NULL
    """, (incident_id,)).fetchall()

    # Enforce: command unit must have disposition before clear-all
    if cmd_unit:
        if not _assignment_has_disposition_tx(c, incident_id, cmd_unit):
            conn.close()
            return {
                "ok": False,
                "requires_disposition": True,
                "error": f"Disposition required for command unit ({cmd_unit}) before Clear All."
            }

    conn.close()

    # Clear all
    for r in unit_rows:
        uid = r["unit_id"]
        mark_assignment(incident_id, uid, "cleared")
        set_unit_status_pipeline(uid, "AVAILABLE")

    incident_history(incident_id, "CLEAR_ALL", user=user, details="All units cleared")

    try:
        finalize_incident_if_clear(incident_id)
    except Exception:
        pass

    return {"ok": True, "requires_disposition": False}

# ================================================================
# PANEL DATA LOADERS (FILTERED — DRAFT SAFE)
# ================================================================

def panel_active():
    """
    Fetch active incidents + their currently assigned units (tree rows).

    Canon (your rule):
      • ACTIVE panel shows ONLY incidents that have >= 1 uncleared unit assignment.
      • If an incident is status ACTIVE but has 0 uncleared units, it should not appear here.
    """
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()

    # Detect cleared column name for UnitAssignments
    ua_cols = {r["name"] for r in c.execute("PRAGMA table_info(UnitAssignments)").fetchall()}
    if "cleared_at" in ua_cols:
        cleared_expr = "(ua.cleared_at IS NULL OR ua.cleared_at = '')"
        cleared_expr_plain = "(cleared_at IS NULL OR cleared_at = '')"
    elif "cleared" in ua_cols:
        cleared_expr = "(ua.cleared IS NULL OR ua.cleared = '')"
        cleared_expr_plain = "(cleared IS NULL OR cleared = '')"
    else:
        # Defensive: if we can't tell, do NOT treat anything as safely "no units"
        cleared_expr = "1=1"
        cleared_expr_plain = "1=1"

    # Only show ACTIVE incidents that still have an uncleared assignment
    inc_rows = c.execute(f"""
        SELECT i.*
        FROM Incidents i
        WHERE i.status = 'ACTIVE'
          AND i.is_draft = 0
          AND EXISTS (
              SELECT 1
              FROM UnitAssignments ua
              WHERE ua.incident_id = i.incident_id
                AND {cleared_expr}
          )
        ORDER BY i.updated DESC
    """).fetchall()

    incidents = [dict(r) for r in (inc_rows or [])]

    # Normalize issue flag and add age for templates
    for i in incidents:
        i["issue_flag"] = int(i.get("issue_flag") or i.get("issue_found") or 0)
        i["age"] = _format_age(i.get("updated") or i.get("created"))
        i["unit_count"] = 0  # Will be updated below

    if not incidents:
        conn.close()
        return []

    ids = [i["incident_id"] for i in incidents if i.get("incident_id") is not None]
    if not ids:
        conn.close()
        return []

    ph = ",".join(["?"] * len(ids))

    # commanding_unit may not exist in older DBs
    ua_cols2 = [r["name"] for r in c.execute("PRAGMA table_info(UnitAssignments)").fetchall()]
    has_cmd_col = "commanding_unit" in ua_cols2

    cmd_select = "COALESCE(ua.commanding_unit,0) AS commanding_unit" if has_cmd_col else "0 AS commanding_unit"
    cmd_order  = "COALESCE(ua.commanding_unit,0) DESC," if has_cmd_col else ""

    ua_rows = c.execute(f"""
        SELECT
            ua.incident_id,
            ua.unit_id,
            {cmd_select},

            ua.assigned,
            ua.dispatched,
            ua.enroute,
            ua.arrived,
            ua.transporting,
            ua.at_medical,
            ua.cleared,

            COALESCE(u.is_apparatus,0) AS is_apparatus,
            COALESCE(u.is_command,0) AS is_command,
            COALESCE(u.is_mutual_aid,0) AS is_mutual_aid,
            COALESCE(u.custom_status,'') AS custom_status,
            COALESCE(u.icon,'unknown.png') AS icon,

            COALESCE(u.status,'') AS unit_status
        FROM UnitAssignments ua
        LEFT JOIN Units u ON u.unit_id = ua.unit_id
        WHERE ua.incident_id IN ({ph})
          AND {cleared_expr_plain}
        ORDER BY
            ua.incident_id,
            {cmd_order}
            COALESCE(u.is_apparatus,0) DESC,
            ua.unit_id ASC
    """, ids).fetchall()

    conn.close()

    by_inc = {i["incident_id"]: [] for i in incidents}

    def _status_for(a: dict) -> str:
        if a.get("at_medical"):
            return "AT_MEDICAL"
        if a.get("transporting"):
            return "TRANSPORTING"
        if a.get("arrived"):
            return "ARRIVED"
        if a.get("enroute"):
            return "ENROUTE"
        if a.get("dispatched"):
            return "DISPATCHED"
        return (a.get("unit_status") or "").upper().strip()

    for r in (ua_rows or []):
        d = dict(r)
        d["display_status"] = _status_for(d)
        by_inc[d["incident_id"]].append(d)

    for i in incidents:
        units = by_inc.get(i["incident_id"], [])
        i["assigned_units"] = units
        i["unit_count"] = len(units)

    return incidents





def panel_open():
    """
    Fetch open incidents.

    Canon (your rule):
      • OPEN panel shows status OPEN
      • PLUS incidents that are status ACTIVE but currently have 0 uncleared assignments
        (i.e., units cleared and disposition not yet completed, so they should not float).
    """
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()

    ua_cols = {r["name"] for r in c.execute("PRAGMA table_info(UnitAssignments)").fetchall()}
    if "cleared_at" in ua_cols:
        cleared_expr = "(ua.cleared_at IS NULL OR ua.cleared_at = '')"
    elif "cleared" in ua_cols:
        cleared_expr = "(ua.cleared IS NULL OR ua.cleared = '')"
    else:
        cleared_expr = "1=1"

    rows = c.execute(f"""
        SELECT i.*
        FROM Incidents i
        WHERE i.is_draft = 0
          AND (
              i.status = 'OPEN'
              OR (
                  i.status = 'ACTIVE'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM UnitAssignments ua
                      WHERE ua.incident_id = i.incident_id
                        AND {cleared_expr}
                  )
              )
          )
        ORDER BY i.created DESC
    """).fetchall()

    incidents = []
    for r in (rows or []):
        d = dict(r)
        d["issue_flag"] = int(d.get("issue_flag") or d.get("issue_found") or 0)
        d["age"] = _format_age(d.get("created") or d.get("updated"))
        incidents.append(d)

    conn.close()
    return incidents


def panel_held():
    """
    Fetch held incidents.
    Draft-held incidents are excluded.
    """
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT *
        FROM Incidents
        WHERE status = 'HELD'
          AND is_draft = 0
        ORDER BY updated DESC
    """).fetchall()

    conn.close()

    incidents = []
    for r in (rows or []):
        d = dict(r)
        d["issue_flag"] = int(d.get("issue_flag") or d.get("issue_found") or 0)
        d["age"] = _format_age(d.get("created") or d.get("updated"))
        incidents.append(d)

    return incidents



# ------------------------------------------------------
# HELD COUNT — DATA HELPER
# ------------------------------------------------------

def get_held_count() -> int:
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()

    row = c.execute("""
        SELECT COUNT(*) AS n
        FROM Incidents
        WHERE status = 'HELD'
          AND is_draft = 0
    """).fetchone()

    conn.close()
    return row["n"] if row else 0


# ------------------------------------------------------
# HELD COUNT — API ROUTE (UI POLLING)
# ------------------------------------------------------

@app.get("/held_count", response_class=JSONResponse)
def api_held_count():
    return {"count": get_held_count()}



# ================================================================
# INCIDENT NUMBER ALLOCATION (CANONICAL)
# ================================================================

def _current_year() -> int:
    return int(datetime.datetime.now().strftime("%Y"))


def _format_incident_number(year: int, seq: int) -> str:
    return f"{year}-{seq:05d}"


def allocate_incident_number(conn) -> tuple[str, int, int]:
    """
    Allocates the next incident number for the current year.
    Must be called inside an active transaction.
    """
    year = _current_year()
    c = conn.cursor()

    row = c.execute("""
        SELECT next_seq
        FROM IncidentCounter
        WHERE year = ?
    """, (year,)).fetchone()

    if not row:
        seq = 1
        c.execute("""
            INSERT INTO IncidentCounter (year, next_seq)
            VALUES (?, ?)
        """, (year, 2))
    else:
        seq = int(row["next_seq"])
        c.execute("""
            UPDATE IncidentCounter
            SET next_seq = ?
            WHERE year = ?
        """, (seq + 1, year))

    return _format_incident_number(year, seq), year, seq


# ================================================================
# PANEL ENDPOINTS — PHASE-3 CANONICAL
# ================================================================

@app.get("/panel/calltaker", response_class=HTMLResponse)
async def panel_calltaker(request: Request):
    return templates.TemplateResponse(
        "calltaker.html",
        {"request": request},
    )


def _crew_id_map_for_shift(shift_key: str | None) -> dict[str, list[str]]:
    """
    Returns {apparatus_id: [personnel_id,...]} for the given shift key (A/B).
    Backward compatible: rows with shift NULL/'' are treated as global.
    """
    ensure_phase3_schema()
    sk = (shift_key or "").strip().upper()

    conn = get_conn()
    c = conn.cursor()
    try:
        if sk in ("A", "B"):
            rows = c.execute(
                """
                SELECT apparatus_id, personnel_id
                FROM PersonnelAssignments
                WHERE COALESCE(NULLIF(TRIM(shift), ''), ?) IN (?, ?)
                """,
                (sk, sk, sk),
            ).fetchall()
        else:
            rows = c.execute(
                """
                SELECT apparatus_id, personnel_id
                FROM PersonnelAssignments
                """
            ).fetchall()

        crew_map: dict[str, list[str]] = {}
        for r in (rows or []):
            app_id = (r["apparatus_id"] or "").strip()
            per_id = (r["personnel_id"] or "").strip()
            if not app_id or not per_id:
                continue
            crew_map.setdefault(app_id, []).append(per_id)
        return crew_map
    finally:
        conn.close()


def _build_units_panel_context(request: Request) -> dict:
    """
    Units panel context builder.

    Rules:
      • Shift context controls PERSONNEL visibility (unless roster_view_mode = ALL).
      • Battalion chiefs are shift-scoped (letter-first).
      • 1578 + Car1 always visible.
      • Apparatus + mutual aid always visible.
      • "ALL" is visibility-only (does not rewrite roster).
      • Units with active shift coverage get has_coverage=True flag.
    """
    roster_view_mode = get_session_roster_view_mode(request) or "CURRENT"
    login_required = not session_is_initialized(request)

    if login_required:
        return {
            "login_required": True,
            "units": [],
            "crew_map": {},
            "shift_letter": "",
            "shift_effective": "",
            "roster_view_mode": roster_view_mode,
        }

    shift_letter = get_session_shift_letter(request) or ""
    shift_effective = get_session_shift_effective(request) or ""

    ensure_phase3_schema()
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM Units").fetchall()

        # Get units with active shift coverage for current shift
        coverage_rows = conn.execute(
            """
            SELECT unit_id
            FROM ShiftOverrides
            WHERE end_ts IS NULL
              AND to_shift_letter = ?
            """,
            (shift_effective,)
        ).fetchall()
        units_with_coverage = {r["unit_id"] for r in coverage_rows}

        # Get units currently dispatched to active incidents (hide from units panel)
        dispatched_rows = conn.execute(
            """
            SELECT DISTINCT ua.unit_id
            FROM UnitAssignments ua
            JOIN Incidents i ON i.incident_id = ua.incident_id
            WHERE ua.cleared IS NULL
              AND i.status NOT IN ('CLOSED', 'CANCELLED', 'DISPOSED')
            """
        ).fetchall()
        dispatched_unit_ids = {r["unit_id"] for r in dispatched_rows}
    finally:
        conn.close()

    # Command visibility (Batt chiefs shift-scoped, 1578/Car1 always)
    visible_command = visible_command_unit_ids(shift_letter, shift_effective)

    # Personnel visibility
    if roster_view_mode == "ALL":
        visible_personnel = roster_personnel_ids_all_shifts()
    else:
        visible_personnel = get_active_personnel_ids_for_request(request)

    # Crew map is stored by EFFECTIVE shift (A/B)
    crew_map = _crew_id_map_for_shift(shift_effective)

    units_out = []
    for u in (rows or []):
        uid = (u["unit_id"] or "").strip()

        # Skip units currently dispatched to active incidents
        if uid in dispatched_unit_ids:
            continue

        is_personnel = uid.isdigit() and len(uid) == 2
        is_apparatus = int((u["is_apparatus"] or 0) or 0) == 1
        is_mutual = int((u["is_mutual_aid"] or 0) or 0) == 1

        # Convert row to dict and add coverage flag
        unit_dict = dict(u)
        unit_dict["has_coverage"] = uid in units_with_coverage

        # Apparatus + mutual aid always visible
        if is_apparatus or is_mutual:
            units_out.append(unit_dict)
            continue

        # Command: only allowed set
        if uid in visible_command:
            units_out.append(unit_dict)
            continue

        # Personnel: roster-filtered unless ALL mode
        if is_personnel:
            if roster_view_mode == "ALL" or uid in visible_personnel:
                units_out.append(unit_dict)
            continue

        # Other units: only show in ALL mode
        if roster_view_mode == "ALL":
            units_out.append(unit_dict)

    return {
        "login_required": False,
        "units": units_out,
        "crew_map": crew_map,
        "shift_letter": shift_letter,
        "shift_effective": shift_effective,
        "roster_view_mode": roster_view_mode,
    }




@app.get("/panel/units", response_class=HTMLResponse)
async def panel_units_display(request: Request):
    """
    Units panel is shift-scoped.
    Pre-login: show "Login Required" prompt.
    Post-login: show the roster world for the selected shift.
    """
    ctx = _build_units_panel_context(request)
    return templates.TemplateResponse(
        "units.html",
        {
            "request": request,
            "units": ctx["units"],
            "crew_map": ctx["crew_map"],
            "login_required": ctx["login_required"],
            "shift_letter": ctx["shift_letter"],
            "shift_effective": ctx["shift_effective"],
            "roster_view_mode": ctx["roster_view_mode"],
        },
    )




@app.get("/panel/active", response_class=HTMLResponse)
async def panel_active_display(request: Request):
    ensure_phase3_schema()
    return templates.TemplateResponse(
        "active_incidents.html",
        {
            "request": request,
            "incidents": panel_active() or [],
        },
    )


@app.get("/panel/open", response_class=HTMLResponse)
async def panel_open_display(request: Request):
    ensure_phase3_schema()
    return templates.TemplateResponse(
        "open_incidents.html",
        {
            "request": request,
            "incidents": panel_open() or [],
        },
    )


@app.get("/panel/held", response_class=HTMLResponse)
async def panel_held_display(request: Request):
    ensure_phase3_schema()
    return templates.TemplateResponse(
        "held_incidents.html",
        {
            "request": request,
            "incidents": panel_held() or [],
        },
    )


@app.get("/modals/held", response_class=HTMLResponse)
async def modals_held(request: Request):
    """Held calls viewer (modal)."""
    ensure_phase3_schema()
    return templates.TemplateResponse("held_incidents.html", {"request": request, "incidents": panel_held() or []})


# ------------------------------------------------------
# INCIDENT HOLD / UNHOLD (PHASE-3 CANONICAL)
# ------------------------------------------------------

@app.get("/api/held_count", response_class=JSONResponse)
def api_held_count(request: Request):
    """Return count of HELD incidents (for toolbar badge)."""
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()
    row = c.execute("SELECT COUNT(1) AS n FROM Incidents WHERE status='HELD'").fetchone()
    conn.close()
    n = int(row['n'] if row and 'n' in row.keys() else (row[0] if row else 0))
    return {"ok": True, "count": n}
# ---------------------------------------------------------------------------
# MODAL — Daily Log Viewer (Phase-3 contract)
# Toolbar opens: /modals/dailylog
# ---------------------------------------------------------------------------
@app.get("/modals/dailylog", response_class=HTMLResponse)
async def dailylog_modal(request: Request):
    today = datetime.datetime.now()
    return templates.TemplateResponse(
        "modals/dailylog_modal.html",
        {
            "request": request,
            "subtypes": DAILYLOG_SUBTYPES,
            "default_from": "",  # No default = show all recent entries (running timeline)
            "default_to": "",    # Filters are available but not pre-set
        },
    )


@app.get("/modals/shift_coverage", response_class=HTMLResponse)
async def shift_coverage_modal(request: Request):
    """Modal for adding temporary shift coverage (shift overrides)."""
    ensure_phase3_schema()

    # Get active overrides for current shift
    shift_letter = get_session_shift_letter(request) or ""
    active_overrides = []

    conn = get_conn()
    c = conn.cursor()
    try:
        rows = c.execute(
            """
            SELECT unit_id, from_shift_letter, to_shift_letter, reason, start_ts
            FROM ShiftOverrides
            WHERE end_ts IS NULL
              AND to_shift_letter = ?
            ORDER BY start_ts DESC
            """,
            (shift_letter,),
        ).fetchall()

        for r in rows:
            active_overrides.append({
                "unit_id": r["unit_id"] if hasattr(r, "keys") else r[0],
                "from_shift_letter": r["from_shift_letter"] if hasattr(r, "keys") else r[1],
                "to_shift_letter": r["to_shift_letter"] if hasattr(r, "keys") else r[2],
                "reason": r["reason"] if hasattr(r, "keys") else r[3],
                "start_ts": r["start_ts"] if hasattr(r, "keys") else r[4],
            })
    finally:
        conn.close()

    return templates.TemplateResponse(
        "modals/shift_coverage_modal.html",
        {
            "request": request,
            "shift_letter": shift_letter,
            "active_overrides": active_overrides,
        },
    )


@app.get("/modals/calendar", response_class=HTMLResponse)
async def calendar_modal(request: Request):
    """Calendar modal for scheduling and shift management."""
    import datetime
    today = datetime.date.today()
    return templates.TemplateResponse(
        "modals/calendar_modal.html",
        {
            "request": request,
            "current_month": today.strftime("%B %Y"),
            "today": today.isoformat(),
        },
    )


@app.get("/modals/reports", response_class=HTMLResponse)
async def reports_modal(request: Request):
    """Reports modal for generating dispatch reports."""
    return templates.TemplateResponse(
        "modals/reports_modal.html",
        {"request": request},
    )


@app.get("/modals/roster", response_class=HTMLResponse)
async def roster_modal(request: Request):
    """Roster management modal."""
    return templates.TemplateResponse(
        "modals/roster_modal.html",
        {"request": request},
    )


@app.get("/modals/contacts", response_class=HTMLResponse)
async def contacts_modal(request: Request):
    """Contacts directory modal."""
    return templates.TemplateResponse(
        "modals/contacts_modal.html",
        {"request": request},
    )


# ============================================================================
# EVENT LOG API — Consolidated (Phase-3 Canon)
# Shows: DAILYLOG + REMARK entries with issue_found support
# ============================================================================

@app.get("/panel/eventlog_rows", response_class=HTMLResponse)
async def panel_eventlog_rows(
    request: Request,
    from_date: str | None = None,
    to_date: str | None = None,
    category: str | None = None,
    unit_id: str | None = None,
    q: str | None = None,
    issues_only: str | None = None,
    limit: int = 500,
):
    """
    Return HTML rows for the Event Log Viewer.
    Shows DAILYLOG and REMARK entries from DailyLog table.
    """
    ensure_phase3_schema()

    # Normalize filters
    category = (category or "").strip().upper()
    unit_id = (unit_id or "").strip()
    q = (q or "").strip()
    issues_only = (issues_only or "").strip() == "1"

    # Build WHERE clause - show DAILYLOG and REMARK entries
    where = ["(dl.action = 'DAILYLOG' OR dl.action = 'REMARK')"]
    params: list = []

    # Date range filter
    if from_date:
        where.append("DATE(dl.timestamp) >= DATE(?)")
        params.append(from_date)
    if to_date:
        where.append("DATE(dl.timestamp) <= DATE(?)")
        params.append(to_date)

    # Category filter
    if category:
        if category == "REMARK":
            where.append("dl.action = 'REMARK'")
        else:
            where.append("dl.action = 'DAILYLOG' AND UPPER(COALESCE(dl.event_type, 'OTHER')) = ?")
            params.append(category)

    # Unit filter
    if unit_id:
        where.append("dl.unit_id = ?")
        params.append(unit_id)

    # Search filter
    if q:
        like = f"%{q}%"
        where.append("(dl.details LIKE ? OR dl.user LIKE ? OR dl.unit_id LIKE ?)")
        params.extend([like, like, like])

    # Issues only filter
    if issues_only:
        where.append("dl.issue_found = 1")

    # Limit
    limit = max(50, min(int(limit or 500), 2000))

    sql = f"""
        SELECT
            dl.id,
            dl.timestamp,
            dl.user,
            dl.incident_id,
            dl.unit_id,
            dl.action,
            dl.event_type,
            dl.details,
            dl.issue_found,
            CASE 
                WHEN dl.action = 'REMARK' THEN 'REMARK'
                ELSE COALESCE(NULLIF(dl.event_type, ''), 'OTHER')
            END AS category,
            i.incident_number,
            i.status AS incident_status
        FROM DailyLog dl
        LEFT JOIN Incidents i ON i.incident_id = dl.incident_id
        WHERE {' AND '.join(where)}
        ORDER BY dl.id DESC
        LIMIT ?
    """

    conn = get_conn()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, tuple(params + [limit])).fetchall()
    conn.close()

    return templates.TemplateResponse(
        "partials/eventlog_rows.html",
        {"request": request, "rows": [dict(r) for r in (rows or [])]},
    )


@app.post("/api/eventlog/add")
async def api_eventlog_add(request: Request):
    """
    Add a new event log entry (DAILYLOG or REMARK).
    Supports issue_found flag.
    """
    ensure_phase3_schema()

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)

    subtype = (data.get("subtype") or "OTHER").strip().upper()
    details = (data.get("details") or "").strip()
    unit_id = (data.get("unit_id") or "").strip() or None
    incident_id = _int_or_none(data.get("incident_id"))
    issue_found = 1 if data.get("issue_found") else 0
    user = (data.get("user") or "Dispatcher").strip()

    # Note: Details are OPTIONAL for Daily Log entries (per FORD-CAD canon)
    # The category (subtype) provides context even without narrative text
    # if not details:
    #     return JSONResponse({"ok": False, "error": "Details required"}, status_code=400)

    # Determine action based on category
    action = "REMARK" if subtype == "REMARK" else "DAILYLOG"
    event_type = None if action == "REMARK" else subtype

    ts = _ts()
    conn = get_conn()
    c = conn.cursor()

    try:
        c.execute("""
            INSERT INTO DailyLog (timestamp, user, incident_id, unit_id, action, event_type, details, issue_found)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (ts, user, incident_id, unit_id, action, event_type, details, issue_found))
        conn.commit()
    except Exception as e:
        conn.close()
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    conn.close()

    # Also add to MasterLog for audit
    try:
        masterlog(action=action, user=user, incident_id=incident_id, unit_id=unit_id, details=details)
    except Exception:
        pass

    return JSONResponse({"ok": True})


@app.post("/api/eventlog/{log_id}/toggle_issue")
async def api_eventlog_toggle_issue(log_id: int, request: Request):
    """Toggle the issue_found flag on an event log entry."""
    ensure_phase3_schema()

    try:
        data = await request.json()
    except Exception:
        data = {}

    new_value = 1 if data.get("issue_found") else 0

    conn = get_conn()
    c = conn.cursor()

    try:
        c.execute("UPDATE DailyLog SET issue_found = ? WHERE id = ?", (new_value, log_id))
        conn.commit()
    except Exception as e:
        conn.close()
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    conn.close()
    return JSONResponse({"ok": True, "issue_found": new_value})


# ---------------------------------------------------------------------------
# EVENT LOG EXPORTS (Phase-3)
# ---------------------------------------------------------------------------
def _eventlog_fetch_rows(
    from_date: str | None = None,
    to_date: str | None = None,
    category: str | None = None,
    unit_id: str | None = None,
    q: str | None = None,
    issues_only: str | None = None,
    limit: int = 2000,
):
    """Return filtered DailyLog rows for export."""
    ensure_phase3_schema()

    try:
        limit = int(limit)
    except Exception:
        limit = 2000
    limit = max(1, min(limit, 5000))

    issues_flag = 1 if str(issues_only or "").strip() in {"1", "true", "True", "yes", "YES", "on"} else 0

    conn = get_conn()
    c = conn.cursor()

    query = """
        SELECT
            d.id,
            d.timestamp,
            COALESCE(d.event_type, d.action) as category,
            d.unit_id,
            i.incident_number,
            d.incident_id,
            d.details,
            d.user,
            d.issue_found
        FROM DailyLog d
        LEFT JOIN Incidents i ON i.incident_id = d.incident_id
        WHERE 1=1
    """
    params: list = []

    if from_date:
        query += " AND DATE(d.timestamp) >= ?"
        params.append(from_date)
    if to_date:
        query += " AND DATE(d.timestamp) <= ?"
        params.append(to_date)

    if category and category != "All":
        query += " AND COALESCE(d.event_type, d.action) = ?"
        params.append(category)

    if unit_id:
        query += " AND d.unit_id = ?"
        params.append(unit_id)

    if q:
        query += " AND d.details LIKE ?"
        params.append(f"%{q}%")

    if issues_flag:
        query += " AND d.issue_found = 1"

    query += " ORDER BY d.timestamp DESC LIMIT ?"
    params.append(limit)

    rows = c.execute(query, params).fetchall()
    conn.close()
    return rows


@app.get("/api/eventlog/export", response_class=JSONResponse)
def api_eventlog_export(
    request: Request,
    from_date: str | None = None,
    to_date: str | None = None,
    category: str | None = None,
    unit_id: str | None = None,
    q: str | None = None,
    issues_only: str | None = None,
    limit: int = 120,
):
    """Export event log rows as JSON (used by mailto summary)."""
    rows = _eventlog_fetch_rows(from_date, to_date, category, unit_id, q, issues_only, limit)
    return JSONResponse({"ok": True, "rows": [dict(r) for r in rows], "truncated": len(rows) >= max(1, int(limit))})


@app.get("/api/eventlog/export_pdf")
def api_eventlog_export_pdf(
    request: Request,
    from_date: str | None = None,
    to_date: str | None = None,
    category: str | None = None,
    unit_id: str | None = None,
    q: str | None = None,
    issues_only: str | None = None,
    limit: int = 2000,
):
    """Export event log rows as a downloadable PDF (no popups required)."""
    rows = _eventlog_fetch_rows(from_date, to_date, category, unit_id, q, issues_only, limit)

    try:
        from io import BytesIO
        from datetime import datetime

        from reportlab.lib.pagesizes import letter, landscape
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    except Exception:
        raise HTTPException(status_code=501, detail="PDF export requires the 'reportlab' package. Install: pip install reportlab")

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(letter),
        leftMargin=18,
        rightMargin=18,
        topMargin=18,
        bottomMargin=18,
        title="FORD-CAD Event Log Export",
    )

    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("FORD-CAD Event Log", styles["Title"]))

    meta_parts = [
        f"From: {from_date or '(any)'}",
        f"To: {to_date or '(any)'}",
        f"Category: {category or 'All'}",
        f"Unit: {unit_id or 'Any'}",
        f"Issues Only: {'Yes' if str(issues_only or '').strip() else 'No'}",
        f"Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    story.append(Paragraph(" &nbsp;&nbsp; ".join(meta_parts), styles["Normal"]))
    story.append(Spacer(1, 10))

    # Table
    data = [["Timestamp", "Category", "Unit", "Incident", "Details", "By", "Issue"]]

    for r in rows:
        ts = (r["timestamp"] or "")
        cat = (r["category"] or "")
        unit = (r["unit_id"] or "")
        inc = (r["incident_number"] or r["incident_id"] or "")
        details = (r["details"] or "")
        user = (r["user"] or "")
        issue = "⚠" if r["issue_found"] else ""

        # Keep PDF readable; Paragraph enables wrapping
        data.append([
            ts,
            cat,
            unit,
            str(inc),
            Paragraph(details.replace("\n", "<br/>") or "&nbsp;", styles["BodyText"]),
            user,
            issue,
        ])

    table = Table(
        data,
        repeatRows=1,
        colWidths=[105, 90, 45, 60, 420, 70, 30],
    )

    table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E9EEF6")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("ALIGN", (0, 0), (-1, 0), "LEFT"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#AAB3BF")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F9FC")]),
        ])
    )

    story.append(table)
    doc.build(story)

    pdf_bytes = buf.getvalue()
    buf.close()

    safe_from = (from_date or "any").replace("/", "-")
    safe_to = (to_date or "any").replace("/", "-")
    filename = f"FORDCAD_EventLog_{safe_from}_to_{safe_to}.pdf"

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"'
    }

    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)

@app.post("/incident/{incident_id}/hold")
async def api_hold_incident(incident_id: int, request: Request):
    """Hold an incident (requires free-text reason). Persists held_reason for audit."""
    ensure_phase3_schema()

    data = {}
    try:
        data = await request.json()
    except Exception:
        data = {}

    reason = (data.get("reason") or data.get("held_reason") or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Hold reason required")

    user = request.session.get("user", "Dispatcher")
    ts = _ts()

    conn = get_conn()
    c = conn.cursor()

    # Update (no incident_number restriction)
    _sqlite_exec_retry(c, """
        UPDATE Incidents
        SET status='HELD',
            held_reason=?,
            held_at=?,
            held_by=?,
            updated=?
        WHERE incident_id=?
          AND status NOT IN ('CLOSED')
    """, (reason, ts, user, ts, incident_id))

    conn.commit()
    conn.close()

    # Audit
    masterlog(event_type="HELD", user=user, incident_id=incident_id, details=reason, unit_id=None, ok=1, reason=reason)
    incident_history(incident_id=incident_id, event_type="HELD", user=user, unit_id=None, details=reason)

    return {"ok": True}

@app.post("/api/incident/{incident_id}/hold")
async def api_hold_incident_v2(incident_id: int, request: Request):
    """Canonical JSON alias."""
    return await api_hold_incident(incident_id=incident_id, request=request)


@app.post("/incident/{incident_id}/unhold")
async def api_unhold_incident(incident_id: int, request: Request):
    """Unhold an incident. Restores to OPEN. held_reason remains for audit."""
    ensure_phase3_schema()

    user = request.session.get("user", "Dispatcher")
    ts = _ts()

    conn = get_conn()
    c = conn.cursor()

    # Pull reason for audit detail (do not clear)
    row = c.execute("SELECT held_reason FROM Incidents WHERE incident_id=?", (incident_id,)).fetchone()
    prior_reason = (row["held_reason"] if row and row["held_reason"] else "").strip()

    _sqlite_exec_retry(c, """
        UPDATE Incidents
        SET status='OPEN',
            held_released_at=?,
            held_released_by=?,
            updated=?
        WHERE incident_id=?
          AND status='HELD'
    """, (ts, user, ts, incident_id))

    conn.commit()
    conn.close()

    details = ("Released" + (f" | prior reason: {prior_reason}" if prior_reason else ""))

    masterlog(event_type="UNHOLD", user=user, incident_id=incident_id, details=details, unit_id=None, ok=1, reason=None)
    incident_history(incident_id=incident_id, event_type="UNHOLD", user=user, unit_id=None, details=details)

    return {"ok": True}

@app.post("/api/incident/{incident_id}/unhold")
async def api_unhold_incident_v2(incident_id: int, request: Request):
    """Canonical JSON alias."""
    return await api_unhold_incident(incident_id=incident_id, request=request)



# ======================================================
# ADMIN — DRAFT & RUN NUMBER CONTROL (PHASE 3D)
# ======================================================

from fastapi import Body
from fastapi.responses import JSONResponse
from fastapi import HTTPException

# ------------------------------------------------------
# ADMIN IDENTITY (PHASE-3 SIMPLE MODEL)
# ------------------------------------------------------

ADMIN_UNITS = {"1578", "CAR1", "BATT1", "BATT2", "BATT3", "BATT4", "17", "47"}

def _is_admin(user: str) -> bool:
    return (user or "").upper() in ADMIN_UNITS


# ------------------------------------------------------
# ADMIN — RUN NUMBER VIEW
# ------------------------------------------------------

@app.get("/admin/run_numbers", response_class=JSONResponse)
def admin_run_numbers(user: str = "DISPATCH"):
    ensure_phase3_schema()

    if not _is_admin(user):
        return JSONResponse(status_code=403, content={"ok": False, "error": "Admin only"})

    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT year, next_seq
        FROM IncidentCounter
        ORDER BY year DESC
    """).fetchall()

    conn.close()
    return {"ok": True, "counters": [dict(r) for r in rows]}


# ------------------------------------------------------
# ADMIN — RUN NUMBER SET (SAFE)
# ------------------------------------------------------

@app.post("/admin/run_numbers/set_next", response_class=JSONResponse)
def admin_set_next(
    year: int = Body(...),
    next_seq: int = Body(...),
    user: str = "DISPATCH"
):
    ensure_phase3_schema()

    if not _is_admin(user):
        return JSONResponse(status_code=403, content={"ok": False, "error": "Admin only"})

    conn = get_conn()
    c = conn.cursor()

    # Guard: do not allow changes if incidents already exist for this year
    row = c.execute("""
        SELECT COUNT(*) AS n
        FROM Incidents
        WHERE incident_number LIKE ?
    """, (f"{year}-%",)).fetchone()

    if int(row["n"]) > 0:
        conn.close()
        return {
            "ok": False,
            "error": "Cannot change counter: issued incidents already exist for this year."
        }

    c.execute("""
        INSERT INTO IncidentCounter (year, next_seq)
        VALUES (?, ?)
        ON CONFLICT(year)
        DO UPDATE SET next_seq = excluded.next_seq
    """, (year, int(next_seq)))

    conn.commit()
    conn.close()

    masterlog(
        action="ADMIN_SET_RUN_COUNTER",
        user=user,
        details=f"year={year} next_seq={next_seq}"
    )

    return {"ok": True}


# ------------------------------------------------------
# ADMIN — LIST DRAFT INCIDENTS
# ------------------------------------------------------

@app.get("/admin/drafts", response_class=JSONResponse)
def admin_list_drafts(user: str = "DISPATCH"):
    ensure_phase3_schema()

    if not _is_admin(user):
        return JSONResponse(status_code=403, content={"ok": False, "error": "Admin only"})

    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT incident_id, created, type, address, status
        FROM Incidents
        WHERE incident_number IS NULL
        ORDER BY created ASC
    """).fetchall()

    conn.close()
    return {"ok": True, "drafts": [dict(r) for r in rows]}


# ------------------------------------------------------
# ADMIN — DELETE DRAFT INCIDENT
# ------------------------------------------------------

@app.post("/admin/draft/delete/{incident_id}", response_class=JSONResponse)
def admin_delete_draft(
    incident_id: int,
    user: str = "DISPATCH"
):
    ensure_phase3_schema()

    if not _is_admin(user):
        return JSONResponse(status_code=403, content={"ok": False, "error": "Admin only"})

    conn = get_conn()
    c = conn.cursor()

    # Safety check — must be a draft
    row = c.execute("""
        SELECT incident_number
        FROM Incidents
        WHERE incident_id = ?
    """, (incident_id,)).fetchone()

    if not row:
        conn.close()
        return {"ok": False, "error": "Incident not found"}

    if row["incident_number"] is not None:
        conn.close()
        return {"ok": False, "error": "Not a draft incident"}

    c.execute("""
        DELETE FROM Incidents
        WHERE incident_id = ?
    """, (incident_id,))

    conn.commit()
    conn.close()

    masterlog(
        action="ADMIN_DELETE_DRAFT",
        user=user,
        incident_id=incident_id,
        details="Draft incident deleted"
    )

    return {"ok": True}

# ------------------------------------------------------
# ADMIN — DRAFT CLEANUP PAGE (HTML)
# ------------------------------------------------------

@app.get("/admin/drafts_page", response_class=HTMLResponse)
def admin_drafts_page(request: Request, user: str = "DISPATCH"):
    ensure_phase3_schema()

    if not _is_admin(user):
        return HTMLResponse("Admin only", status_code=403)

    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT incident_id, created, type, address, status
        FROM Incidents
        WHERE incident_number IS NULL
        ORDER BY created ASC
    """).fetchall()

    conn.close()

    return templates.TemplateResponse(
        "admin_drafts.html",
        {
            "request": request,
            "drafts": [dict(r) for r in rows],
            "user": user
        }
    )


# ================================================================
# ADMIN — SYSTEM MANAGEMENT SECTION
# ================================================================

ARCHIVES_DIR = BASE_DIR / "static" / "archives"


def _archive_to_csv(filename: str, headers: list, rows: list) -> str:
    """Archive data to a CSV file in static/archives/. Returns the file path."""
    import csv
    ARCHIVES_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    filepath = ARCHIVES_DIR / f"{filename}_{ts}.csv"
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)
    return str(filepath)


# ------------------------------------------------------
# ADMIN — SYSTEM STATISTICS
# ------------------------------------------------------

@app.get("/admin/stats", response_class=JSONResponse)
def admin_stats(user: str = "DISPATCH"):
    """Get comprehensive system statistics."""
    ensure_phase3_schema()

    if not _is_admin(user):
        return JSONResponse(status_code=403, content={"ok": False, "error": "Admin only"})

    conn = get_conn()
    c = conn.cursor()

    # Incident counts
    total_incidents = c.execute("SELECT COUNT(*) FROM Incidents WHERE incident_number IS NOT NULL").fetchone()[0]
    open_incidents = c.execute("SELECT COUNT(*) FROM Incidents WHERE status = 'OPEN' AND incident_number IS NOT NULL").fetchone()[0]
    closed_incidents = c.execute("SELECT COUNT(*) FROM Incidents WHERE status = 'CLOSED' AND incident_number IS NOT NULL").fetchone()[0]
    draft_incidents = c.execute("SELECT COUNT(*) FROM Incidents WHERE incident_number IS NULL").fetchone()[0]

    # Current year run number
    current_year = datetime.datetime.now().year
    counter_row = c.execute("SELECT next_seq FROM IncidentCounter WHERE year = ?", (current_year,)).fetchone()
    next_seq = counter_row[0] if counter_row else 1
    current_run_number = f"{current_year}-{next_seq:05d}"

    # Unit counts
    total_units = c.execute("SELECT COUNT(*) FROM Units").fetchone()[0]
    available_units = c.execute("SELECT COUNT(*) FROM Units WHERE status = 'AVAILABLE'").fetchone()[0]

    # Log entry counts
    masterlog_entries = c.execute("SELECT COUNT(*) FROM MasterLog").fetchone()[0]
    dailylog_entries = c.execute("SELECT COUNT(*) FROM DailyLog").fetchone()[0]

    # Last incident
    last_incident_row = c.execute("""
        SELECT incident_number, created
        FROM Incidents
        WHERE incident_number IS NOT NULL
        ORDER BY created DESC
        LIMIT 1
    """).fetchone()
    last_incident = dict(last_incident_row) if last_incident_row else None

    # Incident counts by year
    yearly_counts = c.execute("""
        SELECT substr(incident_number, 1, 4) as year, COUNT(*) as count
        FROM Incidents
        WHERE incident_number IS NOT NULL
        GROUP BY substr(incident_number, 1, 4)
        ORDER BY year DESC
    """).fetchall()

    conn.close()

    return {
        "ok": True,
        "stats": {
            "total_incidents": total_incidents,
            "open_incidents": open_incidents,
            "closed_incidents": closed_incidents,
            "draft_incidents": draft_incidents,
            "current_run_number": current_run_number,
            "next_seq": next_seq,
            "current_year": current_year,
            "total_units": total_units,
            "available_units": available_units,
            "masterlog_entries": masterlog_entries,
            "dailylog_entries": dailylog_entries,
            "last_incident": last_incident,
            "yearly_counts": [dict(r) for r in yearly_counts]
        }
    }


# ------------------------------------------------------
# ADMIN — EXPORT INCIDENTS TO CSV
# ------------------------------------------------------

@app.get("/admin/export/incidents", response_class=JSONResponse)
def admin_export_incidents(user: str = "DISPATCH"):
    """Export all incidents to CSV and return the file path."""
    ensure_phase3_schema()

    if not _is_admin(user):
        return JSONResponse(status_code=403, content={"ok": False, "error": "Admin only"})

    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT incident_id, incident_number, run_number, status, type, location, address,
               priority, caller_name, caller_phone, narrative, created, updated, closed_at,
               final_disposition, cancel_reason
        FROM Incidents
        WHERE incident_number IS NOT NULL
        ORDER BY created DESC
    """).fetchall()

    headers = ["incident_id", "incident_number", "run_number", "status", "type", "location",
               "address", "priority", "caller_name", "caller_phone", "narrative", "created",
               "updated", "closed_at", "final_disposition", "cancel_reason"]

    filepath = _archive_to_csv("incidents", headers, [tuple(r) for r in rows])
    conn.close()

    masterlog(
        action="ADMIN_EXPORT_INCIDENTS",
        user=user,
        details=f"Exported {len(rows)} incidents to {filepath}"
    )

    return {"ok": True, "file": filepath, "count": len(rows)}


# ------------------------------------------------------
# ADMIN — EXPORT LOGS TO CSV
# ------------------------------------------------------

@app.get("/admin/export/logs", response_class=JSONResponse)
def admin_export_logs(user: str = "DISPATCH", log_type: str = "masterlog"):
    """Export MasterLog or DailyLog to CSV."""
    ensure_phase3_schema()

    if not _is_admin(user):
        return JSONResponse(status_code=403, content={"ok": False, "error": "Admin only"})

    conn = get_conn()
    c = conn.cursor()

    if log_type == "dailylog":
        rows = c.execute("""
            SELECT id, timestamp, user, incident_id, unit_id, action, event_type, details
            FROM DailyLog
            ORDER BY timestamp DESC
        """).fetchall()
        headers = ["id", "timestamp", "user", "incident_id", "unit_id", "action", "event_type", "details"]
        filename = "dailylog"
    else:
        rows = c.execute("""
            SELECT id, timestamp, user, action, incident_id, unit_id, ok, reason, details, event_type
            FROM MasterLog
            ORDER BY timestamp DESC
        """).fetchall()
        headers = ["id", "timestamp", "user", "action", "incident_id", "unit_id", "ok", "reason", "details", "event_type"]
        filename = "masterlog"

    filepath = _archive_to_csv(filename, headers, [tuple(r) for r in rows])
    conn.close()

    masterlog(
        action="ADMIN_EXPORT_LOGS",
        user=user,
        details=f"Exported {len(rows)} {log_type} entries to {filepath}"
    )

    return {"ok": True, "file": filepath, "count": len(rows)}


# ------------------------------------------------------
# ADMIN — FETCH ADMIN LOGS
# ------------------------------------------------------

@app.get("/api/admin/logs", response_class=JSONResponse)
def api_admin_logs(user: str = "DISPATCH", limit: int = 50):
    """Fetch recent admin-related MasterLog entries."""
    ensure_phase3_schema()

    if not _is_admin(user):
        return JSONResponse(status_code=403, content={"ok": False, "error": "Admin only"})

    conn = get_conn()
    c = conn.cursor()

    rows = c.execute("""
        SELECT id, timestamp, user, action, incident_id, unit_id, details
        FROM MasterLog
        WHERE action LIKE 'ADMIN%'
        ORDER BY timestamp DESC
        LIMIT ?
    """, (limit,)).fetchall()

    conn.close()

    return {"ok": True, "entries": [dict(r) for r in rows]}


# ------------------------------------------------------
# ADMIN — RESET RUN NUMBERS
# ------------------------------------------------------

@app.post("/admin/reset/run_numbers", response_class=JSONResponse)
def admin_reset_run_numbers(
    user: str = "DISPATCH",
    confirm: bool = Body(False, embed=True),
    force: bool = Body(False, embed=True)
):
    """Reset run number counter to 1 for current year."""
    ensure_phase3_schema()

    if not _is_admin(user):
        return JSONResponse(status_code=403, content={"ok": False, "error": "Admin only"})

    if not confirm:
        return {"ok": False, "error": "Confirmation required. Set confirm=true"}

    conn = get_conn()
    c = conn.cursor()

    current_year = datetime.datetime.now().year

    # Check if incidents exist for this year (unless force=True)
    if not force:
        existing = c.execute("""
            SELECT COUNT(*) FROM Incidents
            WHERE incident_number LIKE ?
        """, (f"{current_year}-%",)).fetchone()[0]

        if existing > 0:
            conn.close()
            return {
                "ok": False,
                "error": f"Cannot reset: {existing} incidents exist for {current_year}. Use force=true to override."
            }

    # Reset counter
    c.execute("""
        INSERT INTO IncidentCounter (year, next_seq)
        VALUES (?, 1)
        ON CONFLICT(year)
        DO UPDATE SET next_seq = 1
    """, (current_year,))

    conn.commit()
    conn.close()

    masterlog(
        action="ADMIN_RESET_RUN_NUMBERS",
        user=user,
        details=f"Reset run counter to 1 for year {current_year} (force={force})"
    )

    return {"ok": True, "year": current_year, "next_seq": 1}


# ------------------------------------------------------
# ADMIN — RESET UNIT STATUS
# ------------------------------------------------------

@app.post("/admin/reset/units", response_class=JSONResponse)
def admin_reset_units(
    user: str = "DISPATCH",
    confirm: bool = Body(False, embed=True)
):
    """Reset all units to AVAILABLE status."""
    ensure_phase3_schema()

    if not _is_admin(user):
        return JSONResponse(status_code=403, content={"ok": False, "error": "Admin only"})

    if not confirm:
        return {"ok": False, "error": "Confirmation required. Set confirm=true"}

    conn = get_conn()
    c = conn.cursor()

    # Count affected units
    affected = c.execute("SELECT COUNT(*) FROM Units WHERE status != 'AVAILABLE'").fetchone()[0]

    # Reset all units
    c.execute("""
        UPDATE Units
        SET status = 'AVAILABLE', custom_status = NULL, last_updated = ?
    """, (_ts(),))

    # Clear all unit assignments that aren't cleared
    c.execute("""
        UPDATE UnitAssignments
        SET cleared = ?
        WHERE cleared IS NULL
    """, (_ts(),))

    conn.commit()
    conn.close()

    masterlog(
        action="ADMIN_RESET_UNITS",
        user=user,
        details=f"Reset {affected} units to AVAILABLE status"
    )

    return {"ok": True, "units_reset": affected}


# ------------------------------------------------------
# ADMIN — CLEAR AUDIT LOGS
# ------------------------------------------------------

@app.post("/admin/reset/logs", response_class=JSONResponse)
def admin_reset_logs(
    user: str = "DISPATCH",
    confirm: bool = Body(False, embed=True),
    keep_days: int = Body(0, embed=True)
):
    """Archive then clear MasterLog and DailyLog entries."""
    ensure_phase3_schema()

    if not _is_admin(user):
        return JSONResponse(status_code=403, content={"ok": False, "error": "Admin only"})

    if not confirm:
        return {"ok": False, "error": "Confirmation required. Set confirm=true"}

    conn = get_conn()
    c = conn.cursor()

    # Calculate cutoff date if keeping some days
    cutoff = None
    if keep_days > 0:
        cutoff_date = datetime.datetime.now() - datetime.timedelta(days=keep_days)
        cutoff = cutoff_date.strftime("%Y-%m-%d")

    # Archive MasterLog
    if cutoff:
        ml_rows = c.execute("""
            SELECT id, timestamp, user, action, incident_id, unit_id, ok, reason, details, event_type
            FROM MasterLog WHERE timestamp < ?
            ORDER BY timestamp
        """, (cutoff,)).fetchall()
    else:
        ml_rows = c.execute("""
            SELECT id, timestamp, user, action, incident_id, unit_id, ok, reason, details, event_type
            FROM MasterLog ORDER BY timestamp
        """).fetchall()

    ml_headers = ["id", "timestamp", "user", "action", "incident_id", "unit_id", "ok", "reason", "details", "event_type"]
    ml_filepath = _archive_to_csv("masterlog", ml_headers, [tuple(r) for r in ml_rows])

    # Archive DailyLog
    if cutoff:
        dl_rows = c.execute("""
            SELECT id, timestamp, user, incident_id, unit_id, action, event_type, details
            FROM DailyLog WHERE timestamp < ?
            ORDER BY timestamp
        """, (cutoff,)).fetchall()
    else:
        dl_rows = c.execute("""
            SELECT id, timestamp, user, incident_id, unit_id, action, event_type, details
            FROM DailyLog ORDER BY timestamp
        """).fetchall()

    dl_headers = ["id", "timestamp", "user", "incident_id", "unit_id", "action", "event_type", "details"]
    dl_filepath = _archive_to_csv("dailylog", dl_headers, [tuple(r) for r in dl_rows])

    # Log before deletion
    masterlog(
        action="ADMIN_CLEAR_LOGS",
        user=user,
        details=f"Archiving logs: MasterLog={len(ml_rows)}, DailyLog={len(dl_rows)}, keep_days={keep_days}"
    )

    # Delete logs
    if cutoff:
        c.execute("DELETE FROM MasterLog WHERE timestamp < ?", (cutoff,))
        c.execute("DELETE FROM DailyLog WHERE timestamp < ?", (cutoff,))
    else:
        c.execute("DELETE FROM MasterLog")
        c.execute("DELETE FROM DailyLog")

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "masterlog_archived": len(ml_rows),
        "dailylog_archived": len(dl_rows),
        "masterlog_file": ml_filepath,
        "dailylog_file": dl_filepath
    }


# ------------------------------------------------------
# ADMIN — CLEAR CLOSED INCIDENTS
# ------------------------------------------------------

@app.post("/admin/reset/closed", response_class=JSONResponse)
def admin_reset_closed(
    user: str = "DISPATCH",
    confirm: bool = Body(False, embed=True)
):
    """Archive then clear only closed incidents."""
    ensure_phase3_schema()

    if not _is_admin(user):
        return JSONResponse(status_code=403, content={"ok": False, "error": "Admin only"})

    if not confirm:
        return {"ok": False, "error": "Confirmation required. Set confirm=true"}

    conn = get_conn()
    c = conn.cursor()

    # Get closed incidents for archiving
    incidents = c.execute("""
        SELECT incident_id, incident_number, run_number, status, type, location, address,
               priority, caller_name, caller_phone, narrative, created, updated, closed_at,
               final_disposition, cancel_reason
        FROM Incidents
        WHERE status = 'CLOSED' AND incident_number IS NOT NULL
        ORDER BY created
    """).fetchall()

    if not incidents:
        conn.close()
        return {"ok": True, "message": "No closed incidents to clear", "count": 0}

    headers = ["incident_id", "incident_number", "run_number", "status", "type", "location",
               "address", "priority", "caller_name", "caller_phone", "narrative", "created",
               "updated", "closed_at", "final_disposition", "cancel_reason"]

    filepath = _archive_to_csv("closed_incidents", headers, [tuple(r) for r in incidents])

    # Get incident IDs for related data cleanup
    incident_ids = [r["incident_id"] for r in incidents]

    # Log before deletion
    masterlog(
        action="ADMIN_CLEAR_CLOSED",
        user=user,
        details=f"Archiving {len(incidents)} closed incidents to {filepath}"
    )

    # Delete related data
    placeholders = ",".join("?" * len(incident_ids))
    c.execute(f"DELETE FROM UnitAssignments WHERE incident_id IN ({placeholders})", incident_ids)
    c.execute(f"DELETE FROM Narrative WHERE incident_id IN ({placeholders})", incident_ids)
    c.execute(f"DELETE FROM IncidentHistory WHERE incident_id IN ({placeholders})", incident_ids)
    c.execute(f"DELETE FROM HeldSeen WHERE incident_id IN ({placeholders})", incident_ids)

    # Delete incidents
    c.execute(f"DELETE FROM Incidents WHERE incident_id IN ({placeholders})", incident_ids)

    conn.commit()
    conn.close()

    return {"ok": True, "count": len(incidents), "file": filepath}


# ------------------------------------------------------
# ADMIN — CLEAR ALL INCIDENTS
# ------------------------------------------------------

@app.post("/admin/reset/incidents", response_class=JSONResponse)
def admin_reset_incidents(
    user: str = "DISPATCH",
    confirm: str = Body("", embed=True)
):
    """Archive then clear ALL incidents. Requires confirm='DELETE ALL'"""
    ensure_phase3_schema()

    if not _is_admin(user):
        return JSONResponse(status_code=403, content={"ok": False, "error": "Admin only"})

    if confirm != "DELETE ALL":
        return {"ok": False, "error": "Type 'DELETE ALL' to confirm this action"}

    conn = get_conn()
    c = conn.cursor()

    # Archive all incidents
    incidents = c.execute("""
        SELECT incident_id, incident_number, run_number, status, type, location, address,
               priority, caller_name, caller_phone, narrative, created, updated, closed_at,
               final_disposition, cancel_reason
        FROM Incidents
        ORDER BY created
    """).fetchall()

    headers = ["incident_id", "incident_number", "run_number", "status", "type", "location",
               "address", "priority", "caller_name", "caller_phone", "narrative", "created",
               "updated", "closed_at", "final_disposition", "cancel_reason"]

    filepath = _archive_to_csv("all_incidents", headers, [tuple(r) for r in incidents])

    # Log before deletion
    masterlog(
        action="ADMIN_CLEAR_ALL_INCIDENTS",
        user=user,
        details=f"Archiving {len(incidents)} incidents to {filepath}"
    )

    # Clear all related tables
    c.execute("DELETE FROM UnitAssignments")
    c.execute("DELETE FROM Narrative")
    c.execute("DELETE FROM IncidentHistory")
    c.execute("DELETE FROM HeldSeen")
    c.execute("DELETE FROM Incidents")

    conn.commit()
    conn.close()

    return {"ok": True, "count": len(incidents), "file": filepath}


# ------------------------------------------------------
# ADMIN — FULL SYSTEM RESET
# ------------------------------------------------------

@app.post("/admin/reset/full", response_class=JSONResponse)
def admin_reset_full(
    user: str = "DISPATCH",
    confirm: str = Body("", embed=True)
):
    """Full system reset: archive everything, clear all data, reset run numbers. Requires confirm='RESET'"""
    ensure_phase3_schema()

    if not _is_admin(user):
        return JSONResponse(status_code=403, content={"ok": False, "error": "Admin only"})

    if confirm != "RESET":
        return {"ok": False, "error": "Type 'RESET' to confirm full system reset"}

    conn = get_conn()
    c = conn.cursor()

    ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    archived_files = []

    # 1. Archive incidents
    incidents = c.execute("""
        SELECT incident_id, incident_number, run_number, status, type, location, address,
               priority, caller_name, caller_phone, narrative, created, updated, closed_at,
               final_disposition, cancel_reason
        FROM Incidents ORDER BY created
    """).fetchall()
    inc_headers = ["incident_id", "incident_number", "run_number", "status", "type", "location",
                   "address", "priority", "caller_name", "caller_phone", "narrative", "created",
                   "updated", "closed_at", "final_disposition", "cancel_reason"]
    if incidents:
        archived_files.append(_archive_to_csv("full_reset_incidents", inc_headers, [tuple(r) for r in incidents]))

    # 2. Archive MasterLog
    ml_rows = c.execute("""
        SELECT id, timestamp, user, action, incident_id, unit_id, ok, reason, details, event_type
        FROM MasterLog ORDER BY timestamp
    """).fetchall()
    ml_headers = ["id", "timestamp", "user", "action", "incident_id", "unit_id", "ok", "reason", "details", "event_type"]
    if ml_rows:
        archived_files.append(_archive_to_csv("full_reset_masterlog", ml_headers, [tuple(r) for r in ml_rows]))

    # 3. Archive DailyLog
    dl_rows = c.execute("""
        SELECT id, timestamp, user, incident_id, unit_id, action, event_type, details
        FROM DailyLog ORDER BY timestamp
    """).fetchall()
    dl_headers = ["id", "timestamp", "user", "incident_id", "unit_id", "action", "event_type", "details"]
    if dl_rows:
        archived_files.append(_archive_to_csv("full_reset_dailylog", dl_headers, [tuple(r) for r in dl_rows]))

    # 4. Archive UnitAssignments
    ua_rows = c.execute("""
        SELECT id, incident_id, unit_id, assigned, dispatched, enroute, arrived, transporting,
               at_medical, cleared, disposition, disposition_remark
        FROM UnitAssignments ORDER BY id
    """).fetchall()
    ua_headers = ["id", "incident_id", "unit_id", "assigned", "dispatched", "enroute", "arrived",
                  "transporting", "at_medical", "cleared", "disposition", "disposition_remark"]
    if ua_rows:
        archived_files.append(_archive_to_csv("full_reset_unit_assignments", ua_headers, [tuple(r) for r in ua_rows]))

    # Log the reset before clearing
    masterlog(
        action="ADMIN_FULL_RESET",
        user=user,
        details=f"Full system reset initiated. Archived {len(incidents)} incidents, {len(ml_rows)} masterlog, {len(dl_rows)} dailylog"
    )

    # Clear all data
    c.execute("DELETE FROM Incidents")
    c.execute("DELETE FROM UnitAssignments")
    c.execute("DELETE FROM Narrative")
    c.execute("DELETE FROM IncidentHistory")
    c.execute("DELETE FROM HeldSeen")
    c.execute("DELETE FROM MasterLog")
    c.execute("DELETE FROM DailyLog")

    # Reset run numbers
    current_year = datetime.datetime.now().year
    c.execute("DELETE FROM IncidentCounter")
    c.execute("INSERT INTO IncidentCounter (year, next_seq) VALUES (?, 1)", (current_year,))

    # Reset unit statuses
    c.execute("""
        UPDATE Units
        SET status = 'AVAILABLE', custom_status = NULL, last_updated = ?
    """, (_ts(),))

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "message": "Full system reset complete",
        "archived_files": archived_files,
        "incidents_cleared": len(incidents),
        "masterlog_cleared": len(ml_rows),
        "dailylog_cleared": len(dl_rows),
        "run_number_reset_to": 1
    }


# ------------------------------------------------------
# ADMIN — DASHBOARD PAGE (HTML)
# ------------------------------------------------------

@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard_page(request: Request, user: str = "DISPATCH"):
    """Admin dashboard HTML page."""
    ensure_phase3_schema()

    if not _is_admin(user):
        return HTMLResponse("<h1>403 Forbidden</h1><p>Admin access required.</p>", status_code=403)

    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "user": user
        }
    )


# ================================================================
# STARTUP EVENT (KEEP THIS - DON'T MODIFY)
# ================================================================

@app.on_event("startup")
async def startup_event():
    """Initialize database schema on application startup."""
    ensure_phase3_schema()

    # Populate/refresh Units table from UnitLog.txt at startup (safe: does not overwrite status)
    try:
        sync_units_table()
    except Exception as e:
        print(f"[STARTUP] sync_units_table() failed: {e}")


# ================================================================
# ERROR HANDLERS
# ================================================================

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return JSONResponse(
        status_code=404,
        content={
            "ok": False,
            "error": "Resource not found",
            "path": str(request.url)
        }
    )


@app.exception_handler(500)
async def server_error_handler(request: Request, exc):
    print(f"❌ Server error: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "ok": False,
            "error": "Internal server error"
        }
    )


# ================================================================
# HEALTH CHECK
# ================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "timestamp": _ts(),
        "database": str(DB_PATH),
        "schema_initialized": _SCHEMA_INIT_DONE
    }

# Deferred bindings (do not alter logic)
_original_panel_active = panel_active
_original_panel_open = panel_open
_original_panel_held = panel_held

_IMPORT_PHASE = False

# =====================================================================
# FORD CAD — UNIT ACTION ENDPOINTS (UAW + Dispatch + Transfer Cmd)
# =====================================================================

@app.post("/api/unit_dispatch/{unit_id}/{incident_id}")
def api_unit_dispatch(unit_id: str, incident_id: int):
    conn = get_conn()
    c = conn.cursor()

    try:
        c.execute(
            """
            INSERT INTO UnitAssignments (unit_id, incident_id, status)
            VALUES (?, ?, 'ENROUTE')
            ON CONFLICT(unit_id, incident_id)
            DO UPDATE SET status='ENROUTE'
            """,
            (unit_id, incident_id),
        )

        # NOTE: If you later want DISPATCHED (not ENROUTE) on dispatch, change here.
        c.execute(
            """
            UPDATE Units
            SET status='ENROUTE', last_updated=?
            WHERE unit_id=?
            """,
            (_ts(), unit_id),
        )

        log_master(unit_id, incident_id, "UNIT_DISPATCH", f"{unit_id} dispatched to {incident_id}")
        conn.commit()
        return {"ok": True}

    finally:
        conn.close()


@app.post("/api/unit_status/{unit_id}/{status}")
async def api_unit_status(request: Request, unit_id: str, status: str):
    """
    Unit-scoped status endpoint.
    Canon rules:
      • If unit is currently on an active incident, stamp UnitAssignments so panels reflect display_status.
      • Apparatus status mirrors to assigned personnel automatically.
    """
    ensure_phase3_schema()

    new_status = (status or "").upper().strip()
    user = request.session.get("user", "Dispatcher")

    allowed = {
        "AVAILABLE",
        "UNAVAILABLE",
        "DISPATCHED",
        "ENROUTE",
        "ARRIVED",
        "TRANSPORTING",
        "AT_MEDICAL",
        "EMERGENCY",
    }
    if new_status not in allowed:
        return {"ok": False, "error": f"Invalid status {new_status}"}

    # Confirm unit exists + detect apparatus
    conn = get_conn()
    c = conn.cursor()
    row = c.execute(
        "SELECT unit_id, COALESCE(is_apparatus,0) AS is_apparatus FROM Units WHERE unit_id = ?",
        (unit_id,),
    ).fetchone()
    if not row:
        conn.close()
        return {"ok": False, "error": f"Unknown unit {unit_id}"}
    is_apparatus = int(row["is_apparatus"] or 0)

    # Update unit status
    update_unit_status(unit_id, new_status)
    log_master(unit_id, None, "STATUS_UPDATE", f"{unit_id} → {new_status}")

    # If unit is on an active incident, stamp assignment column (if present)
    active = c.execute(
        """
        SELECT incident_id
        FROM UnitAssignments
        WHERE unit_id = ?
          AND cleared IS NULL
        ORDER BY assigned DESC
        LIMIT 1
        """,
        (unit_id,),
    ).fetchone()
    incident_id = int(active["incident_id"]) if active else 0

    # Column-safe stamping
    ua_cols = {r["name"] for r in c.execute("PRAGMA table_info(UnitAssignments)").fetchall()}
    field_map = {
        "DISPATCHED": "dispatched",
        "ENROUTE": "enroute",
        "ARRIVED": "arrived",
        "TRANSPORTING": "transporting",
        "AT_MEDICAL": "at_medical",
    }
    field = field_map.get(new_status)

    conn.close()

    if incident_id and field and field in ua_cols:
        ensure_assignment_row(incident_id, unit_id)
        mark_assignment(incident_id, unit_id, field)
        incident_history(incident_id, new_status, user=user, unit_id=unit_id)

    # Apparatus mirrors to assigned crew
    if is_apparatus:
        crew = get_apparatus_crew(unit_id)
        for pid in crew:
            update_unit_status(pid, new_status)

            if incident_id and field and field in ua_cols:
                # Only stamp if that crew member is already assigned to this incident
                conn2 = get_conn()
                c2 = conn2.cursor()
                exists = c2.execute(
                    """
                    SELECT 1
                    FROM UnitAssignments
                    WHERE incident_id = ?
                      AND unit_id = ?
                      AND cleared IS NULL
                    LIMIT 1
                    """,
                    (incident_id, pid),
                ).fetchone()
                conn2.close()

                if exists:
                    ensure_assignment_row(incident_id, pid)
                    mark_assignment(incident_id, pid, field)
                    incident_history(incident_id, new_status, user=user, unit_id=pid)

    return {"ok": True}


# NOTE: Duplicate /api/unit_status endpoint was removed - using the one above with full validation


@app.post("/api/unit_clear/{unit_id}/{incident_id}")
def api_unit_clear(unit_id: str, incident_id: int):
    """
    Clear a unit from an incident (API version).

    CANON REQUIREMENT: Unit disposition is REQUIRED before clearing.
    This endpoint now marks assignments as cleared (preserving audit trail)
    instead of deleting them.
    """
    conn = get_conn()
    c = conn.cursor()

    try:
        # Check if unit has a disposition set
        row = c.execute("""
            SELECT disposition
            FROM UnitAssignments
            WHERE incident_id=? AND unit_id=? AND cleared IS NULL
        """, (incident_id, unit_id)).fetchone()

        if not row:
            conn.close()
            return {"ok": False, "error": "Unit not assigned to this incident or already cleared"}

        disposition = row["disposition"] if row else None
        if not disposition or not str(disposition).strip():
            conn.close()
            return {
                "ok": False,
                "error": "Unit disposition required before clearing",
                "requires_disposition": True,
                "incident_id": incident_id,
                "unit_id": unit_id
            }

        c.execute("BEGIN IMMEDIATE")

        # Mark assignment as cleared (DO NOT DELETE - preserve audit trail)
        c.execute(
            """
            UPDATE UnitAssignments
            SET cleared=?
            WHERE unit_id=? AND incident_id=? AND cleared IS NULL
            """,
            (_ts(), unit_id, incident_id),
        )

        # Return to AVAILABLE AND clear misc/custom status
        c.execute(
            """
            UPDATE Units
            SET status='AVAILABLE',
                custom_status='',
                last_updated=?
            WHERE unit_id=?
            """,
            (_ts(), unit_id),
        )

        log_master(unit_id, incident_id, "CLEAR", f"{unit_id} cleared {incident_id} with disposition {disposition}")
        conn.commit()

        # Check if last unit
        remaining = c.execute("""
            SELECT COUNT(*)
            FROM UnitAssignments
            WHERE incident_id=? AND cleared IS NULL
        """, (incident_id,)).fetchone()[0]

        if remaining == 0:
            return {
                "ok": True,
                "last_unit_cleared": True,
                "requires_event_disposition": True,
                "incident_id": incident_id
            }

        return {"ok": True}

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


@app.post("/api/transfer_command/{unit_id}/{new_command_unit}")
def api_transfer_command(unit_id: str, new_command_unit: str):
    conn = get_conn()
    c = conn.cursor()

    try:
        c.execute(
            """
            SELECT incident_id
            FROM UnitAssignments
            WHERE unit_id=?
            """,
            (unit_id,),
        )
        row = c.fetchone()

        if not row:
            return {"ok": False, "error": "No incident"}

        incident_id = row[0]

        c.execute(
            """
            UPDATE UnitAssignments
            SET commanding_unit=0
            WHERE incident_id=?
            """,
            (incident_id,),
        )

        c.execute(
            """
            UPDATE UnitAssignments
            SET commanding_unit=1
            WHERE incident_id=? AND unit_id=?
            """,
            (incident_id, new_command_unit),
        )

        log_master(new_command_unit, incident_id, "COMMAND_TRANSFER", f"Command → {new_command_unit}")
        conn.commit()
        return {"ok": True}

    finally:
        conn.close()


@app.get("/api/units_on_scene/{unit_id}")
def api_units_on_scene(unit_id: str):
    conn = get_conn()
    c = conn.cursor()

    try:
        c.execute(
            """
            SELECT incident_id
            FROM UnitAssignments
            WHERE unit_id=?
            """,
            (unit_id,),
        )
        row = c.fetchone()

        if not row:
            return []

        incident_id = row[0]

        c.execute(
            """
            SELECT unit_id, unit_id AS unit_name
            FROM UnitAssignments
            WHERE incident_id=?
              AND status='ARRIVED'
            """,
            (incident_id,),
        )

        return [dict(r) for r in c.fetchall()]

    finally:
        conn.close()


if __name__ == "__main__":
    print("[!] Do not run this file directly.")
    print("[+] Use: uvicorn main:app --reload")
    print("")
    print("Quick Start:")
    print("   1. pip install -r requirements.txt")
    print("   2. uvicorn main:app --reload")
    print("   3. Open http://127.0.0.1:8000")


@app.get("/api/unit_ids")
async def api_unit_ids():
    """
    Return the canonical list of known unit IDs from the Units table.
    Front-end can use this to validate unit commands safely.
    """
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()
    rows = c.execute("SELECT unit_id FROM Units ORDER BY unit_id").fetchall()
    conn.close()
    return [r["unit_id"] if hasattr(r, "keys") else r[0] for r in rows]


@app.get("/api/unit_aliases")
async def api_unit_aliases():
    """
    Return alias-to-unit_id mapping for CLI resolution.
    Each unit can have multiple aliases (comma-separated in DB).
    Returns: { "alias1": "UNIT_ID", "alias2": "UNIT_ID", ... }
    Also includes unit_id itself as an alias (case-insensitive).
    """
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()
    rows = c.execute("SELECT unit_id, aliases FROM Units").fetchall()
    conn.close()

    alias_map = {}
    for r in rows:
        unit_id = r["unit_id"] if hasattr(r, "keys") else r[0]
        aliases_str = (r["aliases"] if hasattr(r, "keys") else r[1]) or ""

        # Unit ID itself is always an alias (lowercase for case-insensitive lookup)
        alias_map[unit_id.lower()] = unit_id

        # Parse comma-separated aliases
        if aliases_str.strip():
            for alias in aliases_str.split(","):
                alias = alias.strip().lower()
                if alias:
                    alias_map[alias] = unit_id

    return alias_map


# ---------------------------------------------------------------------------
# CREW (PersonnelAssignments) - GET endpoint
# NOTE: POST /api/crew/assign and /api/crew/unassign are defined earlier (line ~3562)
# ---------------------------------------------------------------------------

@app.get("/api/crew/{apparatus_id}")
async def api_crew_get(apparatus_id: str):
    """Return assigned personnel IDs for a given apparatus/command unit."""
    ensure_phase3_schema()
    apparatus_id = str(apparatus_id or "").strip()
    if not apparatus_id:
        return {"ok": False, "error": "apparatus_id is required"}

    conn = get_conn()
    c = conn.cursor()
    try:
        rows = c.execute(
            "SELECT personnel_id, role, shift, updated FROM PersonnelAssignments WHERE apparatus_id=? ORDER BY personnel_id",
            (apparatus_id,),
        ).fetchall()
        crew = []
        for r in rows:
            if hasattr(r, "keys"):
                crew.append({"personnel_id": r["personnel_id"], "role": r["role"], "shift": r["shift"], "updated": r["updated"]})
            else:
                crew.append({"personnel_id": r[0], "role": r[1], "shift": r[2], "updated": r[3]})
        return {"ok": True, "crew": crew}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CONTACTS MANAGEMENT (for messaging responders)
# ---------------------------------------------------------------------------

@app.get("/api/contacts")
async def api_contacts_list():
    """List all contacts."""
    ensure_phase3_schema()
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT contact_id, unit_id, name, email, phone, carrier,
                   signal_number, role, is_active, receive_reports
            FROM Contacts
            ORDER BY name, unit_id
        """).fetchall()
        contacts = [dict(r) for r in rows]
        return {"ok": True, "contacts": contacts}
    finally:
        conn.close()


@app.get("/api/contacts/{contact_id}")
async def api_contact_get(contact_id: int):
    """Get a single contact."""
    ensure_phase3_schema()
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM Contacts WHERE contact_id=?", (contact_id,)
        ).fetchone()
        if not row:
            return {"ok": False, "error": "Contact not found"}
        return {"ok": True, "contact": dict(row)}
    finally:
        conn.close()


@app.post("/api/contacts")
async def api_contact_create(request: Request):
    """Create a new contact."""
    ensure_phase3_schema()
    data = await request.json()

    unit_id = str(data.get("unit_id", "")).strip() or None
    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip() or None
    phone = str(data.get("phone", "")).strip() or None
    carrier = str(data.get("carrier", "")).strip() or None
    signal_number = str(data.get("signal_number", "")).strip() or None
    role = str(data.get("role", "")).strip() or None
    is_active = 1 if data.get("is_active", True) else 0
    receive_reports = 1 if data.get("receive_reports", False) else 0

    ts = _ts()

    conn = get_conn()
    try:
        c = conn.execute("""
            INSERT INTO Contacts
            (unit_id, name, email, phone, carrier, signal_number, role, is_active, receive_reports, created, updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (unit_id, name, email, phone, carrier, signal_number, role, is_active, receive_reports, ts, ts))
        conn.commit()
        return {"ok": True, "contact_id": c.lastrowid}
    finally:
        conn.close()


@app.put("/api/contacts/{contact_id}")
async def api_contact_update(contact_id: int, request: Request):
    """Update a contact."""
    ensure_phase3_schema()
    data = await request.json()

    conn = get_conn()
    try:
        existing = conn.execute("SELECT * FROM Contacts WHERE contact_id=?", (contact_id,)).fetchone()
        if not existing:
            return {"ok": False, "error": "Contact not found"}

        unit_id = str(data.get("unit_id", existing["unit_id"] or "")).strip() or None
        name = str(data.get("name", existing["name"] or "")).strip()
        email = str(data.get("email", existing["email"] or "")).strip() or None
        phone = str(data.get("phone", existing["phone"] or "")).strip() or None
        carrier = str(data.get("carrier", existing["carrier"] or "")).strip() or None
        signal_number = str(data.get("signal_number", existing["signal_number"] or "")).strip() or None
        role = str(data.get("role", existing["role"] or "")).strip() or None

        is_active = existing["is_active"]
        if "is_active" in data:
            is_active = 1 if data["is_active"] else 0

        receive_reports = existing["receive_reports"]
        if "receive_reports" in data:
            receive_reports = 1 if data["receive_reports"] else 0

        ts = _ts()

        conn.execute("""
            UPDATE Contacts
            SET unit_id=?, name=?, email=?, phone=?, carrier=?, signal_number=?, role=?,
                is_active=?, receive_reports=?, updated=?
            WHERE contact_id=?
        """, (unit_id, name, email, phone, carrier, signal_number, role, is_active, receive_reports, ts, contact_id))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.delete("/api/contacts/{contact_id}")
async def api_contact_delete(contact_id: int):
    """Delete a contact."""
    ensure_phase3_schema()
    conn = get_conn()
    try:
        conn.execute("DELETE FROM Contacts WHERE contact_id=?", (contact_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.post("/api/contacts/{contact_id}/message")
async def api_contact_send_message(contact_id: int, request: Request):
    """Send a message to a contact via their preferred channel."""
    ensure_phase3_schema()
    data = await request.json()
    message = str(data.get("message", "")).strip()
    channel = str(data.get("channel", "email")).strip().lower()  # email, sms, signal

    if not message:
        return {"ok": False, "error": "Message is required"}

    conn = get_conn()
    try:
        contact = conn.execute("SELECT * FROM Contacts WHERE contact_id=?", (contact_id,)).fetchone()
        if not contact:
            return {"ok": False, "error": "Contact not found"}
        contact = dict(contact)
    finally:
        conn.close()

    try:
        import reports

        if channel == "email" and contact.get("email"):
            success = reports.send_email(
                to=contact["email"],
                subject=f"CAD Message for {contact.get('name', contact.get('unit_id', 'Responder'))}",
                body_text=message
            )
            return {"ok": success, "channel": "email"}

        elif channel == "sms" and contact.get("phone") and contact.get("carrier"):
            success = reports.send_sms(contact["phone"], contact["carrier"], message)
            return {"ok": success, "channel": "sms"}

        elif channel == "signal" and contact.get("signal_number"):
            success = reports.send_signal(contact["signal_number"], message)
            return {"ok": success, "channel": "signal"}

        else:
            return {"ok": False, "error": f"Contact missing {channel} info"}

    except ImportError:
        return {"ok": False, "error": "Reports module not available"}


