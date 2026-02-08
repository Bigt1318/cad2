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
app.state.templates = templates  # expose for sub-routers

# ================================================================
# REPORTS & MESSAGING MODULE
# ================================================================
try:
    import reports
    reports.register_report_routes(app)
    print("[MAIN] Reports module loaded")

    # Initialize reports - starts scheduler if enabled (every 30 min during shift)
    # Scheduler sends to all battalion chiefs: B1-B4
    reports.init_reports()
except ImportError as e:
    print(f"[MAIN] Reports module not available: {e}")

# ================================================================
# REPORTS V2 MODULE (State-of-the-Art Reporting System)
# ================================================================
try:
    from app.reporting import register_reporting_routes
    register_reporting_routes(app)
    print("[MAIN] Reports v2 module loaded")
except ImportError as e:
    print(f"[MAIN] Reports v2 module not available: {e}")
except Exception as e:
    print(f"[MAIN] Reports v2 module error: {e}")

# ================================================================
# HISTORY MODULE (Enterprise Call History Viewer)
# ================================================================
try:
    from app.history import register_history_routes
    register_history_routes(app)
    print("[MAIN] History module loaded")
except ImportError as e:
    print(f"[MAIN] History module not available: {e}")
except Exception as e:
    print(f"[MAIN] History module error: {e}")

# ================================================================
# EVENT STREAM MODULE (Operational Event Timeline)
# ================================================================
try:
    from app.eventstream import register_eventstream_routes
    register_eventstream_routes(app)
    print("[MAIN] Event Stream module loaded")
except ImportError as e:
    print(f"[MAIN] Event Stream module not available: {e}")
except Exception as e:
    print(f"[MAIN] Event Stream module error: {e}")

# ================================================================
# REMINDERS MODULE (Smart Reminders & Cross-Shift Awareness)
# ================================================================
try:
    from app.reminders import register_reminder_routes, init_reminder_scheduler
    register_reminder_routes(app)
    init_reminder_scheduler()
    print("[MAIN] Reminders module loaded")
except ImportError as e:
    print(f"[MAIN] Reminders module not available: {e}")
except Exception as e:
    print(f"[MAIN] Reminders module error: {e}")

# ================================================================
# MOBILE MODULE (Extended Mobile MDT)
# ================================================================
try:
    from app.mobile import register_mobile_routes
    register_mobile_routes(app)
    print("[MAIN] Mobile module loaded")
except ImportError as e:
    print(f"[MAIN] Mobile module not available: {e}")
except Exception as e:
    print(f"[MAIN] Mobile module error: {e}")

# ================================================================
# PLAYBOOKS MODULE (Workflow Automation Engine)
# ================================================================
try:
    from app.playbooks import register_playbook_routes
    register_playbook_routes(app)
    print("[MAIN] Playbooks module loaded")
except ImportError as e:
    print(f"[MAIN] Playbooks module not available: {e}")
except Exception as e:
    print(f"[MAIN] Playbooks module error: {e}")

# ================================================================
# THEMES MODULE (User Theme System)
# ================================================================
try:
    from app.themes import register_theme_routes
    register_theme_routes(app)
    print("[MAIN] Themes module loaded")
except ImportError as e:
    print(f"[MAIN] Themes module not available: {e}")
except Exception as e:
    print(f"[MAIN] Themes module error: {e}")

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

    response = await call_next(request)

    # If handler already wrote to MasterLog, do nothing
    if MASTERLOG_WRITTEN.get():
        return response

    # Generic audit fallback
    try:
        user = (request.session.get("user") if hasattr(request, "session") else None) or "Dispatcher"
    except Exception:
        user = "Dispatcher"

    ok = 1 if getattr(response, "status_code", 200) < 400 else 0

    incident_id = None
    unit_id = None

    # Path-based hints
    m = re.search(r"/incident/(\d+)", request.url.path)
    if m:
        try:
            incident_id = int(m.group(1))
        except Exception:
            incident_id = None

    m2 = re.search(r"/unit/([^/]+)", request.url.path)
    if m2:
        unit_id = m2.group(1)

    # Body-based hints (JSON) — use cached body if handler already read it
    details = None
    try:
        body_bytes = getattr(request, "_body", b"") or b""
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

    event = f"HTTP_{request.method} {request.url.path}"[:80]

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
    {"key": "SELF-INITIATED",     "group": "OPS",  "requires_number": True},   # unit self-initiated incident
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

    "SI": "SELF-INITIATED",
    "SELFINIT": "SELF-INITIATED",
    "SELF INIT": "SELF-INITIATED",
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


# ================================================================
# MESSAGING MODULE
# ================================================================
try:
    from app.messaging.routes import register_messaging_routes
    register_messaging_routes(app, templates, get_conn)
    print("[MAIN] Messaging module loaded")
except ImportError as e:
    print(f"[MAIN] Messaging module not available: {e}")
except Exception as e:
    print(f"[MAIN] Messaging module error: {e}")

# ================================================================
# CHAT MODULE v2 — Channel-based messaging
# ================================================================
try:
    from app.messaging.models import init_chat_schema
    from app.messaging.chat_engine import get_chat_engine
    from app.messaging.chat_routes import register_chat_routes
    # Init chat schema
    _chat_conn = get_conn()
    init_chat_schema(_chat_conn)
    _chat_conn.close()
    # Init singleton engine
    get_chat_engine(get_conn)
    # Register chat API routes
    register_chat_routes(app, templates, get_conn)
    print("[MAIN] Chat v2 module loaded")
except ImportError as e:
    print(f"[MAIN] Chat v2 module not available: {e}")
except Exception as e:
    import traceback; traceback.print_exc()
    print(f"[MAIN] Chat v2 module error: {e}")


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
                user TEXT,
                dl_number TEXT
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
                user TEXT,
                dl_number TEXT
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


def _next_dl_number(cursor, year: int | None = None) -> str:
    """
    Generate the next Daily Log number for the given year.
    Format: YYYY-NNNN (e.g. 2026-0001, 2026-0002, ...)
    Uses the DailyLog table to find the current max sequence for the year.
    """
    if year is None:
        year = int(datetime.now().strftime("%Y"))
    prefix = f"{year}-"
    row = cursor.execute(
        "SELECT dl_number FROM DailyLog WHERE dl_number LIKE ? ORDER BY dl_number DESC LIMIT 1",
        (f"{prefix}%",),
    ).fetchone()
    if row and row[0]:
        try:
            seq = int(row[0].split("-", 1)[1]) + 1
        except (ValueError, IndexError):
            seq = 1
    else:
        seq = 1
    return f"{year}-{seq:04d}"


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
    Auto-assigns dl_number in YYYY-NNNN format.
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

    dl_number = _next_dl_number(c)

    c.execute(
        """
        INSERT INTO DailyLog (timestamp, user, incident_id, unit_id, action, event_type, details, dl_number)
        VALUES (?, ?, ?, ?, 'DAILYLOG', ?, ?, ?)
        """,
        (ts, user, incident_id, unit_id, subtype, text, dl_number),
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

    try:
        from app.eventstream.emitter import emit_event
        emit_event("NARRATIVE_ADDED", incident_id=incident_id, unit_id=unit_id, user=user,
                   summary=text[:120] if text else "Narrative added", category="narrative")
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


def expire_stale_shift_overrides() -> int:
    """
    Auto-expire shift overrides when the shift they were moved to is no longer active.
    Called on panel load to clean up overrides from previous shifts.

    Returns the count of expired overrides.
    """
    try:
        from shift_logic import get_shift_for_date
        import datetime
        today = datetime.date.today()
        day_shift, night_shift = get_shift_for_date(today)
        active_shifts = {day_shift, night_shift}
    except Exception:
        # Fallback: don't expire anything if shift_logic unavailable
        return 0

    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()
    expired_count = 0
    try:
        # Find overrides where to_shift_letter is NOT an active shift today
        rows = c.execute(
            """
            SELECT id, unit_id, to_shift_letter
            FROM ShiftOverrides
            WHERE end_ts IS NULL
            """
        ).fetchall()

        for r in (rows or []):
            to_shift = (r["to_shift_letter"] or "").strip().upper()
            if to_shift and to_shift not in active_shifts:
                # Expire this override - it was for a previous shift
                c.execute(
                    "UPDATE ShiftOverrides SET end_ts = ? WHERE id = ?",
                    (_ts(), r["id"])
                )
                expired_count += 1
                try:
                    log_master("SHIFT_OVERRIDE_AUTO_EXPIRE",
                              f"Auto-expired coverage for {r['unit_id']} (was on {to_shift} shift, now {day_shift}/{night_shift})")
                except Exception:
                    pass

        if expired_count > 0:
            conn.commit()
    finally:
        conn.close()

    return expired_count


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
    # NFIRS 5.0 / NERIS COMPLIANCE FIELDS
    # --------------------------------------------------
    # Basic Module
    _add_col("ALTER TABLE Incidents ADD COLUMN nfirs_type_code TEXT")         # NFIRS incident type (111, 112, 321, etc.)
    _add_col("ALTER TABLE Incidents ADD COLUMN property_use_code TEXT")       # Property use code (419, 429, etc.)
    _add_col("ALTER TABLE Incidents ADD COLUMN actions_taken TEXT")           # Actions taken codes (comma-separated)
    _add_col("ALTER TABLE Incidents ADD COLUMN aid_given_received TEXT")      # Mutual aid: N=None, G=Given, R=Received
    _add_col("ALTER TABLE Incidents ADD COLUMN shift TEXT")                   # Shift on duty (A, B, C, D)
    _add_col("ALTER TABLE Incidents ADD COLUMN alarm_time TEXT")              # Time alarm received
    _add_col("ALTER TABLE Incidents ADD COLUMN arrival_time TEXT")            # First unit arrival time
    _add_col("ALTER TABLE Incidents ADD COLUMN controlled_time TEXT")         # Fire controlled time
    _add_col("ALTER TABLE Incidents ADD COLUMN last_unit_cleared TEXT")       # Last unit cleared time

    # Fire Module
    _add_col("ALTER TABLE Incidents ADD COLUMN fire_origin_area TEXT")        # Area of fire origin code
    _add_col("ALTER TABLE Incidents ADD COLUMN heat_source TEXT")             # Heat source code
    _add_col("ALTER TABLE Incidents ADD COLUMN item_first_ignited TEXT")      # Item first ignited code
    _add_col("ALTER TABLE Incidents ADD COLUMN fire_cause TEXT")              # Cause code (1=Intentional, 2=Unintentional, etc.)
    _add_col("ALTER TABLE Incidents ADD COLUMN fire_spread TEXT")             # Fire spread code (1=Object, 2=Room, 3=Floor, etc.)
    _add_col("ALTER TABLE Incidents ADD COLUMN structure_type TEXT")          # Structure type code
    _add_col("ALTER TABLE Incidents ADD COLUMN building_status TEXT")         # Building status (1=Normal, 2=Under construction, etc.)
    _add_col("ALTER TABLE Incidents ADD COLUMN stories_above_grade INTEGER")  # Number of stories above grade
    _add_col("ALTER TABLE Incidents ADD COLUMN stories_below_grade INTEGER")  # Number of stories below grade

    # Detection & Suppression
    _add_col("ALTER TABLE Incidents ADD COLUMN detector_present TEXT")        # Detector present code (1=Yes, 2=No, U=Unknown)
    _add_col("ALTER TABLE Incidents ADD COLUMN detector_type TEXT")           # Detector type code
    _add_col("ALTER TABLE Incidents ADD COLUMN detector_worked TEXT")         # Detector operated (1=Yes, 2=No, etc.)
    _add_col("ALTER TABLE Incidents ADD COLUMN aes_present TEXT")             # Auto extinguishing system present
    _add_col("ALTER TABLE Incidents ADD COLUMN aes_type TEXT")                # AES type code (sprinkler, etc.)
    _add_col("ALTER TABLE Incidents ADD COLUMN aes_worked TEXT")              # AES operated code

    # Property & Loss
    _add_col("ALTER TABLE Incidents ADD COLUMN property_loss INTEGER")        # Property loss in dollars
    _add_col("ALTER TABLE Incidents ADD COLUMN contents_loss INTEGER")        # Contents loss in dollars
    _add_col("ALTER TABLE Incidents ADD COLUMN property_value INTEGER")       # Pre-incident property value
    _add_col("ALTER TABLE Incidents ADD COLUMN contents_value INTEGER")       # Pre-incident contents value

    # Casualties
    _add_col("ALTER TABLE Incidents ADD COLUMN civilian_injuries INTEGER DEFAULT 0")
    _add_col("ALTER TABLE Incidents ADD COLUMN civilian_deaths INTEGER DEFAULT 0")
    _add_col("ALTER TABLE Incidents ADD COLUMN ff_injuries INTEGER DEFAULT 0")
    _add_col("ALTER TABLE Incidents ADD COLUMN ff_deaths INTEGER DEFAULT 0")

    # EMS / NERIS fields
    _add_col("ALTER TABLE Incidents ADD COLUMN patient_count INTEGER DEFAULT 0")
    _add_col("ALTER TABLE Incidents ADD COLUMN transport_count INTEGER DEFAULT 0")
    _add_col("ALTER TABLE Incidents ADD COLUMN destination TEXT")             # Transport destination
    _add_col("ALTER TABLE Incidents ADD COLUMN patient_disposition TEXT")     # Patient disposition code

    # Additional NERIS fields
    _add_col("ALTER TABLE Incidents ADD COLUMN weather_conditions TEXT")      # Weather at scene
    _add_col("ALTER TABLE Incidents ADD COLUMN road_conditions TEXT")         # Road conditions (if MVA)
    _add_col("ALTER TABLE Incidents ADD COLUMN special_circumstances TEXT")   # Special circumstances codes

    # --------------------------------------------------
    # DETERMINANT CODES (MPDS/FPDS)
    # --------------------------------------------------
    _add_col("ALTER TABLE Incidents ADD COLUMN determinant_code TEXT")        # Full code e.g., "10-D-1"
    _add_col("ALTER TABLE Incidents ADD COLUMN determinant_protocol TEXT")    # MPDS, FPDS, or custom
    _add_col("ALTER TABLE Incidents ADD COLUMN determinant_description TEXT") # Chief complaint/description

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
    if "dl_number" not in dl_cols:
        _add_col("ALTER TABLE DailyLog ADD COLUMN dl_number TEXT")




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
    _add_col("ALTER TABLE Units ADD COLUMN display_order INTEGER DEFAULT 999")  # For sorting units in panels
    _add_col("ALTER TABLE Units ADD COLUMN department TEXT")  # Department name for mutual aid grouping

    # --------------------------------------------------
    # SYSTEM SETTINGS (Key-Value store for preferences)
    # --------------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS SystemSettings (
            key TEXT PRIMARY KEY,
            value TEXT,
            description TEXT,
            updated TEXT
        )
    """)

    # --------------------------------------------------
    # RESPONSE PLANS (Run Cards)
    # --------------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS ResponsePlans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            incident_type TEXT NOT NULL,
            priority INTEGER DEFAULT 0,
            units TEXT NOT NULL,
            alarm_level INTEGER DEFAULT 1,
            time_of_day TEXT,
            location_pattern TEXT,
            is_active INTEGER DEFAULT 1,
            notes TEXT,
            created TEXT,
            updated TEXT
        )
    """)

    _add_col("ALTER TABLE ResponsePlans ADD COLUMN name TEXT")
    _add_col("ALTER TABLE ResponsePlans ADD COLUMN incident_type TEXT")
    _add_col("ALTER TABLE ResponsePlans ADD COLUMN priority INTEGER DEFAULT 0")
    _add_col("ALTER TABLE ResponsePlans ADD COLUMN units TEXT")
    _add_col("ALTER TABLE ResponsePlans ADD COLUMN alarm_level INTEGER DEFAULT 1")
    _add_col("ALTER TABLE ResponsePlans ADD COLUMN time_of_day TEXT")
    _add_col("ALTER TABLE ResponsePlans ADD COLUMN location_pattern TEXT")
    _add_col("ALTER TABLE ResponsePlans ADD COLUMN is_active INTEGER DEFAULT 1")
    _add_col("ALTER TABLE ResponsePlans ADD COLUMN notes TEXT")
    _add_col("ALTER TABLE ResponsePlans ADD COLUMN created TEXT")
    _add_col("ALTER TABLE ResponsePlans ADD COLUMN updated TEXT")

    # --------------------------------------------------
    # PRE-PLANS (Pre-Incident Plans for Buildings)
    # --------------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS PrePlans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            address TEXT NOT NULL,
            city TEXT,
            occupancy_type TEXT,
            construction_type TEXT,
            stories INTEGER DEFAULT 1,
            square_footage INTEGER,
            contact_name TEXT,
            contact_phone TEXT,
            sprinkler_type TEXT,
            standpipe_type TEXT,
            fdc_location TEXT,
            alarm_type TEXT,
            alarm_panel_location TEXT,
            knox_box_location TEXT,
            gas_shutoff TEXT,
            electric_shutoff TEXT,
            water_shutoff TEXT,
            hazards TEXT,
            access_info TEXT,
            tactical_notes TEXT,
            last_reviewed TEXT,
            is_active INTEGER DEFAULT 1,
            created TEXT,
            updated TEXT
        )
    """)

    _add_col("ALTER TABLE PrePlans ADD COLUMN name TEXT")
    _add_col("ALTER TABLE PrePlans ADD COLUMN address TEXT")
    _add_col("ALTER TABLE PrePlans ADD COLUMN city TEXT")
    _add_col("ALTER TABLE PrePlans ADD COLUMN occupancy_type TEXT")
    _add_col("ALTER TABLE PrePlans ADD COLUMN construction_type TEXT")
    _add_col("ALTER TABLE PrePlans ADD COLUMN stories INTEGER DEFAULT 1")
    _add_col("ALTER TABLE PrePlans ADD COLUMN square_footage INTEGER")
    _add_col("ALTER TABLE PrePlans ADD COLUMN contact_name TEXT")
    _add_col("ALTER TABLE PrePlans ADD COLUMN contact_phone TEXT")
    _add_col("ALTER TABLE PrePlans ADD COLUMN sprinkler_type TEXT")
    _add_col("ALTER TABLE PrePlans ADD COLUMN standpipe_type TEXT")
    _add_col("ALTER TABLE PrePlans ADD COLUMN fdc_location TEXT")
    _add_col("ALTER TABLE PrePlans ADD COLUMN alarm_type TEXT")
    _add_col("ALTER TABLE PrePlans ADD COLUMN alarm_panel_location TEXT")
    _add_col("ALTER TABLE PrePlans ADD COLUMN knox_box_location TEXT")
    _add_col("ALTER TABLE PrePlans ADD COLUMN gas_shutoff TEXT")
    _add_col("ALTER TABLE PrePlans ADD COLUMN electric_shutoff TEXT")
    _add_col("ALTER TABLE PrePlans ADD COLUMN water_shutoff TEXT")
    _add_col("ALTER TABLE PrePlans ADD COLUMN hazards TEXT")
    _add_col("ALTER TABLE PrePlans ADD COLUMN access_info TEXT")
    _add_col("ALTER TABLE PrePlans ADD COLUMN tactical_notes TEXT")
    _add_col("ALTER TABLE PrePlans ADD COLUMN last_reviewed TEXT")
    _add_col("ALTER TABLE PrePlans ADD COLUMN is_active INTEGER DEFAULT 1")
    _add_col("ALTER TABLE PrePlans ADD COLUMN created TEXT")
    _add_col("ALTER TABLE PrePlans ADD COLUMN updated TEXT")

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
    # STATION ALERTING (Webhooks)
    # --------------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS StationAlerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            station_id TEXT,
            webhook_url TEXT NOT NULL,
            webhook_method TEXT DEFAULT 'POST',
            webhook_headers TEXT,
            webhook_template TEXT,
            trigger_on TEXT DEFAULT 'DISPATCH',
            unit_filter TEXT,
            incident_type_filter TEXT,
            is_active INTEGER DEFAULT 1,
            last_triggered TEXT,
            last_status INTEGER,
            created TEXT,
            updated TEXT
        )
    """)

    _add_col("ALTER TABLE StationAlerts ADD COLUMN name TEXT")
    _add_col("ALTER TABLE StationAlerts ADD COLUMN station_id TEXT")
    _add_col("ALTER TABLE StationAlerts ADD COLUMN webhook_url TEXT")
    _add_col("ALTER TABLE StationAlerts ADD COLUMN webhook_method TEXT DEFAULT 'POST'")
    _add_col("ALTER TABLE StationAlerts ADD COLUMN webhook_headers TEXT")
    _add_col("ALTER TABLE StationAlerts ADD COLUMN webhook_template TEXT")
    _add_col("ALTER TABLE StationAlerts ADD COLUMN trigger_on TEXT DEFAULT 'DISPATCH'")
    _add_col("ALTER TABLE StationAlerts ADD COLUMN unit_filter TEXT")
    _add_col("ALTER TABLE StationAlerts ADD COLUMN incident_type_filter TEXT")
    _add_col("ALTER TABLE StationAlerts ADD COLUMN is_active INTEGER DEFAULT 1")
    _add_col("ALTER TABLE StationAlerts ADD COLUMN last_triggered TEXT")
    _add_col("ALTER TABLE StationAlerts ADD COLUMN last_status INTEGER")
    _add_col("ALTER TABLE StationAlerts ADD COLUMN created TEXT")
    _add_col("ALTER TABLE StationAlerts ADD COLUMN updated TEXT")

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

    # --------------------------------------------------
    # HISTORY MODULE TABLES (Call History Viewer)
    # --------------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS history_saved_views (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            filters_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT,
            created_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS incident_exports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id INTEGER,
            format TEXT,
            artifact_path TEXT,
            created_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS incident_deliveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id INTEGER,
            channel TEXT,
            destination TEXT,
            payload_json TEXT,
            status TEXT DEFAULT 'pending',
            provider_id TEXT,
            error_text TEXT,
            created_at TEXT
        )
    """)
    _create_index("CREATE INDEX IF NOT EXISTS idx_incident_deliveries_incident ON incident_deliveries(incident_id)")

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

    try:
        from app.eventstream.emitter import emit_event
        emit_event("INCIDENT_DRAFT_CREATED", incident_id=incident_id, summary="Draft incident created")
    except Exception:
        pass

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
        # Build alpha part with dot separator: "A" + "2" → "A.2"
        alpha_part = pa
        if pad:
            alpha_part = f"{pa}.{pad}" if pa else pad
        # Build number part with dot separator: "33" + "5" → "33.5"
        num_part = pn
        if pnd:
            num_part = f"{pn}.{pnd}" if pn else pnd
        parts = [alpha_part.strip(), num_part.strip()]
        pole = " - ".join([p for p in parts if p]) if any(parts) else ""

    # Optional: store caller location into Incidents.address if provided
    address = (data.get("address") or data.get("caller_location") or "").strip()

    # Auto-detect shift from current time
    shift = determine_current_shift()

    # Enforce the type catalog
    raw_type = (data.get("type") or "").strip()
    type_key = normalize_incident_type(raw_type)
    if not type_key:
        allowed = ", ".join(sorted(INCIDENT_TYPE_KEYS))
        raise HTTPException(status_code=400, detail=f"Invalid incident type. Allowed: {allowed}")

    # Daily Log subtype support (only meaningful when type_key == "DAILY LOG")
    dailylog_subtype = (data.get("dailylog_subtype") or data.get("subtype") or "").strip()

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
                shift=?,
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
                shift,
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

    try:
        from app.eventstream.emitter import emit_event
        emit_event("INCIDENT_CREATED", incident_id=incident_id, user=user,
                   summary=f"Issued {incident_number}" if incident_number else "Opened")
    except Exception:
        pass

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

    # Look up pre-plan for this location
    preplan = None
    location = (incident["location"] or "").strip()
    if location:
        normalized = location.upper()
        # Try exact match first
        preplan_row = c.execute("""
            SELECT * FROM PrePlans
            WHERE is_active = 1
              AND UPPER(address) = ?
            LIMIT 1
        """, (normalized,)).fetchone()

        if not preplan_row:
            # Try partial match
            search_term = f"%{normalized}%"
            preplan_row = c.execute("""
                SELECT * FROM PrePlans
                WHERE is_active = 1
                  AND UPPER(address) LIKE ?
                ORDER BY LENGTH(address) ASC
                LIMIT 1
            """, (search_term,)).fetchone()

        if preplan_row:
            preplan = dict(preplan_row)

    # Get premise history (previous incidents at this location)
    premise_history = []
    premise_count = 0
    if location:
        hist_rows = c.execute("""
            SELECT incident_id, incident_number, type, status, created
            FROM Incidents
            WHERE incident_number IS NOT NULL
              AND UPPER(location) LIKE ?
              AND incident_id != ?
            ORDER BY created DESC
            LIMIT 5
        """, (f"%{normalized}%", incident_id)).fetchall()
        premise_history = [dict(r) for r in hist_rows]

        count_row = c.execute("""
            SELECT COUNT(*) as total FROM Incidents
            WHERE incident_number IS NOT NULL
              AND UPPER(location) LIKE ?
              AND incident_id != ?
        """, (f"%{normalized}%", incident_id)).fetchone()
        premise_count = count_row["total"] if count_row else 0

    # Get caller history (previous calls from this number)
    caller_history = []
    caller_count = 0
    caller_phone = (incident["caller_phone"] or "").strip()
    if caller_phone:
        digits_only = ''.join(filter(str.isdigit, caller_phone))
        if len(digits_only) >= 7:
            search_term = f"%{digits_only[-7:]}%"
            hist_rows = c.execute("""
                SELECT incident_id, incident_number, type, status, created, location
                FROM Incidents
                WHERE incident_number IS NOT NULL
                  AND caller_phone IS NOT NULL
                  AND (
                      REPLACE(REPLACE(REPLACE(REPLACE(caller_phone, '-', ''), '(', ''), ')', ''), ' ', '')
                      LIKE ?
                  )
                  AND incident_id != ?
                ORDER BY created DESC
                LIMIT 5
            """, (search_term, incident_id)).fetchall()
            caller_history = [dict(r) for r in hist_rows]

            count_row = c.execute("""
                SELECT COUNT(*) as total FROM Incidents
                WHERE incident_number IS NOT NULL
                  AND caller_phone IS NOT NULL
                  AND (
                      REPLACE(REPLACE(REPLACE(REPLACE(caller_phone, '-', ''), '(', ''), ')', ''), ' ', '')
                      LIKE ?
                  )
                  AND incident_id != ?
            """, (search_term, incident_id)).fetchone()
            caller_count = count_row["total"] if count_row else 0

    conn.close()

    # Get NFIRS completeness status
    nfirs_status = get_nfirs_completeness(incident_id)

    # --- Incident Chat Channel ---
    incident_chat_channel_id = None
    incident_chat_messages = []
    try:
        from app.messaging.chat_engine import get_chat_engine
        _chat = get_chat_engine()
        user_id = request.session.get("unit_id") or request.session.get("user") or "DISPATCH"
        _ch = _chat.get_or_create_incident_channel(incident_id, title=f"Incident #{incident_id}")
        incident_chat_channel_id = _ch["id"]
        # Auto-join assigned units + dispatcher
        _chat.add_member(_ch["id"], "unit", user_id, display_name=user_id)
        for u in units:
            _chat.add_member(_ch["id"], "unit", u["unit_id"], display_name=u.get("unit_name") or u["unit_id"])
        incident_chat_messages = _chat.get_messages(_ch["id"], limit=20)
    except Exception as _ce:
        print(f"[IAW] Chat channel setup: {_ce}")

    return templates.TemplateResponse(
        "iaw/incident_action_window.html",
        {
            "request": request,
            "incident": dict(incident),
            "units": [dict(u) for u in units],
            "narrative": [dict(n) for n in narrative],
            "preplan": preplan,
            "premise_history": premise_history,
            "premise_count": premise_count,
            "caller_history": caller_history,
            "caller_count": caller_count,
            "nfirs_status": nfirs_status,
            "incident_chat_channel_id": incident_chat_channel_id,
            "incident_chat_messages": incident_chat_messages,
            "user_id": request.session.get("unit_id") or request.session.get("user") or "DISPATCH",
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

    # Get incident type for response plan recommendations
    incident_type = None
    recommended_units = []
    try:
        inc_row = c.execute("SELECT type FROM Incidents WHERE incident_id = ?", (incident_id,)).fetchone()
        if inc_row and inc_row["type"]:
            incident_type = inc_row["type"].upper().strip()

            # Get recommended units from response plans
            plans = c.execute("""
                SELECT units FROM ResponsePlans
                WHERE is_active = 1
                  AND (incident_type = ? OR incident_type = 'DEFAULT' OR ? LIKE incident_type || '%')
                ORDER BY
                    CASE WHEN incident_type = ? THEN 0 ELSE 1 END,
                    alarm_level ASC,
                    priority DESC
                LIMIT 5
            """, (incident_type, incident_type, incident_type)).fetchall()

            # Build recommended units list
            seen = set()
            for plan in plans:
                for unit_id in (plan["units"] or "").split(","):
                    unit_id = unit_id.strip()
                    if unit_id and unit_id not in seen and unit_id not in assigned_to_incident:
                        seen.add(unit_id)
                        # Find unit details
                        unit_info = next((u for u in eligible if u.get("unit_id") == unit_id), None)
                        if unit_info:
                            recommended_units.append(unit_info)
    except Exception:
        pass
    finally:
        conn.close()

    return templates.TemplateResponse(
        "modals/dispatch_picker.html",
        {
            "request": request,
            "incident_id": incident_id,
            "incident_type": incident_type,
            "recommended_units": recommended_units,
            "command_units": groups["command"],
            "personnel_units": groups["personnel"],
            "apparatus_units": groups["apparatus"],
            "mutual_aid_units": groups["mutual_aid"],
            "login_required": False,
            "shift_letter": shift_letter,
        },
    )


def _load_unit_for_uaw(unit_id: str):
    """Load unit data for UAW modal."""
    conn = get_conn()
    c = conn.cursor()
    unit = c.execute(
        "SELECT * FROM Units WHERE unit_id = ?", (unit_id,)
    ).fetchone()
    if not unit:
        conn.close()
        return None, None

    # Find active incident if any
    active = c.execute("""
        SELECT incident_id FROM UnitAssignments
        WHERE unit_id = ? AND cleared IS NULL
        ORDER BY assigned DESC LIMIT 1
    """, (unit_id,)).fetchone()

    conn.close()
    return dict(unit), active["incident_id"] if active else None


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
      - Shifts rotate every 2 days:
        Day 0: A (day), B (night)
        Day 1: C (day), D (night)
        Day 2: A (day), B (night) ... repeats

    Reference date: Feb 2, 2026 is A shift (day)
    """
    # Try to use reports module if available for consistency
    try:
        import reports
        return reports.get_current_shift()
    except ImportError:
        pass

    # Fallback calculation
    now_dt = datetime.datetime.now()
    hour = now_dt.hour
    current_date = now_dt.date()

    # Reference date when A shift started (day shift)
    ref_date = datetime.date(2026, 2, 2)

    # Night shift spans two calendar days (1800-0600)
    # If it's between 0000-0600, we're still on the previous day's night shift
    if hour < 6:
        current_date = current_date - datetime.timedelta(days=1)
        is_night = True
    elif hour >= 18:
        is_night = True
    else:
        is_night = False

    # Calculate days since reference date
    days_diff = (current_date - ref_date).days

    # Each calendar day has 2 shifts (day and night)
    # shift_index cycles 0, 1, 2, 3 (A, B, C, D)
    # Day 0 (even): A(day=0), B(night=1)
    # Day 1 (odd): C(day=2), D(night=3)
    day_in_cycle = days_diff % 2
    shift_index = (day_in_cycle * 2) + (1 if is_night else 0)

    rotation = ["A", "B", "C", "D"]
    return rotation[shift_index]


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
               COALESCE(custom_status,'') AS custom_status,
               COALESCE(display_order, 999) AS display_order,
               COALESCE(department,'') AS department
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

    _ma_type_order = {"fire": 0, "ems": 1, "helicopter": 2, "police": 3, "ema": 4, "animal_control": 5}
    mutual_aid_sorted = sorted(mutual_aid, key=lambda x: (
        _ma_type_order.get((x.get("unit_type") or "").lower(), 99),
        (x.get("department") or ""),
        (x.get("unit_id") or "")
    ))

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
      1) Command units pinned (canonical fixed order): 1578, Car1, Batt1–Batt4
      2) Personnel (two-digit IDs) - sorted by display_order, then by unit_id
      3) Apparatus - sorted by display_order, then by APPARATUS_ORDER fallback
      4) Mutual aid last
      5) Any other units (fallback) last

    Notes:
      - This function ONLY orders units; filtering for "available" happens in /panel/units.
      - Always attaches metadata so templates can rely on keys.
      - display_order from database takes priority when set (< 999)
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

    # Sort by display_order first (if set), then by legacy index/name
    def _get_display_order(x: dict) -> int:
        return int(x.get("display_order") or 999)

    def _cmd_sort_key(x: dict) -> tuple:
        uid = (x.get("unit_id") or "").strip()
        # Command units ALWAYS sort by canonical COMMAND_IDS order
        # (1578=0, Car1=1, Batt1=2, Batt2=3, Batt3=4, Batt4=5)
        return (command_index.get(uid, 999),)

    cmd.sort(key=_cmd_sort_key)

    def _personnel_sort_key(x: dict) -> tuple:
        uid = (x.get("unit_id") or "").strip()
        display_order = _get_display_order(x)
        numeric_order = int(uid) if uid.isdigit() and len(uid) == 2 else 999
        # If display_order is custom (< 999), use it; otherwise use numeric
        if display_order < 999:
            return (display_order, numeric_order)
        return (numeric_order, 0)

    personnel.sort(key=_personnel_sort_key)

    def _apparatus_sort_key(x: dict) -> tuple:
        uid = (x.get("unit_id") or "").strip()
        display_order = _get_display_order(x)
        legacy_order = apparatus_index.get(uid, 999)
        # If display_order is custom (< 999), use it; otherwise use legacy
        if display_order < 999:
            return (display_order, legacy_order)
        return (legacy_order, 0)

    apparatus.sort(key=_apparatus_sort_key)
    _ma_type_order_panel = {"fire": 0, "ems": 1, "helicopter": 2, "police": 3, "ema": 4, "animal_control": 5}
    mutual.sort(key=lambda x: (
        _ma_type_order_panel.get((x.get("unit_type") or "").lower(), 99),
        (x.get("department") or ""),
        (x.get("unit_id") or "")
    ))
    other.sort(key=lambda x: (_get_display_order(x), x.get("unit_id") or ""))

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
        # --- Chat event: DISPATCH ---
        try:
            from app.messaging.chat_engine import get_chat_engine, post_cad_event_to_chat
            for uid in result.get("assigned", []):
                post_cad_event_to_chat(get_chat_engine(), incident_id, "DISPATCH", unit_id=uid, user=user)
        except Exception:
            pass
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
    "AVAILABLE",
    "OOS",
    "ON_SCENE",
    "OPERATING",
    "BUSY",
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


    # --- Chat event helper ---
    def _chat_event(evt):
        try:
            from app.messaging.chat_engine import get_chat_engine, post_cad_event_to_chat
            post_cad_event_to_chat(get_chat_engine(), incident_id, evt, unit_id=unit_id, user=user)
        except Exception:
            pass

    # --- Event Stream helper (never breaks caller) ---
    def _emit_status(evt):
        try:
            from app.eventstream.emitter import emit_event
            emit_event(evt, incident_id=incident_id, unit_id=unit_id, user=user,
                       summary=f"{unit_id} {evt.lower()}")
        except Exception:
            pass

    # DISPATCHED
    if new_status == "DISPATCHED":
        set_unit_status_pipeline(unit_id, "DISPATCHED")
        mark_assignment(incident_id, unit_id, "dispatched")
        incident_history(incident_id, "DISPATCHED", user=user, unit_id=unit_id)
        _mirror_to_crew("dispatched")
        _chat_event("DISPATCH")
        _emit_status("DISPATCHED")
        return {"ok": True}

    if new_status == "ENROUTE":
        set_unit_status_pipeline(unit_id, "ENROUTE")
        mark_assignment(incident_id, unit_id, "enroute")
        incident_history(incident_id, "ENROUTE", user=user, unit_id=unit_id)
        _mirror_to_crew("enroute")
        _chat_event("ENROUTE")
        _emit_status("ENROUTE")

    elif new_status == "ARRIVED":
        set_unit_status_pipeline(unit_id, "ARRIVED")
        mark_assignment(incident_id, unit_id, "arrived")
        incident_history(incident_id, "ARRIVED", user=user, unit_id=unit_id)
        _mirror_to_crew("arrived")
        _chat_event("ARRIVED")
        _emit_status("ARRIVED")

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
        _emit_status("TRANSPORTING")

    elif new_status == "AT_MEDICAL":
        set_unit_status_pipeline(unit_id, "AT_MEDICAL")
        mark_assignment(incident_id, unit_id, "at_medical")
        incident_history(incident_id, "AT_MEDICAL", user=user, unit_id=unit_id)
        _mirror_to_crew("at_medical")
        _emit_status("AT_MEDICAL")

    elif new_status == "EMERGENCY":
        set_unit_status_pipeline(unit_id, "EMERGENCY")
        incident_history(incident_id, "EMERGENCY", user=user, unit_id=unit_id)
        _mirror_to_crew()
        _emit_status("EMERGENCY")

    elif new_status == "UNAVAILABLE":
        set_unit_status_pipeline(unit_id, "UNAVAILABLE")
        incident_history(incident_id, "UNAVAILABLE", user=user, unit_id=unit_id)
        _mirror_to_crew()
        _emit_status("UNAVAILABLE")

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
        _emit_status("CLEARED")

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

        # ---- Auto-clear all remaining units with this disposition -----------
        import datetime as _dt
        now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if dispo != "H":
            # Clear all uncleared units and set their disposition
            if "cleared" in ua_cols:
                c.execute(f"""
                    UPDATE UnitAssignments
                    SET cleared = ?, disposition = ?
                    WHERE incident_id = ? AND {cleared_expr}
                """, (now, dispo, incident_id))
            elif "cleared_at" in ua_cols:
                c.execute(f"""
                    UPDATE UnitAssignments
                    SET cleared_at = ?, disposition = ?
                    WHERE incident_id = ? AND {cleared_expr}
                """, (now, dispo, incident_id))
            # Reset unit statuses to AVAILABLE
            c.execute("""
                UPDATE Units SET status = 'AVAILABLE', last_updated = ?
                WHERE unit_id IN (
                    SELECT unit_id FROM UnitAssignments WHERE incident_id = ?
                )
            """, (now, incident_id))

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

        # Check NFIRS completeness on close
        nfirs_warning = None
        if resulting_status == "CLOSED":
            nfirs_completeness = get_nfirs_completeness(incident_id)
            if nfirs_completeness.get("status") == "red":
                nfirs_warning = "NFIRS data incomplete - missing required fields"
                # Log the incomplete NFIRS closure
                try:
                    masterlog(
                        event_type="NFIRS_INCOMPLETE_CLOSE",
                        incident_id=incident_id,
                        ok=1,
                        details=f"Incident closed with incomplete NFIRS: {nfirs_completeness.get('missing_required', [])}"
                    )
                except Exception:
                    pass  # Don't fail the close due to logging

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail={"ok": False, "error": str(e)})
    finally:
        conn.close()

    response = {
        "ok": True,
        "incident_id": incident_id,
        "disposition": dispo,
        "remaining_units": int(remaining),
        "status": resulting_status,
    }

    if nfirs_warning:
        response["nfirs_warning"] = nfirs_warning

    return response


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
                user,
                dl_number
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
                user,
                dl_number
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
            "rows": entries,
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


def dispatch_units_to_incident(incident_id: int, units: list[str], user: str, force: bool = False):
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
                if force:
                    # Auto-clear from previous incident (self-initiate / reassign)
                    c.execute("""
                        UPDATE UnitAssignments SET cleared = ?
                        WHERE unit_id = ? AND cleared IS NULL AND incident_id <> ?
                    """, (ts, unit_id, incident_id))
                else:
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

    try:
        from app.eventstream.emitter import emit_event
        for u in assigned:
            emit_event("UNIT_DISPATCHED", incident_id=incident_id, unit_id=u, user=user,
                       summary=f"{u} dispatched")
    except Exception:
        pass

    return {"ok": True, "assigned": assigned, "skipped": skipped}



@app.post("/dispatch/unit_to_incident")
async def dispatch_unit_endpoint(request: Request):
    data = await request.json()

    incident_id = data.get("incident_id")
    units = data.get("units", [])

    if not incident_id or not isinstance(units, list) or not units:
        return {"ok": False, "error": "Invalid dispatch payload"}

    user = request.session.get("user", "Dispatcher")

    result = dispatch_units_to_incident(
        incident_id=int(incident_id),
        units=units,
        user=user,
    )

    # Fire station alerts for successful dispatches
    if result.get("ok") and result.get("assigned"):
        try:
            conn = get_conn()
            incident = conn.execute("SELECT * FROM Incidents WHERE incident_id = ?", (incident_id,)).fetchone()
            conn.close()
            if incident:
                import asyncio
                asyncio.create_task(fire_station_alerts("DISPATCH", dict(incident), result["assigned"]))
        except Exception as e:
            print(f"[STATION_ALERT] Error triggering alerts: {e}")

    return result


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

VALID_UNIT_STATUSES_IAW = {
    "ENROUTE",
    "ARRIVED",
    "TRANSPORT",
    "TRANSPORTING",
    "AT_MEDICAL",
    "CLEARED",
    "AVAILABLE",
    "OOS",
    "ON_SCENE",
    "OPERATING",
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

    # --- Chat event: CLEAR ---
    try:
        from app.messaging.chat_engine import get_chat_engine, post_cad_event_to_chat
        post_cad_event_to_chat(get_chat_engine(), incident_id, "CLEAR", unit_id=unit_id, user=user,
                               details=f"{disposition} ({VALID_DISPOSITIONS_LEGACY_CLEAR[disposition]})")
    except Exception:
        pass

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

    # --- Chat event: CLOSE ---
    try:
        from app.messaging.chat_engine import get_chat_engine, post_cad_event_to_chat
        post_cad_event_to_chat(get_chat_engine(), incident_id, "CLOSE", user=user,
                               details=f"{code} ({EVENT_OUTCOME_MAP.get(code, '')})")
    except Exception:
        pass

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
            dl.dl_number,
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

    try:
        from app.eventstream.emitter import emit_event
        emit_event("INCIDENT_CLOSED", incident_id=incident_id,
                   summary="Incident automatically closed (all units cleared)")
    except Exception:
        pass


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

    try:
        from app.eventstream.emitter import emit_event
        emit_event("INCIDENT_CLOSED_MANUAL", incident_id=incident_id, user=user,
                   summary=f"Closed with disposition: {disposition}, {len(units)} units cleared")
    except Exception:
        pass

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

    # Dispatch (force=True allows reassignment for self-initiated/CLI dispatch)
    force = mode in ("D", "SI", "F", "FORCE")
    res = dispatch_units_to_incident(int(incident_id), units, user="CLI", force=force)

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
    incident_history(incident_id, "CLEARED", user=user, unit_id=unit_id, details=f"Disposition: {disposition}" if disposition else "")

    try:
        from app.eventstream.emitter import emit_event
        emit_event("UNIT_CLEARED", incident_id=incident_id, unit_id=unit_id, user=user,
                   summary=f"{unit_id} cleared" + (f" ({disposition})" if disposition else ""))
    except Exception:
        pass

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
    Accepts optional disposition parameter to apply to command unit (and all units if desired).
    """
    ensure_phase3_schema()
    data = await request.json()
    incident_id = int(data.get("incident_id") or 0)
    disposition = (data.get("disposition") or "").strip().upper()
    remark = (data.get("remark") or data.get("comment") or "").strip()

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

    # If disposition provided, apply it to command unit (and optionally all units)
    if disposition and cmd_unit:
        c.execute("""
            UPDATE UnitAssignments
            SET disposition = ?
            WHERE incident_id = ? AND unit_id = ?
        """, (disposition, incident_id, cmd_unit))
        conn.commit()

    # Apply disposition to all units if provided
    if disposition:
        for r in unit_rows:
            uid = r["unit_id"]
            # Only set if not already set
            c.execute("""
                UPDATE UnitAssignments
                SET disposition = ?
                WHERE incident_id = ? AND unit_id = ? AND (disposition IS NULL OR disposition = '')
            """, (disposition, incident_id, uid))
        conn.commit()

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

    # Auto-expire shift overrides from previous shifts
    try:
        expire_stale_shift_overrides()
    except Exception:
        pass  # Don't fail panel load if cleanup fails

    # Ghost assignment cleanup: clear assignments on closed incidents, reset unit status
    try:
        _gc = get_conn()
        _gc_ts = _ts()
        _gc.execute("""
            UPDATE UnitAssignments SET cleared = ?
            WHERE cleared IS NULL
              AND incident_id IN (SELECT incident_id FROM Incidents WHERE status = 'CLOSED')
        """, (_gc_ts,))
        _gc.execute("""
            UPDATE Units SET status = 'AVAILABLE', last_updated = ?
            WHERE status != 'AVAILABLE'
              AND unit_id NOT IN (SELECT unit_id FROM UnitAssignments WHERE cleared IS NULL)
        """, (_gc_ts,))
        _gc.commit()
        _gc.close()
    except Exception:
        pass

    ensure_phase3_schema()
    conn = get_conn()
    try:
        # Use get_units_for_panel() for proper categorization and sorting
        rows = get_units_for_panel()

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
    """Reports modal - 4-tab reporting system (Run, Builder, Scheduled, History)."""
    return templates.TemplateResponse(
        "modals/reporting_modal.html",
        {"request": request},
    )


@app.get("/modals/reports_admin", response_class=HTMLResponse)
async def reports_admin_modal(request: Request):
    """Reports Administration modal - comprehensive report configuration."""
    return templates.TemplateResponse(
        "modals/reports_admin_modal.html",
        {"request": request},
    )


@app.get("/admin/reports", response_class=HTMLResponse)
async def admin_reports_page(request: Request):
    """Reports Administration full page - state-of-the-art v2 reporting system."""
    return templates.TemplateResponse(
        "admin/reports.html",
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


@app.get("/modals/keyboard_help", response_class=HTMLResponse)
async def keyboard_help_modal(request: Request):
    """Keyboard shortcuts help modal."""
    return templates.TemplateResponse(
        "modals/keyboard_help_modal.html",
        {"request": request},
    )


@app.get("/incident/{incident_id}/nfirs", response_class=HTMLResponse)
async def nfirs_modal(request: Request, incident_id: int):
    """NFIRS/NERIS data entry modal for an incident."""
    ensure_phase3_schema()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("SELECT * FROM Incidents WHERE incident_id = ?", (incident_id,))
    row = c.fetchone()
    conn.close()

    if not row:
        return HTMLResponse("<div class='modal-content'><p>Incident not found.</p></div>", status_code=404)

    incident = dict(row)
    return templates.TemplateResponse(
        "modals/nfirs_modal.html",
        {"request": request, "incident": incident},
    )


def validate_nfirs_data(body: dict) -> list:
    """
    Validate NFIRS data based on incident type.
    Returns list of error messages (empty if valid).
    """
    errors = []
    type_code = body.get("nfirs_type_code")

    # Basic module - always required
    if not type_code:
        errors.append("NFIRS Incident Type Code is required")
        return errors  # Can't validate further without type

    try:
        code = int(type_code)
    except (ValueError, TypeError):
        errors.append("Invalid NFIRS Incident Type Code")
        return errors

    # Fire module - required for types 100-173
    if 100 <= code <= 173:
        if not body.get("fire_cause"):
            errors.append("Cause of Ignition is required for fire incidents")
        if not body.get("fire_spread"):
            errors.append("Extent of Fire Spread is required for fire incidents")

    # EMS module - required for types 300-381
    if 300 <= code <= 381:
        if not body.get("patient_disposition"):
            errors.append("Patient Disposition is required for EMS incidents")

    return errors


def get_nfirs_completeness(incident_id: int) -> dict:
    """
    Calculate NFIRS completeness for an incident.
    Returns dict with: complete (bool), score (0-100), missing (list of field names), status (green/yellow/red)
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("SELECT * FROM Incidents WHERE incident_id = ?", (incident_id,))
    row = c.fetchone()
    conn.close()

    if not row:
        return {"complete": False, "score": 0, "missing": [], "status": "red"}

    incident = dict(row)
    type_code = incident.get("nfirs_type_code")

    if not type_code:
        return {
            "complete": False,
            "score": 0,
            "missing": ["nfirs_type_code"],
            "status": "red"
        }

    try:
        code = int(type_code)
    except (ValueError, TypeError):
        return {
            "complete": False,
            "score": 0,
            "missing": ["nfirs_type_code (invalid)"],
            "status": "red"
        }

    required_fields = ["nfirs_type_code"]
    optional_fields = ["property_use_code", "aid_given_received", "shift", "actions_taken"]

    # Fire-specific fields
    if 100 <= code <= 173:
        required_fields.extend(["fire_cause", "fire_spread"])
        optional_fields.extend([
            "fire_origin_area", "heat_source", "item_first_ignited",
            "structure_type", "detector_present", "aes_present",
            "property_loss", "contents_loss"
        ])

    # EMS-specific fields
    if 300 <= code <= 381:
        required_fields.append("patient_disposition")
        optional_fields.extend(["patient_count", "transport_count", "destination"])

    # Check required fields
    missing_required = []
    for field in required_fields:
        val = incident.get(field)
        if not val or (isinstance(val, str) and val.strip() == ""):
            missing_required.append(field)

    # Check optional fields
    missing_optional = []
    for field in optional_fields:
        val = incident.get(field)
        if not val or (isinstance(val, str) and val.strip() == ""):
            missing_optional.append(field)

    # Calculate score
    total_fields = len(required_fields) + len(optional_fields)
    filled_fields = total_fields - len(missing_required) - len(missing_optional)
    score = int((filled_fields / total_fields) * 100) if total_fields > 0 else 0

    # Determine status
    if missing_required:
        status = "red"
        complete = False
    elif missing_optional:
        status = "yellow"
        complete = True  # Required fields are filled
    else:
        status = "green"
        complete = True

    return {
        "complete": complete,
        "score": score,
        "missing": missing_required + missing_optional,
        "missing_required": missing_required,
        "missing_optional": missing_optional,
        "status": status
    }


@app.post("/api/incident/{incident_id}/nfirs")
async def save_nfirs_data(request: Request, incident_id: int):
    """Save NFIRS/NERIS compliance data for an incident."""
    ensure_phase3_schema()
    body = await request.json()

    # Validate required fields based on incident type
    validation_errors = validate_nfirs_data(body)
    if validation_errors:
        return {"ok": False, "errors": validation_errors}

    # List of NFIRS fields to update
    nfirs_fields = [
        "nfirs_type_code", "property_use_code", "actions_taken", "aid_given_received",
        "shift", "alarm_time", "arrival_time", "controlled_time", "last_unit_cleared",
        "fire_origin_area", "heat_source", "item_first_ignited", "fire_cause", "fire_spread",
        "structure_type", "building_status", "stories_above_grade", "stories_below_grade",
        "detector_present", "detector_type", "detector_worked",
        "aes_present", "aes_type", "aes_worked",
        "property_loss", "contents_loss", "property_value", "contents_value",
        "civilian_injuries", "civilian_deaths", "ff_injuries", "ff_deaths",
        "patient_count", "transport_count", "destination", "patient_disposition",
        "weather_conditions", "road_conditions", "special_circumstances"
    ]

    # Build update query dynamically
    updates = []
    values = []
    for field in nfirs_fields:
        if field in body:
            updates.append(f"{field} = ?")
            val = body[field]
            # Handle empty strings as NULL for optional fields
            if val == "" or val is None:
                values.append(None)
            else:
                values.append(val)

    if not updates:
        return {"ok": False, "error": "No fields to update"}

    values.append(incident_id)
    sql = f"UPDATE Incidents SET {', '.join(updates)}, updated = ? WHERE incident_id = ?"
    values.insert(-1, datetime.datetime.now(datetime.timezone.utc).isoformat())

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(sql, values)
        conn.commit()
        conn.close()

        # Log the action
        user = request.session.get("user", "system")
        masterlog(event_type="NFIRS_DATA_UPDATED", user=user, incident_id=incident_id, ok=1, details=f"Updated {len(updates)} NFIRS fields")
        incident_history(incident_id=incident_id, event_type="NFIRS_DATA_UPDATED", user=user, details=f"NFIRS data updated")

        # Return completeness info with success
        completeness = get_nfirs_completeness(incident_id)
        return {"ok": True, "completeness": completeness}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/incident/{incident_id}/nfirs/export")
async def export_nfirs_data(request: Request, incident_id: int):
    """Export NFIRS data for a single incident as JSON."""
    ensure_phase3_schema()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("SELECT * FROM Incidents WHERE incident_id = ?", (incident_id,))
    row = c.fetchone()
    conn.close()

    if not row:
        return {"ok": False, "error": "Incident not found"}

    incident = dict(row)

    # Build NFIRS-formatted export
    nfirs_export = {
        "header": {
            "state": "KY",  # Configure as needed
            "fdid": "BOSK",  # BlueOval SK Fire Department ID
            "incident_number": incident.get("incident_number"),
            "exposure": 0,
        },
        "basic_module": {
            "incident_type": incident.get("nfirs_type_code"),
            "incident_date": incident.get("created", "")[:10] if incident.get("created") else None,
            "alarm_time": incident.get("alarm_time"),
            "arrival_time": incident.get("arrival_time"),
            "controlled_time": incident.get("controlled_time"),
            "last_unit_cleared": incident.get("last_unit_cleared"),
            "shift": incident.get("shift"),
            "aid_given_received": incident.get("aid_given_received"),
            "actions_taken": incident.get("actions_taken"),
            "property_use": incident.get("property_use_code"),
            "location": {
                "address": incident.get("address") or incident.get("location"),
                "node": incident.get("node"),
                "pole": incident.get("pole"),
            },
        },
        "fire_module": {
            "cause": incident.get("fire_cause"),
            "fire_spread": incident.get("fire_spread"),
            "origin_area": incident.get("fire_origin_area"),
            "heat_source": incident.get("heat_source"),
            "item_first_ignited": incident.get("item_first_ignited"),
            "structure_type": incident.get("structure_type"),
            "stories_above": incident.get("stories_above_grade"),
            "stories_below": incident.get("stories_below_grade"),
            "detector_present": incident.get("detector_present"),
            "detector_worked": incident.get("detector_worked"),
            "aes_present": incident.get("aes_present"),
            "aes_type": incident.get("aes_type"),
            "aes_worked": incident.get("aes_worked"),
        },
        "ems_module": {
            "patient_count": incident.get("patient_count"),
            "transport_count": incident.get("transport_count"),
            "destination": incident.get("destination"),
            "patient_disposition": incident.get("patient_disposition"),
        },
        "casualties": {
            "civilian_injuries": incident.get("civilian_injuries") or 0,
            "civilian_deaths": incident.get("civilian_deaths") or 0,
            "ff_injuries": incident.get("ff_injuries") or 0,
            "ff_deaths": incident.get("ff_deaths") or 0,
        },
        "property_loss": {
            "property_loss": incident.get("property_loss"),
            "contents_loss": incident.get("contents_loss"),
            "property_value": incident.get("property_value"),
            "contents_value": incident.get("contents_value"),
        },
    }

    return {"ok": True, "nfirs": nfirs_export}


@app.get("/api/nfirs/export/csv")
async def export_nfirs_csv(
    request: Request,
    start_date: str = None,
    end_date: str = None,
    status: str = "CLOSED"
):
    """
    Export NFIRS data as CSV for state submission.
    Query params:
      - start_date: Filter incidents from date (YYYY-MM-DD)
      - end_date: Filter incidents to date (YYYY-MM-DD)
      - status: Filter by status (default: CLOSED)
    """
    import csv
    import io

    ensure_phase3_schema()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Build query
    where_clauses = ["incident_number IS NOT NULL", "nfirs_type_code IS NOT NULL"]
    params = []

    if status:
        where_clauses.append("status = ?")
        params.append(status.upper())

    if start_date:
        where_clauses.append("DATE(created) >= DATE(?)")
        params.append(start_date)

    if end_date:
        where_clauses.append("DATE(created) <= DATE(?)")
        params.append(end_date)

    where_sql = " AND ".join(where_clauses)
    c.execute(f"""
        SELECT * FROM Incidents
        WHERE {where_sql}
        ORDER BY created DESC
    """, params)

    rows = c.fetchall()
    conn.close()

    # NFIRS column mapping (database column -> NFIRS standard name)
    nfirs_columns = [
        ("fdid", "FDID"),
        ("state", "State"),
        ("incident_number", "Incident Number"),
        ("exposure", "Exposure"),
        ("created", "Incident Date"),
        ("nfirs_type_code", "Incident Type"),
        ("property_use_code", "Property Use"),
        ("aid_given_received", "Aid Given/Received"),
        ("location", "Street Address"),
        ("city", "City"),
        ("state_code", "State Code"),
        ("zip_code", "ZIP Code"),
        ("shift", "Shift"),
        ("alarm_time", "Alarm Time"),
        ("arrival_time", "Arrival Time"),
        ("controlled_time", "Controlled Time"),
        ("last_unit_cleared", "Last Unit Cleared"),
        ("actions_taken", "Actions Taken"),
        ("fire_cause", "Cause of Ignition"),
        ("fire_spread", "Fire Spread"),
        ("fire_origin_area", "Area of Fire Origin"),
        ("heat_source", "Heat Source"),
        ("item_first_ignited", "Item First Ignited"),
        ("structure_type", "Structure Type"),
        ("stories_above_grade", "Stories Above Grade"),
        ("stories_below_grade", "Stories Below Grade"),
        ("detector_present", "Detector Present"),
        ("detector_worked", "Detector Operated"),
        ("aes_present", "AES Present"),
        ("aes_type", "AES Type"),
        ("aes_worked", "AES Operated"),
        ("property_loss", "Property Loss"),
        ("contents_loss", "Contents Loss"),
        ("property_value", "Property Value"),
        ("contents_value", "Contents Value"),
        ("civilian_injuries", "Civilian Injuries"),
        ("civilian_deaths", "Civilian Deaths"),
        ("ff_injuries", "Firefighter Injuries"),
        ("ff_deaths", "Firefighter Deaths"),
        ("patient_count", "Patient Count"),
        ("transport_count", "Patients Transported"),
        ("patient_disposition", "Patient Disposition"),
        ("destination", "Transport Destination"),
    ]

    # Get agency settings for FDID and State
    fdid = "FORD"
    state = "KY"
    try:
        settings_conn = sqlite3.connect(DB_PATH)
        settings_conn.row_factory = sqlite3.Row
        sc = settings_conn.cursor()
        sc.execute("SELECT key, value FROM SystemSettings WHERE key IN ('fdid', 'state')")
        settings = {r["key"]: r["value"] for r in sc.fetchall()}
        settings_conn.close()
        fdid = settings.get("fdid", "FORD")
        state = settings.get("state", "KY")
    except Exception:
        pass  # Use defaults if settings table doesn't exist

    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)

    # Write header row
    writer.writerow([col[1] for col in nfirs_columns])

    # Write data rows
    for row in rows:
        incident = dict(row)
        csv_row = []
        for db_col, _ in nfirs_columns:
            if db_col == "fdid":
                csv_row.append(fdid)
            elif db_col == "state":
                csv_row.append(state)
            elif db_col == "exposure":
                csv_row.append("0")  # Single incident, no exposures
            elif db_col == "created":
                # Format date as YYYY-MM-DD
                val = incident.get("created", "")
                csv_row.append(val[:10] if val else "")
            elif db_col in ("city", "state_code", "zip_code"):
                # Extract from location if not separate
                csv_row.append(incident.get(db_col, ""))
            else:
                val = incident.get(db_col)
                csv_row.append(val if val is not None else "")
        writer.writerow(csv_row)

    # Create response
    csv_content = output.getvalue()
    output.close()

    # Generate filename with date range
    today = datetime.datetime.now().strftime("%Y%m%d")
    filename = f"NFIRS_Export_{today}.csv"

    from fastapi.responses import Response
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )


@app.get("/api/nfirs/completeness/{incident_id}")
async def api_nfirs_completeness(incident_id: int):
    """Get NFIRS completeness status for an incident."""
    ensure_phase3_schema()
    return get_nfirs_completeness(incident_id)


@app.get("/api/nfirs/stats")
async def api_nfirs_stats():
    """Get NFIRS compliance statistics for admin dashboard."""
    ensure_phase3_schema()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Total incidents with NFIRS data
    c.execute("""
        SELECT COUNT(*) as count FROM Incidents
        WHERE incident_number IS NOT NULL AND nfirs_type_code IS NOT NULL
    """)
    with_nfirs = c.fetchone()["count"]

    # Total closed incidents
    c.execute("""
        SELECT COUNT(*) as count FROM Incidents
        WHERE incident_number IS NOT NULL AND status = 'CLOSED'
    """)
    total_closed = c.fetchone()["count"]

    # Incidents missing required NFIRS fields (closed incidents without type code)
    c.execute("""
        SELECT COUNT(*) as count FROM Incidents
        WHERE incident_number IS NOT NULL
        AND status = 'CLOSED'
        AND (nfirs_type_code IS NULL OR nfirs_type_code = '')
    """)
    missing_type = c.fetchone()["count"]

    # Fire incidents missing required fire fields
    c.execute("""
        SELECT COUNT(*) as count FROM Incidents
        WHERE incident_number IS NOT NULL
        AND status = 'CLOSED'
        AND nfirs_type_code IS NOT NULL
        AND CAST(nfirs_type_code AS INTEGER) BETWEEN 100 AND 173
        AND (fire_cause IS NULL OR fire_cause = '' OR fire_spread IS NULL OR fire_spread = '')
    """)
    missing_fire = c.fetchone()["count"]

    # EMS incidents missing required EMS fields
    c.execute("""
        SELECT COUNT(*) as count FROM Incidents
        WHERE incident_number IS NOT NULL
        AND status = 'CLOSED'
        AND nfirs_type_code IS NOT NULL
        AND CAST(nfirs_type_code AS INTEGER) BETWEEN 300 AND 381
        AND (patient_disposition IS NULL OR patient_disposition = '')
    """)
    missing_ems = c.fetchone()["count"]

    conn.close()

    total_missing = missing_type + missing_fire + missing_ems
    compliance_pct = int(((total_closed - total_missing) / total_closed * 100)) if total_closed > 0 else 100

    return {
        "ok": True,
        "stats": {
            "total_with_nfirs": with_nfirs,
            "total_closed": total_closed,
            "missing_type_code": missing_type,
            "missing_fire_fields": missing_fire,
            "missing_ems_fields": missing_ems,
            "total_incomplete": total_missing,
            "compliance_percentage": compliance_pct
        }
    }


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
            dl.dl_number,
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

    # --- Chat event: HOLD ---
    try:
        from app.messaging.chat_engine import get_chat_engine, post_cad_event_to_chat
        post_cad_event_to_chat(get_chat_engine(), incident_id, "HOLD", user=user, details=reason)
    except Exception:
        pass

    try:
        from app.eventstream.emitter import emit_event
        emit_event("INCIDENT_HELD", incident_id=incident_id, user=user,
                   summary=f"Held: {reason}", severity="alert")
    except Exception:
        pass

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

    try:
        from app.eventstream.emitter import emit_event
        emit_event("INCIDENT_UNHOLD", incident_id=incident_id, user=user, summary=details)
    except Exception:
        pass

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

# Super-admins have full system access (agency config, admin user management, system reset)
# Default super-admins - can be extended via SystemSettings
SUPER_ADMIN_UNITS = {"1578", "17"}

def _is_admin(user: str) -> bool:
    """Check if user has admin access (operational admin)."""
    return (user or "").upper() in ADMIN_UNITS

def _is_super_admin(user: str) -> bool:
    """Check if user has super-admin access (system configuration)."""
    user_upper = (user or "").upper()
    if user_upper in SUPER_ADMIN_UNITS:
        return True
    # Also check SystemSettings for additional super-admins
    try:
        conn = get_conn()
        row = conn.execute(
            "SELECT value FROM SystemSettings WHERE key = 'super_admin_users'"
        ).fetchone()
        conn.close()
        if row and row["value"]:
            extra_admins = {u.strip().upper() for u in row["value"].split(",")}
            return user_upper in extra_admins
    except Exception:
        pass
    return False

def _get_user_permission_level(user: str) -> str:
    """
    Get permission level for a user.
    Returns: 'super_admin', 'admin', or 'user'
    """
    if _is_super_admin(user):
        return "super_admin"
    elif _is_admin(user):
        return "admin"
    return "user"


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
# RESPONSE PLANS (Run Cards) API
# ------------------------------------------------------

@app.get("/api/response_plans")
def get_response_plans():
    """Get all response plans."""
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()
    rows = c.execute("""
        SELECT id, name, incident_type, priority, units, alarm_level, time_of_day,
               location_pattern, is_active, notes, created, updated
        FROM ResponsePlans
        ORDER BY incident_type, alarm_level, priority DESC
    """).fetchall()
    conn.close()
    return {"ok": True, "plans": [dict(r) for r in rows]}


@app.get("/api/response_plans/{plan_id}")
def get_response_plan(plan_id: int):
    """Get a single response plan by ID."""
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()
    row = c.execute("SELECT * FROM ResponsePlans WHERE id = ?", (plan_id,)).fetchone()
    conn.close()
    if not row:
        return {"ok": False, "error": "Plan not found"}
    return {"ok": True, "plan": dict(row)}


@app.post("/api/response_plans")
async def create_response_plan(request: Request):
    """Create a new response plan."""
    ensure_phase3_schema()
    body = await request.json()

    name = body.get("name", "").strip()
    incident_type = body.get("incident_type", "").strip().upper()
    units = body.get("units", "").strip()  # Comma-separated unit IDs
    priority = int(body.get("priority", 0))
    alarm_level = int(body.get("alarm_level", 1))
    time_of_day = body.get("time_of_day", "").strip() or None  # DAY, NIGHT, or empty
    location_pattern = body.get("location_pattern", "").strip() or None
    is_active = 1 if body.get("is_active", True) else 0
    notes = body.get("notes", "").strip() or None

    if not name or not incident_type or not units:
        return {"ok": False, "error": "Name, incident_type, and units are required"}

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO ResponsePlans (name, incident_type, priority, units, alarm_level, time_of_day,
                                   location_pattern, is_active, notes, created, updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (name, incident_type, priority, units, alarm_level, time_of_day,
          location_pattern, is_active, notes, now, now))
    plan_id = c.lastrowid
    conn.commit()
    conn.close()

    user = request.session.get("user", "system")
    masterlog(event_type="RESPONSE_PLAN_CREATED", user=user, ok=1, details=f"Created plan '{name}' for {incident_type}")

    return {"ok": True, "id": plan_id}


@app.put("/api/response_plans/{plan_id}")
async def update_response_plan(request: Request, plan_id: int):
    """Update an existing response plan."""
    ensure_phase3_schema()
    body = await request.json()

    updates = []
    values = []

    for field in ["name", "incident_type", "units", "time_of_day", "location_pattern", "notes"]:
        if field in body:
            updates.append(f"{field} = ?")
            values.append(body[field] if body[field] else None)

    for field in ["priority", "alarm_level", "is_active"]:
        if field in body:
            updates.append(f"{field} = ?")
            values.append(int(body[field]))

    if not updates:
        return {"ok": False, "error": "No fields to update"}

    updates.append("updated = ?")
    values.append(datetime.datetime.now(datetime.timezone.utc).isoformat())
    values.append(plan_id)

    conn = get_conn()
    c = conn.cursor()
    c.execute(f"UPDATE ResponsePlans SET {', '.join(updates)} WHERE id = ?", values)
    conn.commit()
    conn.close()

    user = request.session.get("user", "system")
    masterlog(event_type="RESPONSE_PLAN_UPDATED", user=user, ok=1, details=f"Updated plan ID {plan_id}")

    return {"ok": True}


@app.delete("/api/response_plans/{plan_id}")
async def delete_response_plan(request: Request, plan_id: int):
    """Delete a response plan."""
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM ResponsePlans WHERE id = ?", (plan_id,))
    conn.commit()
    conn.close()

    user = request.session.get("user", "system")
    masterlog(event_type="RESPONSE_PLAN_DELETED", user=user, ok=1, details=f"Deleted plan ID {plan_id}")

    return {"ok": True}


@app.get("/api/response_plans/recommend/{incident_type}")
def recommend_units(incident_type: str, alarm_level: int = 1, time_of_day: str = None):
    """
    Get recommended units for a given incident type.
    Returns units from matching response plans, filtered by availability.
    """
    ensure_phase3_schema()
    incident_type = incident_type.upper().strip()

    # Determine time of day if not specified
    if not time_of_day:
        hour = datetime.datetime.now().hour
        time_of_day = "DAY" if 6 <= hour < 18 else "NIGHT"

    conn = get_conn()
    c = conn.cursor()

    # Find matching response plans
    # Priority: exact match > fuzzy match > default
    plans = c.execute("""
        SELECT id, name, units, alarm_level, time_of_day, priority
        FROM ResponsePlans
        WHERE is_active = 1
          AND (incident_type = ? OR incident_type = 'DEFAULT' OR ? LIKE incident_type || '%')
          AND (alarm_level <= ? OR alarm_level = 1)
          AND (time_of_day IS NULL OR time_of_day = '' OR time_of_day = ?)
        ORDER BY
            CASE WHEN incident_type = ? THEN 0 ELSE 1 END,
            alarm_level ASC,
            priority DESC
    """, (incident_type, incident_type, alarm_level, time_of_day, incident_type)).fetchall()

    # Get available units
    available_units = {r[0] for r in c.execute(
        "SELECT unit_id FROM Units WHERE status = 'AVAILABLE'"
    ).fetchall()}

    # Build recommended units list
    recommended = []
    seen_units = set()

    for plan in plans:
        plan_units = [u.strip() for u in (plan["units"] or "").split(",") if u.strip()]
        for unit in plan_units:
            if unit not in seen_units:
                seen_units.add(unit)
                is_available = unit in available_units
                recommended.append({
                    "unit_id": unit,
                    "available": is_available,
                    "plan_name": plan["name"],
                    "alarm_level": plan["alarm_level"]
                })

    conn.close()

    return {
        "ok": True,
        "incident_type": incident_type,
        "alarm_level": alarm_level,
        "time_of_day": time_of_day,
        "recommended": recommended,
        "plans_matched": len(plans)
    }


@app.get("/admin/response_plans", response_class=HTMLResponse)
async def admin_response_plans_page(request: Request):
    """Admin page for managing response plans."""
    return templates.TemplateResponse(
        "admin/response_plans.html",
        {"request": request}
    )


# ------------------------------------------------------
# ANALYTICS DASHBOARD
# ------------------------------------------------------

@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request):
    """Analytics dashboard page."""
    return templates.TemplateResponse(
        "admin/analytics.html",
        {"request": request}
    )


@app.get("/api/analytics")
async def get_analytics(
    period: str = "week",
    from_date: str = None,
    to_date: str = None
):
    """
    Get analytics data for the dashboard.
    Period: today, week, month, year, custom
    """
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()

    # Calculate date range
    now = datetime.datetime.now()
    if period == "today":
        start_date = now.replace(hour=0, minute=0, second=0).isoformat()
    elif period == "week":
        start_date = (now - datetime.timedelta(days=7)).isoformat()
    elif period == "month":
        start_date = (now - datetime.timedelta(days=30)).isoformat()
    elif period == "year":
        start_date = f"{now.year}-01-01T00:00:00"
    elif period == "custom" and from_date:
        start_date = f"{from_date}T00:00:00"
    else:
        start_date = (now - datetime.timedelta(days=7)).isoformat()

    end_date = to_date + "T23:59:59" if to_date else now.isoformat()

    # Total incidents
    total_row = c.execute("""
        SELECT COUNT(*) as total
        FROM Incidents
        WHERE incident_number IS NOT NULL
          AND created >= ? AND created <= ?
    """, (start_date, end_date)).fetchone()
    total_incidents = total_row["total"] if total_row else 0

    # Incidents by type
    type_rows = c.execute("""
        SELECT type, COUNT(*) as count
        FROM Incidents
        WHERE incident_number IS NOT NULL
          AND created >= ? AND created <= ?
        GROUP BY type
        ORDER BY count DESC
        LIMIT 8
    """, (start_date, end_date)).fetchall()

    type_labels = [r["type"] or "Unknown" for r in type_rows]
    type_data = [r["count"] for r in type_rows]

    # Incidents by hour
    hourly_data = [0] * 24
    hour_rows = c.execute("""
        SELECT substr(created, 12, 2) as hour, COUNT(*) as count
        FROM Incidents
        WHERE incident_number IS NOT NULL
          AND created >= ? AND created <= ?
        GROUP BY hour
    """, (start_date, end_date)).fetchall()

    for r in hour_rows:
        try:
            h = int(r["hour"])
            if 0 <= h < 24:
                hourly_data[h] = r["count"]
        except:
            pass

    # Timeline data (group by day or hour depending on period)
    if period == "today":
        # Group by hour
        timeline_rows = c.execute("""
            SELECT substr(created, 12, 2) as period, COUNT(*) as count
            FROM Incidents
            WHERE incident_number IS NOT NULL
              AND created >= ? AND created <= ?
            GROUP BY period
            ORDER BY period
        """, (start_date, end_date)).fetchall()
        timeline_labels = [f"{r['period']}:00" for r in timeline_rows]
    else:
        # Group by day
        timeline_rows = c.execute("""
            SELECT substr(created, 1, 10) as period, COUNT(*) as count
            FROM Incidents
            WHERE incident_number IS NOT NULL
              AND created >= ? AND created <= ?
            GROUP BY period
            ORDER BY period
        """, (start_date, end_date)).fetchall()
        timeline_labels = [r["period"] for r in timeline_rows]

    timeline_data = [r["count"] for r in timeline_rows]

    # Response times calculation
    response_times = []
    rt_rows = c.execute("""
        SELECT ua.dispatched, ua.enroute, ua.arrived,
               i.type
        FROM UnitAssignments ua
        JOIN Incidents i ON ua.incident_id = i.incident_id
        WHERE i.incident_number IS NOT NULL
          AND i.created >= ? AND i.created <= ?
          AND ua.dispatched IS NOT NULL
          AND ua.arrived IS NOT NULL
    """, (start_date, end_date)).fetchall()

    for r in rt_rows:
        try:
            dispatched = datetime.datetime.fromisoformat(r["dispatched"].replace("Z", "+00:00"))
            arrived = datetime.datetime.fromisoformat(r["arrived"].replace("Z", "+00:00"))
            total_seconds = (arrived - dispatched).total_seconds()
            if 0 < total_seconds < 3600:  # Sanity check: less than 1 hour
                response_times.append({
                    "total": total_seconds,
                    "type": r["type"] or "Unknown",
                    "dispatched": r["dispatched"],
                    "enroute": r["enroute"],
                    "arrived": r["arrived"]
                })
        except:
            pass

    # Calculate averages and percentiles
    avg_response_time = 0
    percentile_90 = 0
    if response_times:
        times = sorted([r["total"] for r in response_times])
        avg_response_time = sum(times) / len(times)
        idx_90 = int(len(times) * 0.9)
        percentile_90 = times[idx_90] if idx_90 < len(times) else times[-1]

    # Response time distribution
    response_distribution = [0, 0, 0, 0, 0]  # <4, 4-6, 6-8, 8-10, >10 minutes
    for r in response_times:
        mins = r["total"] / 60
        if mins < 4:
            response_distribution[0] += 1
        elif mins < 6:
            response_distribution[1] += 1
        elif mins < 8:
            response_distribution[2] += 1
        elif mins < 10:
            response_distribution[3] += 1
        else:
            response_distribution[4] += 1

    # Response times by type
    response_by_type = {}
    for r in response_times:
        t = r["type"]
        if t not in response_by_type:
            response_by_type[t] = {"times": [], "d2e": [], "e2a": []}
        response_by_type[t]["times"].append(r["total"])
        # Calculate dispatch to enroute
        if r["enroute"]:
            try:
                d = datetime.datetime.fromisoformat(r["dispatched"].replace("Z", "+00:00"))
                e = datetime.datetime.fromisoformat(r["enroute"].replace("Z", "+00:00"))
                response_by_type[t]["d2e"].append((e - d).total_seconds())
            except:
                pass
        # Calculate enroute to arrived
        if r["enroute"] and r["arrived"]:
            try:
                e = datetime.datetime.fromisoformat(r["enroute"].replace("Z", "+00:00"))
                a = datetime.datetime.fromisoformat(r["arrived"].replace("Z", "+00:00"))
                response_by_type[t]["e2a"].append((a - e).total_seconds())
            except:
                pass

    response_by_type_list = []
    for t, data in response_by_type.items():
        times = sorted(data["times"])
        d2e = data["d2e"]
        e2a = data["e2a"]
        response_by_type_list.append({
            "type": t,
            "count": len(times),
            "avg_total": sum(times) / len(times) if times else 0,
            "avg_dispatch_to_enroute": sum(d2e) / len(d2e) if d2e else 0,
            "avg_enroute_to_arrived": sum(e2a) / len(e2a) if e2a else 0,
            "percentile_90": times[int(len(times) * 0.9)] if times else 0
        })
    response_by_type_list.sort(key=lambda x: x["count"], reverse=True)

    # Unit utilization (runs per unit)
    unit_rows = c.execute("""
        SELECT ua.unit_id, COUNT(*) as runs
        FROM UnitAssignments ua
        JOIN Incidents i ON ua.incident_id = i.incident_id
        WHERE i.incident_number IS NOT NULL
          AND i.created >= ? AND i.created <= ?
        GROUP BY ua.unit_id
        ORDER BY runs DESC
        LIMIT 15
    """, (start_date, end_date)).fetchall()

    unit_labels = [r["unit_id"] for r in unit_rows]
    unit_data = [r["runs"] for r in unit_rows]

    # Active units count
    active_units = c.execute("SELECT COUNT(*) FROM Units WHERE status != 'UNAVAILABLE'").fetchone()[0]

    # Total transports
    transport_count = c.execute("""
        SELECT COUNT(DISTINCT incident_id)
        FROM UnitAssignments
        WHERE transporting IS NOT NULL
    """).fetchone()[0]

    conn.close()

    return {
        "ok": True,
        "period": period,
        "start_date": start_date,
        "end_date": end_date,
        "total_incidents": total_incidents,
        "avg_response_time": round(avg_response_time, 1),
        "percentile_90": round(percentile_90, 1),
        "active_units": active_units,
        "total_transports": transport_count,
        "type_labels": type_labels,
        "type_data": type_data,
        "hourly_data": hourly_data,
        "timeline_labels": timeline_labels,
        "timeline_data": timeline_data,
        "response_distribution": response_distribution,
        "unit_labels": unit_labels,
        "unit_data": unit_data,
        "response_by_type": response_by_type_list
    }


# ------------------------------------------------------
# MOBILE MDT INTERFACE
# ------------------------------------------------------

@app.get("/mobile/mdt/{unit_id}", response_class=HTMLResponse)
async def mobile_mdt(request: Request, unit_id: str):
    """
    Mobile Data Terminal interface for apparatus tablets.
    Touch-optimized view for a single unit's dispatch operations.
    """
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()

    # Get unit info
    unit_row = c.execute("SELECT * FROM Units WHERE unit_id = ?", (unit_id,)).fetchone()
    if not unit_row:
        conn.close()
        return HTMLResponse(f"<h1>Unit {unit_id} not found</h1><a href='/'>Back to CAD</a>", status_code=404)

    current_status = unit_row["status"] or "AVAILABLE"

    # Find active incident assignment for this unit
    assignment = c.execute("""
        SELECT ua.*, i.incident_id, i.incident_number, i.type, i.location, i.priority,
               i.caller_name, i.caller_phone, i.node, i.pole, i.narrative, i.status as incident_status
        FROM UnitAssignments ua
        JOIN Incidents i ON ua.incident_id = i.incident_id
        WHERE ua.unit_id = ?
          AND ua.cleared IS NULL
          AND i.status IN ('OPEN', 'ACTIVE')
        ORDER BY ua.dispatched DESC
        LIMIT 1
    """, (unit_id,)).fetchone()

    incident = None
    if assignment:
        incident = dict(assignment)
        # Determine current status from assignment
        if assignment["cleared"]:
            current_status = "CLEARED"
        elif assignment["at_medical"]:
            current_status = "AT_MEDICAL"
        elif assignment["transporting"]:
            current_status = "TRANSPORTING"
        elif assignment["arrived"]:
            current_status = "ARRIVED"
        elif assignment["enroute"]:
            current_status = "ENROUTE"
        elif assignment["dispatched"]:
            current_status = "DISPATCHED"

    conn.close()

    return templates.TemplateResponse(
        "mobile/mdt.html",
        {
            "request": request,
            "unit_id": unit_id,
            "unit": dict(unit_row),
            "current_status": current_status,
            "incident": incident,
            "assignment": dict(assignment) if assignment else None,
        }
    )


@app.get("/api/mobile/status/{unit_id}")
async def mobile_status_check(unit_id: str):
    """
    Quick status check for mobile MDT auto-refresh.
    Returns whether the page needs to refresh (new dispatch, status change).
    """
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()

    # Check for active assignment
    assignment = c.execute("""
        SELECT ua.dispatched, ua.enroute, ua.arrived, ua.cleared
        FROM UnitAssignments ua
        JOIN Incidents i ON ua.incident_id = i.incident_id
        WHERE ua.unit_id = ?
          AND ua.cleared IS NULL
          AND i.status IN ('OPEN', 'ACTIVE')
        LIMIT 1
    """, (unit_id,)).fetchone()

    conn.close()

    return {
        "ok": True,
        "has_assignment": assignment is not None,
        "needs_refresh": False  # Could implement change detection later
    }


@app.get("/mobile", response_class=HTMLResponse)
async def mobile_unit_select(request: Request):
    """Mobile unit selection page."""
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()

    units = c.execute("""
        SELECT unit_id, name, unit_type, status, is_apparatus, is_command
        FROM Units
        WHERE (is_apparatus = 1 OR is_command = 1)
        ORDER BY unit_id
    """).fetchall()

    conn.close()

    # Simple HTML for unit selection
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Select Unit - FORD CAD Mobile</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0f172a; color: #fff; margin: 0; padding: 20px; }
            h1 { color: #60a5fa; margin-bottom: 20px; }
            .unit-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; }
            .unit-btn { padding: 20px; background: #1e293b; border: 2px solid #334155; border-radius: 12px; color: #fff; text-decoration: none; text-align: center; font-weight: 600; font-size: 18px; transition: all 0.15s; }
            .unit-btn:hover { background: #334155; border-color: #60a5fa; }
            .unit-status { font-size: 12px; color: #64748b; margin-top: 4px; }
            .back-link { display: block; margin-top: 20px; color: #60a5fa; text-decoration: none; }
        </style>
    </head>
    <body>
        <h1>Select Your Unit</h1>
        <div class="unit-grid">
    """

    for u in units:
        status_class = (u["status"] or "available").lower()
        html += f'''
            <a href="/mobile/mdt/{u["unit_id"]}" class="unit-btn">
                {u["unit_id"]}
                <div class="unit-status">{u["status"] or "AVAILABLE"}</div>
            </a>
        '''

    html += """
        </div>
        <a href="/" class="back-link">&larr; Back to Full CAD</a>
    </body>
    </html>
    """

    return HTMLResponse(html)


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

    if not _is_super_admin(user):
        return JSONResponse(status_code=403, content={"ok": False, "error": "Super-admin access required to delete all incidents"})

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

    if not _is_super_admin(user):
        return JSONResponse(status_code=403, content={"ok": False, "error": "Super-admin access required for full system reset"})

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
# ADMIN — UNIT MANAGEMENT APIs
# ------------------------------------------------------

@app.get("/api/admin/units", response_class=JSONResponse)
def api_admin_units_list(user: str = "DISPATCH"):
    """List all units for admin management."""
    ensure_phase3_schema()

    if not _is_admin(user):
        return JSONResponse({"ok": False, "error": "Admin access required"}, status_code=403)

    conn = get_conn()
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT unit_id, name, unit_type, status, icon,
               is_apparatus, is_command, is_mutual_aid,
               display_order, aliases, last_updated
        FROM Units
        ORDER BY
            CASE WHEN is_apparatus = 1 THEN 1
                 WHEN is_command = 1 THEN 2
                 ELSE 3 END,
            display_order ASC,
            unit_id ASC
    """).fetchall()
    conn.close()

    return {
        "ok": True,
        "units": [dict(r) for r in rows]
    }


@app.post("/api/admin/units/add", response_class=JSONResponse)
async def api_admin_units_add(request: Request, user: str = "DISPATCH"):
    """Add a new unit."""
    ensure_phase3_schema()

    if not _is_admin(user):
        return JSONResponse({"ok": False, "error": "Admin access required"}, status_code=403)

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)

    unit_id = (data.get("unit_id") or "").strip().upper()
    if not unit_id:
        return JSONResponse({"ok": False, "error": "unit_id required"}, status_code=400)

    name = (data.get("name") or unit_id).strip()
    unit_type = (data.get("unit_type") or "PERSONNEL").upper()
    icon = (data.get("icon") or "").strip()
    is_apparatus = 1 if data.get("is_apparatus") else 0
    is_command = 1 if data.get("is_command") else 0
    is_mutual_aid = 1 if data.get("is_mutual_aid") else 0
    display_order = int(data.get("display_order", 999))
    aliases = (data.get("aliases") or "").strip()

    conn = get_conn()
    c = conn.cursor()

    # Check if unit exists
    existing = c.execute("SELECT 1 FROM Units WHERE unit_id = ?", (unit_id,)).fetchone()
    if existing:
        conn.close()
        return JSONResponse({"ok": False, "error": f"Unit {unit_id} already exists"}, status_code=409)

    c.execute("""
        INSERT INTO Units (unit_id, name, unit_type, status, icon,
                          is_apparatus, is_command, is_mutual_aid,
                          display_order, aliases, last_updated)
        VALUES (?, ?, ?, 'AVAILABLE', ?, ?, ?, ?, ?, ?, ?)
    """, (unit_id, name, unit_type, icon, is_apparatus, is_command, is_mutual_aid,
          display_order, aliases, _ts()))

    conn.commit()
    conn.close()

    masterlog(event_type="UNIT_ADD", user=user, details=f"Added unit {unit_id}")

    return {"ok": True, "unit_id": unit_id}


@app.post("/api/admin/units/update/{unit_id}", response_class=JSONResponse)
async def api_admin_units_update(request: Request, unit_id: str, user: str = "DISPATCH"):
    """Update an existing unit."""
    ensure_phase3_schema()

    if not _is_admin(user):
        return JSONResponse({"ok": False, "error": "Admin access required"}, status_code=403)

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)

    conn = get_conn()
    c = conn.cursor()

    existing = c.execute("SELECT 1 FROM Units WHERE unit_id = ?", (unit_id,)).fetchone()
    if not existing:
        conn.close()
        return JSONResponse({"ok": False, "error": f"Unit {unit_id} not found"}, status_code=404)

    # Build update query
    updates = []
    params = []

    if "name" in data:
        updates.append("name = ?")
        params.append((data["name"] or "").strip())
    if "unit_type" in data:
        updates.append("unit_type = ?")
        params.append((data["unit_type"] or "PERSONNEL").upper())
    if "icon" in data:
        updates.append("icon = ?")
        params.append((data["icon"] or "").strip())
    if "is_apparatus" in data:
        updates.append("is_apparatus = ?")
        params.append(1 if data["is_apparatus"] else 0)
    if "is_command" in data:
        updates.append("is_command = ?")
        params.append(1 if data["is_command"] else 0)
    if "is_mutual_aid" in data:
        updates.append("is_mutual_aid = ?")
        params.append(1 if data["is_mutual_aid"] else 0)
    if "display_order" in data:
        updates.append("display_order = ?")
        params.append(int(data["display_order"]))
    if "aliases" in data:
        updates.append("aliases = ?")
        params.append((data["aliases"] or "").strip())

    if not updates:
        conn.close()
        return JSONResponse({"ok": False, "error": "No fields to update"}, status_code=400)

    updates.append("last_updated = ?")
    params.append(_ts())
    params.append(unit_id)

    c.execute(f"UPDATE Units SET {', '.join(updates)} WHERE unit_id = ?", params)
    conn.commit()
    conn.close()

    masterlog(event_type="UNIT_UPDATE", user=user, details=f"Updated unit {unit_id}")

    return {"ok": True, "unit_id": unit_id}


@app.post("/api/admin/units/delete/{unit_id}", response_class=JSONResponse)
def api_admin_units_delete(unit_id: str, user: str = "DISPATCH"):
    """Delete a unit."""
    ensure_phase3_schema()

    if not _is_admin(user):
        return JSONResponse({"ok": False, "error": "Admin access required"}, status_code=403)

    conn = get_conn()
    c = conn.cursor()

    existing = c.execute("SELECT 1 FROM Units WHERE unit_id = ?", (unit_id,)).fetchone()
    if not existing:
        conn.close()
        return JSONResponse({"ok": False, "error": f"Unit {unit_id} not found"}, status_code=404)

    c.execute("DELETE FROM Units WHERE unit_id = ?", (unit_id,))
    conn.commit()
    conn.close()

    masterlog(event_type="UNIT_DELETE", user=user, details=f"Deleted unit {unit_id}")

    return {"ok": True, "deleted": unit_id}


@app.post("/api/admin/units/reorder", response_class=JSONResponse)
async def api_admin_units_reorder(request: Request, user: str = "DISPATCH"):
    """Reorder units by setting their display_order values."""
    ensure_phase3_schema()

    if not _is_admin(user):
        return JSONResponse({"ok": False, "error": "Admin access required"}, status_code=403)

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)

    # Expecting: {"orders": [{"unit_id": "Engine1", "display_order": 1}, ...]}
    orders = data.get("orders", [])
    if not orders:
        return JSONResponse({"ok": False, "error": "No orders provided"}, status_code=400)

    conn = get_conn()
    c = conn.cursor()

    for item in orders:
        uid = item.get("unit_id")
        order = item.get("display_order", 999)
        if uid:
            c.execute("UPDATE Units SET display_order = ?, last_updated = ? WHERE unit_id = ?",
                      (order, _ts(), uid))

    conn.commit()
    conn.close()

    masterlog(event_type="UNITS_REORDER", user=user, details=f"Reordered {len(orders)} units")

    return {"ok": True, "updated": len(orders)}


# ------------------------------------------------------
# ADMIN — SYSTEM SETTINGS APIs
# ------------------------------------------------------

@app.get("/api/admin/settings", response_class=JSONResponse)
def api_admin_settings_list(user: str = "DISPATCH"):
    """Get all system settings."""
    ensure_phase3_schema()

    if not _is_admin(user):
        return JSONResponse({"ok": False, "error": "Admin access required"}, status_code=403)

    conn = get_conn()
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT key, value, description, updated FROM SystemSettings ORDER BY key").fetchall()
    conn.close()

    return {
        "ok": True,
        "settings": {r["key"]: {"value": r["value"], "description": r["description"]} for r in rows}
    }


@app.post("/api/admin/settings", response_class=JSONResponse)
async def api_admin_settings_save(request: Request, user: str = "DISPATCH"):
    """Save a system setting. Super-admin required for system settings."""
    ensure_phase3_schema()

    if not _is_admin(user):
        return JSONResponse({"ok": False, "error": "Admin access required"}, status_code=403)

    # Check if setting requires super-admin
    try:
        body = await request.json()
        key = body.get("key", "")
        # System-critical settings require super-admin
        super_admin_keys = {
            "agency_name", "dept_name", "dept_code", "fdid", "state",
            "address", "city", "phone", "super_admin_users", "admin_users"
        }
        if key in super_admin_keys and not _is_super_admin(user):
            return JSONResponse({"ok": False, "error": "Super-admin access required for system settings"}, status_code=403)
    except Exception:
        pass

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)

    key = (data.get("key") or "").strip()
    value = data.get("value", "")
    description = data.get("description", "")

    if not key:
        return JSONResponse({"ok": False, "error": "key required"}, status_code=400)

    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        INSERT INTO SystemSettings (key, value, description, updated)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = ?, description = ?, updated = ?
    """, (key, value, description, _ts(), value, description, _ts()))

    conn.commit()
    conn.close()

    masterlog(event_type="SETTING_CHANGE", user=user, details=f"Changed setting: {key}")

    return {"ok": True, "key": key}


@app.get("/api/admin/icons", response_class=JSONResponse)
def api_admin_icons_list():
    """List available unit icons from the images directory."""
    import os

    icons = []
    icons_dir = os.path.join("static", "images")

    if os.path.exists(icons_dir):
        for f in os.listdir(icons_dir):
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp')):
                icons.append(f"/static/images/{f}")

    # Also check icons subfolder
    icons_sub = os.path.join("static", "images", "icons")
    if os.path.exists(icons_sub):
        for f in os.listdir(icons_sub):
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp')):
                icons.append(f"/static/images/icons/{f}")

    return {"ok": True, "icons": sorted(set(icons))}


# ------------------------------------------------------
# ADMIN — DASHBOARD PAGE (HTML)
# ------------------------------------------------------

@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard_page(request: Request, user: str = "DISPATCH"):
    """Admin dashboard HTML page."""
    ensure_phase3_schema()

    permission_level = _get_user_permission_level(user)
    if permission_level == "user":
        return HTMLResponse("<h1>403 Forbidden</h1><p>Admin access required.</p>", status_code=403)

    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "user": user,
            "permission_level": permission_level,
            "is_super_admin": permission_level == "super_admin",
            "is_admin": True  # They passed the check above
        }
    )


# ------------------------------------------------------
# SETTINGS — USER PREFERENCES PAGE (HTML)
# ------------------------------------------------------

@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, user: str = "DISPATCH"):
    """General settings/preferences page (accessible to all users)."""
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "user": user,
            "is_admin": _is_admin(user)
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
    import traceback
    print(f"❌ Server error: {exc}")
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={
            "ok": False,
            "error": str(exc)
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
    """Return all on-scene (arrived but not cleared) units for this unit's active incident."""
    conn = get_conn()
    c = conn.cursor()

    try:
        row = c.execute("""
            SELECT incident_id
            FROM UnitAssignments
            WHERE unit_id = ? AND cleared IS NULL
            ORDER BY dispatched DESC LIMIT 1
        """, (unit_id,)).fetchone()

        if not row:
            return {"ok": True, "units": [], "incident_id": None}

        incident_id = row["incident_id"]

        rows = c.execute("""
            SELECT unit_id, unit_id AS unit_name,
                   CASE WHEN commanding_unit = 1 THEN 1 ELSE 0 END AS is_command
            FROM UnitAssignments
            WHERE incident_id = ?
              AND arrived IS NOT NULL
              AND cleared IS NULL
        """, (incident_id,)).fetchall()

        return {"ok": True, "units": [dict(r) for r in rows], "incident_id": incident_id}

    except Exception as e:
        return {"ok": False, "units": [], "error": str(e)}

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


# ------------------------------------------------------
# PRE-PLANS (Pre-Incident Plans for Buildings)
# ------------------------------------------------------

@app.get("/admin/preplans", response_class=HTMLResponse)
async def admin_preplans_page(request: Request):
    """Admin page for managing pre-incident plans."""
    return templates.TemplateResponse(
        "admin/preplans.html",
        {"request": request}
    )


@app.get("/api/preplans")
async def get_preplans(search: str = None, active_only: bool = True):
    """Get all pre-plans with optional search."""
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()

    try:
        if search:
            search_term = f"%{search}%"
            if active_only:
                rows = c.execute("""
                    SELECT * FROM PrePlans
                    WHERE is_active = 1
                      AND (name LIKE ? OR address LIKE ? OR city LIKE ? OR hazards LIKE ?)
                    ORDER BY name
                """, (search_term, search_term, search_term, search_term)).fetchall()
            else:
                rows = c.execute("""
                    SELECT * FROM PrePlans
                    WHERE name LIKE ? OR address LIKE ? OR city LIKE ? OR hazards LIKE ?
                    ORDER BY name
                """, (search_term, search_term, search_term, search_term)).fetchall()
        else:
            if active_only:
                rows = c.execute("SELECT * FROM PrePlans WHERE is_active = 1 ORDER BY name").fetchall()
            else:
                rows = c.execute("SELECT * FROM PrePlans ORDER BY name").fetchall()

        return {"ok": True, "preplans": [dict(r) for r in rows]}
    finally:
        conn.close()


@app.get("/api/preplans/{preplan_id}")
async def get_preplan(preplan_id: int):
    """Get a specific pre-plan by ID."""
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()

    try:
        row = c.execute("SELECT * FROM PrePlans WHERE id = ?", (preplan_id,)).fetchone()
        if not row:
            return {"ok": False, "error": "Pre-plan not found"}
        return {"ok": True, "preplan": dict(row)}
    finally:
        conn.close()


@app.get("/api/preplans/match/{address}")
async def match_preplan(address: str):
    """
    Find pre-plans that match a given address.
    Used during incident creation to show pre-plan info.
    """
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()

    try:
        # Normalize the address for matching
        normalized = address.upper().strip()

        # Try exact match first
        row = c.execute("""
            SELECT * FROM PrePlans
            WHERE is_active = 1
              AND UPPER(address) = ?
            LIMIT 1
        """, (normalized,)).fetchone()

        if row:
            return {"ok": True, "matched": True, "preplan": dict(row)}

        # Try partial match (address starts with or contains)
        # Extract street number and name for fuzzy matching
        search_term = f"%{normalized}%"
        row = c.execute("""
            SELECT * FROM PrePlans
            WHERE is_active = 1
              AND UPPER(address) LIKE ?
            ORDER BY LENGTH(address) ASC
            LIMIT 1
        """, (search_term,)).fetchone()

        if row:
            return {"ok": True, "matched": True, "preplan": dict(row)}

        return {"ok": True, "matched": False}
    finally:
        conn.close()


@app.post("/api/preplans")
async def create_or_update_preplan(request: Request):
    """Create or update a pre-plan."""
    ensure_phase3_schema()
    data = await request.json()

    preplan_id = data.get("id")
    ts = datetime.datetime.now().isoformat()

    conn = get_conn()
    c = conn.cursor()

    try:
        if preplan_id:
            # Update existing
            c.execute("""
                UPDATE PrePlans SET
                    name = ?,
                    address = ?,
                    city = ?,
                    occupancy_type = ?,
                    construction_type = ?,
                    stories = ?,
                    square_footage = ?,
                    contact_name = ?,
                    contact_phone = ?,
                    sprinkler_type = ?,
                    standpipe_type = ?,
                    fdc_location = ?,
                    alarm_type = ?,
                    alarm_panel_location = ?,
                    knox_box_location = ?,
                    gas_shutoff = ?,
                    electric_shutoff = ?,
                    water_shutoff = ?,
                    hazards = ?,
                    access_info = ?,
                    tactical_notes = ?,
                    last_reviewed = ?,
                    is_active = ?,
                    updated = ?
                WHERE id = ?
            """, (
                data.get("name", ""),
                data.get("address", ""),
                data.get("city", ""),
                data.get("occupancy_type", ""),
                data.get("construction_type", ""),
                data.get("stories", 1),
                data.get("square_footage"),
                data.get("contact_name", ""),
                data.get("contact_phone", ""),
                data.get("sprinkler_type", ""),
                data.get("standpipe_type", ""),
                data.get("fdc_location", ""),
                data.get("alarm_type", ""),
                data.get("alarm_panel_location", ""),
                data.get("knox_box_location", ""),
                data.get("gas_shutoff", ""),
                data.get("electric_shutoff", ""),
                data.get("water_shutoff", ""),
                data.get("hazards", ""),
                data.get("access_info", ""),
                data.get("tactical_notes", ""),
                data.get("last_reviewed", ts[:10]),
                1 if data.get("is_active", True) else 0,
                ts,
                preplan_id
            ))
            conn.commit()
            masterlog(event_type="PREPLAN_UPDATE", user="SYSTEM", details=f"Updated pre-plan ID={preplan_id}: {data.get('name')}")
            return {"ok": True, "id": preplan_id, "action": "updated"}
        else:
            # Create new
            c.execute("""
                INSERT INTO PrePlans (
                    name, address, city, occupancy_type, construction_type,
                    stories, square_footage, contact_name, contact_phone,
                    sprinkler_type, standpipe_type, fdc_location,
                    alarm_type, alarm_panel_location, knox_box_location,
                    gas_shutoff, electric_shutoff, water_shutoff,
                    hazards, access_info, tactical_notes,
                    last_reviewed, is_active, created, updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data.get("name", ""),
                data.get("address", ""),
                data.get("city", ""),
                data.get("occupancy_type", ""),
                data.get("construction_type", ""),
                data.get("stories", 1),
                data.get("square_footage"),
                data.get("contact_name", ""),
                data.get("contact_phone", ""),
                data.get("sprinkler_type", ""),
                data.get("standpipe_type", ""),
                data.get("fdc_location", ""),
                data.get("alarm_type", ""),
                data.get("alarm_panel_location", ""),
                data.get("knox_box_location", ""),
                data.get("gas_shutoff", ""),
                data.get("electric_shutoff", ""),
                data.get("water_shutoff", ""),
                data.get("hazards", ""),
                data.get("access_info", ""),
                data.get("tactical_notes", ""),
                data.get("last_reviewed", ts[:10]),
                1 if data.get("is_active", True) else 0,
                ts,
                ts
            ))
            conn.commit()
            new_id = c.lastrowid
            masterlog(event_type="PREPLAN_CREATE", user="SYSTEM", details=f"Created pre-plan ID={new_id}: {data.get('name')}")
            return {"ok": True, "id": new_id, "action": "created"}
    finally:
        conn.close()


@app.delete("/api/preplans/{preplan_id}")
async def delete_preplan(preplan_id: int):
    """Delete (deactivate) a pre-plan."""
    ensure_phase3_schema()
    conn = get_conn()

    try:
        # Soft delete - set is_active to 0
        conn.execute("UPDATE PrePlans SET is_active = 0, updated = ? WHERE id = ?",
                    (datetime.datetime.now().isoformat(), preplan_id))
        conn.commit()
        masterlog(event_type="PREPLAN_DELETE", user="SYSTEM", details=f"Deactivated pre-plan ID={preplan_id}")
        return {"ok": True}
    finally:
        conn.close()


# ------------------------------------------------------
# DETERMINANT CODES (MPDS/FPDS)
# ------------------------------------------------------

# MPDS Protocol Reference - Medical Priority Dispatch System
MPDS_PROTOCOLS = {
    "1": {"name": "Abdominal Pain", "levels": ["A", "C", "D"]},
    "2": {"name": "Allergies/Envenomations", "levels": ["A", "B", "C", "D", "E"]},
    "3": {"name": "Animal Bites", "levels": ["A", "B", "D"]},
    "4": {"name": "Assault/Sexual Assault", "levels": ["A", "B", "D"]},
    "5": {"name": "Back Pain", "levels": ["A", "C", "D"]},
    "6": {"name": "Breathing Problems", "levels": ["C", "D", "E"]},
    "7": {"name": "Burns/Explosions", "levels": ["A", "B", "C", "D", "E"]},
    "8": {"name": "Carbon Monoxide/Hazmat", "levels": ["B", "C", "D"]},
    "9": {"name": "Cardiac Arrest", "levels": ["B", "D", "E"]},
    "10": {"name": "Chest Pain", "levels": ["A", "C", "D"]},
    "11": {"name": "Choking", "levels": ["A", "D", "E"]},
    "12": {"name": "Convulsions/Seizures", "levels": ["A", "B", "C", "D"]},
    "13": {"name": "Diabetic Problems", "levels": ["A", "C", "D"]},
    "14": {"name": "Drowning", "levels": ["B", "C", "D", "E"]},
    "15": {"name": "Electrocution", "levels": ["B", "C", "D", "E"]},
    "16": {"name": "Eye Problems", "levels": ["A", "B", "D"]},
    "17": {"name": "Falls", "levels": ["A", "B", "D"]},
    "18": {"name": "Headache", "levels": ["A", "B", "C"]},
    "19": {"name": "Heart Problems", "levels": ["A", "C", "D"]},
    "20": {"name": "Heat/Cold Exposure", "levels": ["A", "B", "C", "D"]},
    "21": {"name": "Hemorrhage/Lacerations", "levels": ["A", "B", "C", "D"]},
    "22": {"name": "Inaccessible/Entrapment", "levels": ["A", "B", "D"]},
    "23": {"name": "Overdose/Poisoning", "levels": ["B", "C", "D"]},
    "24": {"name": "Pregnancy/Childbirth", "levels": ["A", "B", "C", "D"]},
    "25": {"name": "Psychiatric/Suicide", "levels": ["A", "B", "D"]},
    "26": {"name": "Sick Person", "levels": ["A", "B", "C", "D"]},
    "27": {"name": "Stab/Gunshot Wound", "levels": ["A", "B", "D"]},
    "28": {"name": "Stroke/CVA", "levels": ["A", "C"]},
    "29": {"name": "Traffic Accident", "levels": ["A", "B", "D"]},
    "30": {"name": "Traumatic Injuries", "levels": ["A", "B", "D"]},
    "31": {"name": "Unconscious/Fainting", "levels": ["A", "C", "D", "E"]},
    "32": {"name": "Unknown Problem", "levels": ["B", "D"]},
    "33": {"name": "Transfer/Interfacility", "levels": ["A", "C", "D"]},
}

# FPDS Protocol Reference - Fire Priority Dispatch System
FPDS_PROTOCOLS = {
    "52": {"name": "Alarms", "levels": ["A", "B", "C", "D"]},
    "53": {"name": "Citizen Assist", "levels": ["A", "B", "C"]},
    "54": {"name": "Confined Space", "levels": ["B", "C", "D"]},
    "55": {"name": "Electrical Hazard", "levels": ["B", "C", "D"]},
    "56": {"name": "Elevator Emergency", "levels": ["A", "B", "C", "D"]},
    "57": {"name": "Fuel Spill", "levels": ["B", "C", "D"]},
    "58": {"name": "Hazmat Release", "levels": ["B", "C", "D"]},
    "59": {"name": "High Angle Rescue", "levels": ["B", "C", "D"]},
    "60": {"name": "Gas Leak", "levels": ["B", "C", "D"]},
    "61": {"name": "Building Fire", "levels": ["C", "D", "E"]},
    "62": {"name": "Outside Fire", "levels": ["A", "B", "C", "D"]},
    "63": {"name": "Vehicle Fire", "levels": ["B", "C", "D"]},
    "64": {"name": "Water Rescue", "levels": ["B", "C", "D"]},
    "65": {"name": "Technical Rescue", "levels": ["B", "C", "D"]},
    "66": {"name": "Smoke Investigation", "levels": ["B", "C", "D"]},
    "67": {"name": "Appliance Fire", "levels": ["B", "C", "D"]},
    "68": {"name": "Odor Investigation", "levels": ["A", "B", "C"]},
    "69": {"name": "Aircraft Emergency", "levels": ["C", "D", "E"]},
}

# Determinant Level Descriptions
DETERMINANT_LEVELS = {
    "O": {"name": "Omega", "description": "Lowest - Possible phone advice", "priority": 5, "color": "gray"},
    "A": {"name": "Alpha", "description": "Low - BLS ambulance", "priority": 4, "color": "green"},
    "B": {"name": "Bravo", "description": "Moderate - BLS ambulance, possible ALS", "priority": 3, "color": "yellow"},
    "C": {"name": "Charlie", "description": "Urgent - ALS evaluation", "priority": 2, "color": "orange"},
    "D": {"name": "Delta", "description": "High priority - ALS response", "priority": 1, "color": "red"},
    "E": {"name": "Echo", "description": "Highest - Cardiac arrest, immediate response", "priority": 0, "color": "purple"},
}


@app.get("/api/determinant_codes")
async def get_determinant_codes(protocol: str = None):
    """Get determinant code reference data."""
    result = {
        "ok": True,
        "levels": DETERMINANT_LEVELS,
    }

    if protocol == "MPDS" or protocol is None:
        result["mpds"] = MPDS_PROTOCOLS
    if protocol == "FPDS" or protocol is None:
        result["fpds"] = FPDS_PROTOCOLS

    return result


@app.get("/api/determinant_codes/{protocol}/{code}")
async def get_determinant_info(protocol: str, code: str):
    """Get info about a specific determinant code."""
    protocol = protocol.upper()
    protocols = MPDS_PROTOCOLS if protocol == "MPDS" else FPDS_PROTOCOLS

    # Parse code like "10-D-1" or "10D1"
    code = code.upper().replace("-", "")
    # Extract protocol number and level
    import re
    match = re.match(r"(\d+)([A-E])(\d*)", code)
    if not match:
        return {"ok": False, "error": "Invalid code format"}

    proto_num = match.group(1)
    level = match.group(2)
    suffix = match.group(3) or "1"

    proto_info = protocols.get(proto_num)
    if not proto_info:
        return {"ok": False, "error": f"Unknown protocol {proto_num}"}

    level_info = DETERMINANT_LEVELS.get(level)
    if not level_info:
        return {"ok": False, "error": f"Unknown level {level}"}

    return {
        "ok": True,
        "code": f"{proto_num}-{level}-{suffix}",
        "protocol": protocol,
        "protocol_number": proto_num,
        "protocol_name": proto_info["name"],
        "level": level,
        "level_name": level_info["name"],
        "level_description": level_info["description"],
        "priority": level_info["priority"],
        "color": level_info["color"]
    }


@app.post("/api/incident/{incident_id}/determinant")
async def set_incident_determinant(incident_id: int, request: Request):
    """Set the determinant code for an incident."""
    ensure_phase3_schema()
    data = await request.json()

    code = str(data.get("code", "")).strip().upper()
    protocol = str(data.get("protocol", "MPDS")).strip().upper()
    description = str(data.get("description", "")).strip()

    if not code:
        return {"ok": False, "error": "Code is required"}

    conn = get_conn()
    try:
        # Update the incident
        conn.execute("""
            UPDATE Incidents
            SET determinant_code = ?,
                determinant_protocol = ?,
                determinant_description = ?,
                updated = ?
            WHERE incident_id = ?
        """, (code, protocol, description, datetime.datetime.now().isoformat(), incident_id))
        conn.commit()

        masterlog(
            event_type="DETERMINANT_SET",
            user="SYSTEM",
            incident_id=incident_id,
            details=f"Set determinant to {protocol} {code}"
        )

        return {"ok": True, "code": code, "protocol": protocol}
    finally:
        conn.close()


@app.post("/api/incident/{incident_id}/edit")
async def api_incident_edit(incident_id: int, request: Request):
    """
    Edit incident fields after creation.
    Accepts JSON with any of: location, address, caller_name, caller_phone, type, priority, notes.
    Logs all changes to IncidentHistory for audit trail.
    """
    ensure_phase3_schema()
    data = await request.json()

    editable_fields = ["location", "address", "caller_name", "caller_phone", "type", "priority", "notes"]
    updates = {}
    for field in editable_fields:
        if field in data:
            updates[field] = (data[field] or "").strip()

    if not updates:
        return {"ok": False, "error": "No editable fields provided"}

    conn = get_conn()
    c = conn.cursor()
    try:
        # Fetch current values for audit
        row = c.execute("SELECT * FROM Incidents WHERE incident_id = ?", (incident_id,)).fetchone()
        if not row:
            return {"ok": False, "error": "Incident not found"}
        old_vals = dict(row)

        # Build SET clause
        set_parts = []
        params = []
        for field, val in updates.items():
            set_parts.append(f"{field} = ?")
            params.append(val)
        set_parts.append("updated = ?")
        params.append(_ts())
        params.append(incident_id)

        c.execute(f"UPDATE Incidents SET {', '.join(set_parts)} WHERE incident_id = ?", params)
        conn.commit()

        # Audit: log each changed field
        user = "DISPATCH"
        try:
            user = request.session.get("username") or request.session.get("user") or "DISPATCH"
        except Exception:
            pass

        changes = []
        for field, val in updates.items():
            old = str(old_vals.get(field) or "")
            if old != val:
                changes.append(f"{field}: '{old}' -> '{val}'")
                incident_history(incident_id, "FIELD_EDITED", user=user, details=f"{field} changed from '{old}' to '{val}'")

        if changes:
            masterlog("INCIDENT_EDITED", user=user, incident_id=incident_id, details="; ".join(changes))

        return {"ok": True, "updated_fields": list(updates.keys()), "changes": changes}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        conn.close()


@app.get("/incident/{incident_id}/determinant_picker", response_class=HTMLResponse)
async def determinant_picker(request: Request, incident_id: int):
    """Display the determinant code picker modal."""
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()

    incident = c.execute("SELECT * FROM Incidents WHERE incident_id = ?", (incident_id,)).fetchone()
    conn.close()

    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    return templates.TemplateResponse(
        "modals/determinant_picker.html",
        {
            "request": request,
            "incident_id": incident_id,
            "incident": dict(incident),
            "mpds_protocols": MPDS_PROTOCOLS,
            "fpds_protocols": FPDS_PROTOCOLS,
            "determinant_levels": DETERMINANT_LEVELS
        }
    )


# ------------------------------------------------------
# STATION ALERTING (Webhooks)
# ------------------------------------------------------

@app.get("/admin/station_alerts", response_class=HTMLResponse)
async def admin_station_alerts_page(request: Request):
    """Admin page for managing station alert webhooks."""
    return templates.TemplateResponse(
        "admin/station_alerts.html",
        {"request": request}
    )


@app.get("/api/station_alerts")
async def get_station_alerts():
    """Get all station alert configurations."""
    ensure_phase3_schema()
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM StationAlerts ORDER BY name").fetchall()
        return {"ok": True, "alerts": [dict(r) for r in rows]}
    finally:
        conn.close()


@app.get("/api/station_alerts/{alert_id}")
async def get_station_alert(alert_id: int):
    """Get a specific station alert configuration."""
    ensure_phase3_schema()
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM StationAlerts WHERE id = ?", (alert_id,)).fetchone()
        if not row:
            return {"ok": False, "error": "Alert not found"}
        return {"ok": True, "alert": dict(row)}
    finally:
        conn.close()


@app.post("/api/station_alerts")
async def create_or_update_station_alert(request: Request):
    """Create or update a station alert webhook."""
    ensure_phase3_schema()
    data = await request.json()

    alert_id = data.get("id")
    ts = datetime.datetime.now().isoformat()

    conn = get_conn()
    try:
        if alert_id:
            # Update existing
            conn.execute("""
                UPDATE StationAlerts SET
                    name = ?,
                    station_id = ?,
                    webhook_url = ?,
                    webhook_method = ?,
                    webhook_headers = ?,
                    webhook_template = ?,
                    trigger_on = ?,
                    unit_filter = ?,
                    incident_type_filter = ?,
                    is_active = ?,
                    updated = ?
                WHERE id = ?
            """, (
                data.get("name", ""),
                data.get("station_id", ""),
                data.get("webhook_url", ""),
                data.get("webhook_method", "POST"),
                data.get("webhook_headers", ""),
                data.get("webhook_template", ""),
                data.get("trigger_on", "DISPATCH"),
                data.get("unit_filter", ""),
                data.get("incident_type_filter", ""),
                1 if data.get("is_active", True) else 0,
                ts,
                alert_id
            ))
            conn.commit()
            masterlog(event_type="STATION_ALERT_UPDATE", user="SYSTEM", details=f"Updated station alert ID={alert_id}")
            return {"ok": True, "id": alert_id, "action": "updated"}
        else:
            # Create new
            c = conn.cursor()
            c.execute("""
                INSERT INTO StationAlerts (
                    name, station_id, webhook_url, webhook_method, webhook_headers,
                    webhook_template, trigger_on, unit_filter, incident_type_filter,
                    is_active, created, updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data.get("name", ""),
                data.get("station_id", ""),
                data.get("webhook_url", ""),
                data.get("webhook_method", "POST"),
                data.get("webhook_headers", ""),
                data.get("webhook_template", ""),
                data.get("trigger_on", "DISPATCH"),
                data.get("unit_filter", ""),
                data.get("incident_type_filter", ""),
                1 if data.get("is_active", True) else 0,
                ts, ts
            ))
            conn.commit()
            new_id = c.lastrowid
            masterlog(event_type="STATION_ALERT_CREATE", user="SYSTEM", details=f"Created station alert ID={new_id}")
            return {"ok": True, "id": new_id, "action": "created"}
    finally:
        conn.close()


@app.delete("/api/station_alerts/{alert_id}")
async def delete_station_alert(alert_id: int):
    """Delete a station alert webhook."""
    ensure_phase3_schema()
    conn = get_conn()
    try:
        conn.execute("DELETE FROM StationAlerts WHERE id = ?", (alert_id,))
        conn.commit()
        masterlog(event_type="STATION_ALERT_DELETE", user="SYSTEM", details=f"Deleted station alert ID={alert_id}")
        return {"ok": True}
    finally:
        conn.close()


@app.post("/api/station_alerts/{alert_id}/test")
async def test_station_alert(alert_id: int):
    """Test a station alert webhook with sample data."""
    ensure_phase3_schema()
    conn = get_conn()

    try:
        alert = conn.execute("SELECT * FROM StationAlerts WHERE id = ?", (alert_id,)).fetchone()
        if not alert:
            return {"ok": False, "error": "Alert not found"}
        alert = dict(alert)
    finally:
        conn.close()

    # Create test payload
    test_data = {
        "incident_id": 9999,
        "incident_number": "2026-TEST",
        "type": "STRUCTURE FIRE",
        "location": "123 TEST STREET",
        "priority": 1,
        "units": ["ENGINE1", "LADDER1"],
        "narrative": "This is a test alert",
        "timestamp": datetime.datetime.now().isoformat(),
        "station_id": alert.get("station_id", ""),
        "alert_name": alert.get("name", ""),
        "test": True
    }

    result = await trigger_webhook(alert, test_data)
    return result


async def trigger_webhook(alert: dict, payload: dict) -> dict:
    """Send a webhook notification using urllib."""
    import json
    import urllib.request
    import urllib.parse
    import asyncio

    url = alert.get("webhook_url", "")
    method = alert.get("webhook_method", "POST").upper()

    if not url:
        return {"ok": False, "error": "No webhook URL configured"}

    # Parse headers
    headers = {"Content-Type": "application/json"}
    custom_headers = alert.get("webhook_headers", "")
    if custom_headers:
        try:
            headers.update(json.loads(custom_headers))
        except:
            pass

    # Apply template if exists
    template = alert.get("webhook_template", "")
    if template:
        try:
            # Simple template substitution
            body = template
            for key, value in payload.items():
                body = body.replace(f"{{{{{key}}}}}", str(value))
            data = body.encode('utf-8')
        except Exception:
            data = json.dumps(payload).encode('utf-8')
    else:
        data = json.dumps(payload).encode('utf-8')

    def _do_request():
        """Synchronous request function to run in thread pool."""
        try:
            if method == "GET":
                query_string = urllib.parse.urlencode(payload)
                full_url = f"{url}?{query_string}" if query_string else url
                req = urllib.request.Request(full_url, headers=headers, method="GET")
            else:
                req = urllib.request.Request(url, data=data, headers=headers, method="POST")

            with urllib.request.urlopen(req, timeout=10) as response:
                status_code = response.status
                response_text = response.read().decode('utf-8', errors='ignore')[:500]
                return {"ok": status_code < 400, "status_code": status_code, "response": response_text}

        except urllib.error.HTTPError as e:
            return {"ok": False, "status_code": e.code, "error": str(e)}
        except Exception as e:
            return {"ok": False, "status_code": 0, "error": str(e)}

    try:
        # Run synchronous request in thread pool
        result = await asyncio.to_thread(_do_request)

        # Update last triggered status
        conn = get_conn()
        try:
            conn.execute("""
                UPDATE StationAlerts
                SET last_triggered = ?, last_status = ?
                WHERE id = ?
            """, (datetime.datetime.now().isoformat(), result.get("status_code", 0), alert.get("id")))
            conn.commit()
        finally:
            conn.close()

        return result

    except Exception as e:
        # Update with error status
        conn = get_conn()
        try:
            conn.execute("""
                UPDATE StationAlerts
                SET last_triggered = ?, last_status = ?
                WHERE id = ?
            """, (datetime.datetime.now().isoformat(), 0, alert.get("id")))
            conn.commit()
        finally:
            conn.close()

        return {"ok": False, "error": str(e)}


async def fire_station_alerts(trigger_type: str, incident: dict, units: list = None):
    """Fire all matching station alerts for a dispatch event."""
    ensure_phase3_schema()
    conn = get_conn()

    try:
        alerts = conn.execute("""
            SELECT * FROM StationAlerts
            WHERE is_active = 1
              AND (trigger_on = ? OR trigger_on = 'ALL')
        """, (trigger_type,)).fetchall()
    finally:
        conn.close()

    if not alerts:
        return

    for alert in alerts:
        alert = dict(alert)

        # Check unit filter
        unit_filter = alert.get("unit_filter", "")
        if unit_filter and units:
            filter_units = [u.strip().upper() for u in unit_filter.split(",")]
            matching_units = [u for u in units if u.upper() in filter_units]
            if not matching_units:
                continue

        # Check incident type filter
        type_filter = alert.get("incident_type_filter", "")
        if type_filter:
            filter_types = [t.strip().upper() for t in type_filter.split(",")]
            incident_type = (incident.get("type") or "").upper()
            if incident_type not in filter_types:
                continue

        # Build payload
        payload = {
            "incident_id": incident.get("incident_id"),
            "incident_number": incident.get("incident_number"),
            "type": incident.get("type"),
            "location": incident.get("location"),
            "priority": incident.get("priority"),
            "units": units or [],
            "narrative": incident.get("narrative", ""),
            "caller_name": incident.get("caller_name", ""),
            "caller_phone": incident.get("caller_phone", ""),
            "timestamp": datetime.datetime.now().isoformat(),
            "station_id": alert.get("station_id", ""),
            "alert_name": alert.get("name", ""),
            "trigger_type": trigger_type
        }

        # Fire webhook asynchronously
        try:
            await trigger_webhook(alert, payload)
        except Exception as e:
            print(f"[STATION_ALERT] Error firing webhook {alert.get('name')}: {e}")


# ------------------------------------------------------
# CALLER & PREMISE HISTORY
# ------------------------------------------------------

@app.get("/api/premise_history/{location}")
async def get_premise_history(location: str, limit: int = 10, exclude_id: int = None):
    """
    Get previous incidents at or near the same location.
    Used to show dispatchers premise history.
    """
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()

    try:
        # Normalize location for matching
        normalized = location.upper().strip()
        if not normalized:
            return {"ok": True, "history": [], "count": 0}

        # Search for exact and similar locations
        query = """
            SELECT incident_id, incident_number, type, location, status,
                   created, closed_at, caller_name, caller_phone,
                   narrative, priority
            FROM Incidents
            WHERE incident_number IS NOT NULL
              AND UPPER(location) LIKE ?
        """
        params = [f"%{normalized}%"]

        if exclude_id:
            query += " AND incident_id != ?"
            params.append(exclude_id)

        query += " ORDER BY created DESC LIMIT ?"
        params.append(limit)

        rows = c.execute(query, params).fetchall()

        history = []
        for r in rows:
            history.append({
                "incident_id": r["incident_id"],
                "incident_number": r["incident_number"],
                "type": r["type"],
                "location": r["location"],
                "status": r["status"],
                "created": r["created"],
                "closed_at": r["closed_at"],
                "caller_name": r["caller_name"],
                "priority": r["priority"]
            })

        # Get total count
        count_query = """
            SELECT COUNT(*) as total FROM Incidents
            WHERE incident_number IS NOT NULL
              AND UPPER(location) LIKE ?
        """
        count_params = [f"%{normalized}%"]
        if exclude_id:
            count_query += " AND incident_id != ?"
            count_params.append(exclude_id)

        total = c.execute(count_query, count_params).fetchone()["total"]

        return {"ok": True, "history": history, "count": total}
    finally:
        conn.close()


@app.get("/api/caller_history/{phone}")
async def get_caller_history(phone: str, limit: int = 10, exclude_id: int = None):
    """
    Get previous incidents from the same caller phone number.
    Helps identify frequent callers.
    """
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()

    try:
        # Normalize phone - remove non-digits for matching
        digits_only = ''.join(filter(str.isdigit, phone))
        if len(digits_only) < 7:
            return {"ok": True, "history": [], "count": 0}

        # Match last 7 digits (handles different formats)
        search_term = f"%{digits_only[-7:]}%"

        query = """
            SELECT incident_id, incident_number, type, location, status,
                   created, closed_at, caller_name, caller_phone, priority
            FROM Incidents
            WHERE incident_number IS NOT NULL
              AND caller_phone IS NOT NULL
              AND caller_phone != ''
              AND (
                  REPLACE(REPLACE(REPLACE(REPLACE(caller_phone, '-', ''), '(', ''), ')', ''), ' ', '')
                  LIKE ?
              )
        """
        params = [search_term]

        if exclude_id:
            query += " AND incident_id != ?"
            params.append(exclude_id)

        query += " ORDER BY created DESC LIMIT ?"
        params.append(limit)

        rows = c.execute(query, params).fetchall()

        history = []
        for r in rows:
            history.append({
                "incident_id": r["incident_id"],
                "incident_number": r["incident_number"],
                "type": r["type"],
                "location": r["location"],
                "status": r["status"],
                "created": r["created"],
                "closed_at": r["closed_at"],
                "caller_name": r["caller_name"],
                "caller_phone": r["caller_phone"],
                "priority": r["priority"]
            })

        # Get total count
        count_query = """
            SELECT COUNT(*) as total FROM Incidents
            WHERE incident_number IS NOT NULL
              AND caller_phone IS NOT NULL
              AND caller_phone != ''
              AND (
                  REPLACE(REPLACE(REPLACE(REPLACE(caller_phone, '-', ''), '(', ''), ')', ''), ' ', '')
                  LIKE ?
              )
        """
        count_params = [search_term]
        if exclude_id:
            count_query += " AND incident_id != ?"
            count_params.append(exclude_id)

        total = c.execute(count_query, count_params).fetchone()["total"]

        return {"ok": True, "history": history, "count": total, "caller_phone": phone}
    finally:
        conn.close()


@app.get("/api/incident/{incident_id}/history")
async def get_incident_history_context(incident_id: int):
    """
    Get both premise and caller history for an incident.
    Returns combined history for display in IAW.
    """
    ensure_phase3_schema()
    conn = get_conn()
    c = conn.cursor()

    try:
        # Get current incident
        incident = c.execute("SELECT * FROM Incidents WHERE incident_id = ?", (incident_id,)).fetchone()
        if not incident:
            return {"ok": False, "error": "Incident not found"}

        incident = dict(incident)
        location = incident.get("location", "")
        phone = incident.get("caller_phone", "")

        result = {
            "ok": True,
            "premise_history": [],
            "caller_history": [],
            "premise_count": 0,
            "caller_count": 0
        }

        # Get premise history
        if location:
            normalized = location.upper().strip()
            rows = c.execute("""
                SELECT incident_id, incident_number, type, status, created
                FROM Incidents
                WHERE incident_number IS NOT NULL
                  AND UPPER(location) LIKE ?
                  AND incident_id != ?
                ORDER BY created DESC
                LIMIT 5
            """, (f"%{normalized}%", incident_id)).fetchall()
            result["premise_history"] = [dict(r) for r in rows]

            count = c.execute("""
                SELECT COUNT(*) as total FROM Incidents
                WHERE incident_number IS NOT NULL
                  AND UPPER(location) LIKE ?
                  AND incident_id != ?
            """, (f"%{normalized}%", incident_id)).fetchone()
            result["premise_count"] = count["total"]

        # Get caller history
        if phone:
            digits_only = ''.join(filter(str.isdigit, phone))
            if len(digits_only) >= 7:
                search_term = f"%{digits_only[-7:]}%"
                rows = c.execute("""
                    SELECT incident_id, incident_number, type, status, created, location
                    FROM Incidents
                    WHERE incident_number IS NOT NULL
                      AND caller_phone IS NOT NULL
                      AND caller_phone != ''
                      AND (
                          REPLACE(REPLACE(REPLACE(REPLACE(caller_phone, '-', ''), '(', ''), ')', ''), ' ', '')
                          LIKE ?
                      )
                      AND incident_id != ?
                    ORDER BY created DESC
                    LIMIT 5
                """, (search_term, incident_id)).fetchall()
                result["caller_history"] = [dict(r) for r in rows]

                count = c.execute("""
                    SELECT COUNT(*) as total FROM Incidents
                    WHERE incident_number IS NOT NULL
                      AND caller_phone IS NOT NULL
                      AND caller_phone != ''
                      AND (
                          REPLACE(REPLACE(REPLACE(REPLACE(caller_phone, '-', ''), '(', ''), ')', ''), ' ', '')
                          LIKE ?
                      )
                      AND incident_id != ?
                """, (search_term, incident_id)).fetchone()
                result["caller_count"] = count["total"]

        return result
    finally:
        conn.close()

