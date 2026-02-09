"""
FORD-CAD — Test Infrastructure (conftest.py)
=============================================
Provides:
  - CAD_TEST_MODE environment setup
  - Test database (cad_test.db) with deterministic seed data
  - FastAPI TestClient with session injection
  - DB assertion helpers
  - Artifact collection
"""

import os
import sys
import shutil
import sqlite3
import datetime
import json
import pytest

# Ensure project root is on path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

# ============================================================================
# TEST MODE: Use separate test database
# ============================================================================
TEST_DB_PATH = os.path.join(ROOT_DIR, "cad_test.db")
ARTIFACTS_DIR = os.path.join(ROOT_DIR, "test_artifacts",
                              datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))

os.environ["CAD_TEST_MODE"] = "1"


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(scope="session", autouse=True)
def setup_test_env():
    """Session-wide test environment setup."""
    # Remove stale test DB
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

    # Create artifact directories
    for subdir in ["screenshots", "console_logs", "server_logs",
                   "exported_reports", "json_snapshots"]:
        os.makedirs(os.path.join(ARTIFACTS_DIR, subdir), exist_ok=True)

    # Monkey-patch main.DB_PATH before importing app
    import main
    main.DB_PATH = TEST_DB_PATH
    main._SCHEMA_INIT_DONE = False

    yield

    # Cleanup (ignore Windows file lock errors)
    try:
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
    except (PermissionError, OSError):
        pass


@pytest.fixture(scope="session")
def app():
    """Get the FastAPI app instance with test DB."""
    import main
    main.DB_PATH = TEST_DB_PATH
    main._SCHEMA_INIT_DONE = False
    return main.app


@pytest.fixture(scope="session")
def client(app):
    """FastAPI TestClient (session-scoped for speed)."""
    from starlette.testclient import TestClient
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(scope="session")
def seeded_db(app, client):
    """Seed the test database with deterministic data."""
    import main
    main.DB_PATH = TEST_DB_PATH
    main._SCHEMA_INIT_DONE = False
    main.ensure_phase3_schema()

    conn = sqlite3.connect(TEST_DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Initialize chat tables (not auto-created in test mode)
    try:
        from app.messaging.models import init_chat_schema
        init_chat_schema(conn)
        conn.commit()
    except Exception:
        pass

    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ---- UNITS ----
    # Columns: unit_id, name, unit_type, status, is_apparatus, is_mutual_aid, last_updated
    units = [
        # Command / Admin units
        ("1578", "Chief", "AVAILABLE", "Command", 0, 0),
        ("CAR1", "Car 1", "AVAILABLE", "Command", 0, 0),
        ("BATT1", "Battalion 1", "AVAILABLE", "Command", 0, 0),
        ("BATT2", "Battalion 2", "AVAILABLE", "Command", 0, 0),
        ("BATT3", "Battalion 3", "AVAILABLE", "Command", 0, 0),
        ("BATT4", "Battalion 4", "AVAILABLE", "Command", 0, 0),
        ("17", "Inspector", "AVAILABLE", "Command", 0, 0),
        ("47", "Admin 47", "AVAILABLE", "Command", 0, 0),
        # Apparatus
        ("E1", "Engine 1", "AVAILABLE", "Engine", 1, 0),
        ("E2", "Engine 2", "AVAILABLE", "Engine", 1, 0),
        ("M1", "Medic 1", "AVAILABLE", "Medic", 1, 0),
        ("M2", "Medic 2", "AVAILABLE", "Medic", 1, 0),
        ("T1", "Tower 1", "AVAILABLE", "Tower", 1, 0),
        ("SQ1", "Squad 1", "AVAILABLE", "Squad", 1, 0),
        ("UTV1", "UTV 1", "AVAILABLE", "UTV", 1, 0),
        ("UTV2", "UTV 2", "AVAILABLE", "UTV", 1, 0),
        # Personnel (2-digit IDs)
        ("11", "FF Smith", "AVAILABLE", "Personnel", 0, 0),
        ("12", "FF Johnson", "AVAILABLE", "Personnel", 0, 0),
        ("21", "FF Williams", "AVAILABLE", "Personnel", 0, 0),
        ("22", "FF Brown", "AVAILABLE", "Personnel", 0, 0),
        # Dispatcher
        ("DISP1", "Dispatcher 1", "AVAILABLE", "Dispatch", 0, 0),
    ]

    for uid, name, status, utype, is_app, ma in units:
        c.execute("""
            INSERT OR REPLACE INTO Units
            (unit_id, name, status, unit_type, is_apparatus, is_mutual_aid, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (uid, name, status, utype, is_app, ma, ts))

    # ---- PERSONNEL ASSIGNMENTS ----
    personnel = [
        ("E2", "11", "Driver", "A"),
        ("E2", "12", "Officer", "A"),
        ("E1", "21", "Driver", "A"),
        ("E1", "22", "Officer", "A"),
    ]
    for app_id, pers_id, role, shift in personnel:
        c.execute("""
            INSERT OR REPLACE INTO PersonnelAssignments
            (apparatus_id, personnel_id, role, shift, updated)
            VALUES (?, ?, ?, ?, ?)
        """, (app_id, pers_id, role, shift, ts))

    # ---- UNIT ROSTER ----
    for uid, _, _, _, _, _ in units:
        c.execute("""
            INSERT OR REPLACE INTO UnitRoster
            (unit_id, shift_letter, home_shift_letter, updated)
            VALUES (?, ?, ?, ?)
        """, (uid, "A", "A", ts))

    # ---- INCIDENTS ----
    # 1: Active emergency with full calltaker info + units assigned
    c.execute("""
        INSERT INTO Incidents
        (incident_number, type, location, caller_name, caller_phone, status,
         priority, shift, narrative, created, updated, is_draft, address, node, pole,
         nature, cross_street)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
    """, ("2026-0001", "STRUCTURE FIRE", "100 MAIN ST", "John Doe", "313-555-0001",
          "ACTIVE", 1, "A", "Smoke visible from 2nd floor", ts, ts,
          "100 MAIN ST, FORD", "N100", "P42", "Structure Fire - Commercial", "ELM AVE"))

    # 2: Open incident — no units, missing some calltaker fields
    c.execute("""
        INSERT INTO Incidents
        (incident_number, type, location, status, priority, shift, created, updated, is_draft)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
    """, ("2026-0002", "EMS", "200 OAK RD", "OPEN", 2, "A", ts, ts))

    # 3: Held incident
    c.execute("""
        INSERT INTO Incidents
        (incident_number, type, location, caller_name, status, priority, shift,
         created, updated, is_draft)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
    """, ("2026-0003", "GRASS FIRE", "300 PINE LN", "Jane Smith", "HELD", 3, "A", ts, ts))

    # 4: Closed incident with full timeline
    closed_ts = (datetime.datetime.now() - datetime.timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""
        INSERT INTO Incidents
        (incident_number, type, location, caller_name, caller_phone, status, priority,
         shift, narrative, created, updated, closed_at, is_draft, address)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
    """, ("2026-0004", "MEDICAL", "400 MAPLE DR", "Bob Wilson", "313-555-0004",
          "CLOSED", 2, "A", "Chest pain complaint", closed_ts, ts, ts,
          "400 MAPLE DR, FORD"))

    # 5: Draft incident
    c.execute("""
        INSERT INTO Incidents
        (type, location, status, priority, shift, created, updated, is_draft)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1)
    """, ("UNKNOWN", "", "OPEN", 5, "A", ts, ts))

    conn.commit()

    # ---- UNIT ASSIGNMENTS (for incident 1) ----
    c.execute("""
        INSERT INTO UnitAssignments
        (unit_id, incident_id, dispatched, enroute, arrived)
        VALUES (?, 1, ?, ?, ?)
    """, ("E1", ts, ts, ts))

    c.execute("""
        INSERT INTO UnitAssignments
        (unit_id, incident_id, dispatched, enroute)
        VALUES (?, 1, ?, ?)
    """, ("M1", ts, ts))

    # Closed incident assignments (incident 4)
    c.execute("""
        INSERT INTO UnitAssignments
        (unit_id, incident_id, dispatched, enroute, arrived, cleared, disposition)
        VALUES (?, 4, ?, ?, ?, ?, 'R')
    """, ("E2", closed_ts, closed_ts, closed_ts, ts))

    conn.commit()

    # ---- NARRATIVES ----
    c.execute("""
        INSERT INTO Narrative (incident_id, user, text, timestamp, entry_type)
        VALUES (1, 'DISP1', 'Smoke visible from 2nd floor. Multiple callers.', ?, 'REMARK')
    """, (ts,))
    c.execute("""
        INSERT INTO Narrative (incident_id, user, text, timestamp, entry_type)
        VALUES (1, 'E1', 'Engine 1 on scene. Working fire. Going defensive.', ?, 'REMARK')
    """, (ts,))
    c.execute("""
        INSERT INTO Narrative (incident_id, user, text, timestamp, entry_type)
        VALUES (4, 'DISP1', 'Patient stable. Transported to hospital.', ?, 'REMARK')
    """, (closed_ts,))

    conn.commit()

    # ---- INCIDENT HISTORY ----
    for evt, uid in [("CREATED", None), ("DISPATCH", "E1"), ("ENROUTE", "E1"),
                     ("ARRIVED", "E1"), ("DISPATCH", "M1"), ("ENROUTE", "M1")]:
        c.execute("""
            INSERT INTO IncidentHistory
            (incident_id, event_type, user, unit_id, timestamp, details)
            VALUES (1, ?, 'DISP1', ?, ?, ?)
        """, (evt, uid, ts, f"{evt} {uid or ''}"))

    conn.commit()

    # ---- CONTACTS ----
    contacts = [
        ("Fire Marshal", "313-555-1000", "marshal@ford.gov", "Fire", None),
        ("EMS Director", "313-555-2000", "ems@ford.gov", "EMS", None),
        ("Police Dispatch", "313-555-3000", "pd@ford.gov", "Police", None),
        ("DTE Energy", "800-555-4000", "dte@utility.com", "Utilities", None),
        ("Henry Ford Hospital", "313-555-5000", "er@hfhs.org", "Hospital", None),
    ]
    for name, phone, email, role, sig in contacts:
        c.execute("""
            INSERT INTO Contacts (name, phone, email, role, signal_number, is_active, receive_reports, created, updated)
            VALUES (?, ?, ?, ?, ?, 1, 0, ?, ?)
        """, (name, phone, email, role, sig, ts, ts))

    conn.commit()

    # ---- DAILY LOG ----
    try:
        cols = [r[1] for r in c.execute("PRAGMA table_info(DailyLog)").fetchall()]
        if cols:
            c.execute("""
                INSERT INTO DailyLog (action, details, user, timestamp, incident_id, unit_id)
                VALUES ('SHIFT_START', 'A Shift started', 'DISP1', ?, NULL, NULL)
            """, (ts,))
            c.execute("""
                INSERT INTO DailyLog (action, details, user, timestamp, incident_id, unit_id)
                VALUES ('DISPATCH', 'E1 dispatched to 2026-0001', 'DISP1', ?, 1, 'E1')
            """, (ts,))
            conn.commit()
    except Exception:
        pass

    conn.close()
    return TEST_DB_PATH


# ============================================================================
# Session helpers
# ============================================================================

def make_session_cookies(client, unit_id, shift="A", is_admin=False):
    """Login via the session endpoint and return the client (cookies are stored)."""
    # Use the session login API
    resp = client.post("/api/session/login", json={
        "dispatcher_unit": unit_id,
        "user": unit_id,
        "shift_letter": shift,
    })
    return resp


@pytest.fixture
def admin_session(client, seeded_db):
    """Client authenticated as admin unit 1578."""
    make_session_cookies(client, "1578", "A", is_admin=True)
    return client


@pytest.fixture
def dispatcher_session(client, seeded_db):
    """Client authenticated as normal dispatcher DISP1."""
    make_session_cookies(client, "DISP1", "A")
    return client


@pytest.fixture
def superadmin_session(client, seeded_db):
    """Client authenticated as super-admin unit 17."""
    make_session_cookies(client, "17", "A", is_admin=True)
    return client


# ============================================================================
# DB helpers
# ============================================================================

def get_test_db():
    """Direct connection to test database for assertions."""
    conn = sqlite3.connect(TEST_DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def db_query(sql, params=()):
    """Run a query against the test DB and return list of dicts."""
    conn = get_test_db()
    rows = conn.execute(sql, params).fetchall()
    result = [dict(r) for r in rows]
    conn.close()
    return result


def db_count(table, where="1=1", params=()):
    """Count rows in a table."""
    conn = get_test_db()
    row = conn.execute(f"SELECT COUNT(*) AS cnt FROM {table} WHERE {where}", params).fetchone()
    conn.close()
    return row["cnt"]


# ============================================================================
# Artifact helpers
# ============================================================================

def save_artifact(name, content, subdir="json_snapshots"):
    """Save test artifact to the artifacts directory."""
    path = os.path.join(ARTIFACTS_DIR, subdir, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if isinstance(content, (dict, list)):
        with open(path, "w") as f:
            json.dump(content, f, indent=2, default=str)
    elif isinstance(content, bytes):
        with open(path, "wb") as f:
            f.write(content)
    else:
        with open(path, "w") as f:
            f.write(str(content))
    return path
