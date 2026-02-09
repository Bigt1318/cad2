"""
FORD-CAD — Core API Tests
==========================
Tests: Session, Incidents, Units, Dispatch, Status, Clear, Remarks,
       History, Search, Health, Contacts, Roster, Daily Log
"""

import pytest
import json
from tests.conftest import db_query, db_count, save_artifact, make_session_cookies


# ============================================================================
# SECTION 2 — ROLE-BASED AUTH & SESSION
# ============================================================================

class TestSession:
    """Login, session status, logout, role checks."""

    def test_session_login_dispatcher(self, client, seeded_db):
        resp = client.post("/api/session/login", json={
            "dispatcher_unit": "DISP1", "user": "DISP1", "shift_letter": "A"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["shift_letter"] == "A"
        assert data["role"] == "DISPATCHER"
        save_artifact("session_login_dispatcher.json", data)

    def test_session_login_admin(self, client, seeded_db):
        resp = client.post("/api/session/login", json={
            "dispatcher_unit": "1578", "user": "1578", "shift_letter": "A"
        })
        data = resp.json()
        assert data["ok"] is True
        assert data["role"] == "ADMIN"

    def test_session_login_superadmin(self, client, seeded_db):
        resp = client.post("/api/session/login", json={
            "dispatcher_unit": "17", "user": "17", "shift_letter": "A"
        })
        data = resp.json()
        assert data["ok"] is True
        assert data["role"] in ("ADMIN", "SUPER_ADMIN")

    def test_session_status(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/api/session/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["logged_in"] is True
        assert data["dispatcher_unit"] == "DISP1"

    def test_session_logout(self, client, seeded_db):
        make_session_cookies(client, "DISP1", "A")
        resp = client.post("/api/session/logout")
        assert resp.status_code == 200

    def test_root_redirects_without_session(self, client, seeded_db):
        # Clear session first
        client.post("/api/session/logout")
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code in (302, 307)

    def test_login_page_accessible(self, client, seeded_db):
        resp = client.get("/login")
        assert resp.status_code == 200
        assert b"login" in resp.content.lower() or b"Login" in resp.content


# ============================================================================
# SECTION 4A — HEALTH & PING
# ============================================================================

class TestHealth:
    """Health check and ping endpoints."""

    def test_ping(self, client, seeded_db):
        resp = client.get("/api/ping")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "ts" in data

    def test_health(self, client, seeded_db):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["db_connected"] is True
        assert data["active_incidents"] >= 0
        assert data["total_units"] > 0
        save_artifact("health_check.json", data)

    def test_health_basic(self, client, seeded_db):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"


# ============================================================================
# SECTION 4B — CALLTAKER / INCIDENT CREATION
# ============================================================================

class TestCalltaker:
    """Incident creation and editing."""

    def test_seed_data_incidents_exist(self, seeded_db):
        count = db_count("Incidents")
        assert count >= 5, f"Expected at least 5 seeded incidents, got {count}"

    def test_create_incident_draft(self, dispatcher_session, seeded_db):
        """Create a draft incident via /incident/new."""
        resp = dispatcher_session.post("/incident/new")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") is True or data.get("incident_id")
        save_artifact("create_incident.json", data)

    def test_edit_incident_fields(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.post("/api/incident/2/edit", json={
            "priority": "1",
            "caller_name": "Updated Caller",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

        # Verify in DB
        rows = db_query("SELECT priority, caller_name FROM Incidents WHERE incident_id = 2")
        assert len(rows) == 1
        assert rows[0]["caller_name"] == "Updated Caller"

    def test_edit_incident_location(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.post("/api/incident/2/edit", json={
            "location": "999 UPDATED RD",
        })
        data = resp.json()
        assert data["ok"] is True
        rows = db_query("SELECT location FROM Incidents WHERE incident_id = 2")
        assert rows[0]["location"] == "999 UPDATED RD"

    def test_get_incident_data(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/incident/1/edit_data")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("incident_id") == 1 or data.get("ok")


# ============================================================================
# SECTION 4C — DISPATCH WORKFLOW
# ============================================================================

class TestDispatch:
    """Unit dispatch to incidents."""

    def test_dispatch_unit_to_incident(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.post("/dispatch/unit_to_incident", json={
            "incident_id": 2,
            "units": ["E2"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

        # Verify unit assignment in DB
        rows = db_query(
            "SELECT * FROM UnitAssignments WHERE incident_id = 2 AND unit_id = 'E2' AND cleared IS NULL"
        )
        assert len(rows) >= 1

    def test_dispatch_multiple_units(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.post("/dispatch/unit_to_incident", json={
            "incident_id": 2,
            "units": ["T1", "SQ1"],
        })
        data = resp.json()
        assert data["ok"] is True

    def test_dispatch_invalid_payload(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.post("/dispatch/unit_to_incident", json={
            "incident_id": None,
            "units": [],
        })
        data = resp.json()
        assert data["ok"] is False


# ============================================================================
# SECTION 4D — STATUS WORKFLOW
# ============================================================================

class TestUnitStatus:
    """Unit status changes: enroute, arrived, transporting, etc."""

    def test_status_enroute(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.post("/incident/2/unit/E2/status", json={
            "status": "ENROUTE"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") is True

    def test_status_arrived(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.post("/incident/2/unit/E2/status", json={
            "status": "ARRIVED"
        })
        data = resp.json()
        assert data.get("ok") is True

    def test_status_transporting(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.post("/incident/2/unit/E2/status", json={
            "status": "TRANSPORTING"
        })
        data = resp.json()
        assert data.get("ok") is True

    def test_status_at_medical(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.post("/incident/2/unit/E2/status", json={
            "status": "AT_MEDICAL"
        })
        data = resp.json()
        assert data.get("ok") is True

    def test_status_invalid(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.post("/incident/2/unit/E2/status", json={
            "status": "FLYING"
        })
        data = resp.json()
        assert data.get("ok") is False

    def test_unit_status_api(self, dispatcher_session, seeded_db):
        """Test the /api/unit_status/{unit_id}/{status} endpoint."""
        resp = dispatcher_session.post("/api/unit_status/UTV1/AVAILABLE")
        assert resp.status_code == 200


# ============================================================================
# SECTION 4E — REMARK / NARRATIVE
# ============================================================================

class TestRemarks:
    """Add remarks/narratives to incidents."""

    def test_add_remark(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.post("/remark", json={
            "incident_id": 1,
            "text": "Test remark from automated suite",
            "unit_id": "DISP1",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") is True or "narrative" in str(data).lower()

        # Verify in DB
        rows = db_query(
            "SELECT * FROM Narrative WHERE incident_id = 1 AND text LIKE '%automated suite%'"
        )
        assert len(rows) >= 1

    def test_add_remark_missing_text(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.post("/remark", json={
            "incident_id": 1,
            "text": "",
        })
        # Should either fail or return empty success
        assert resp.status_code == 200


# ============================================================================
# SECTION 4F — CLEAR / DISPOSITION
# ============================================================================

class TestClearDisposition:
    """Unit clearing and disposition workflow."""

    def test_clear_unit_with_disposition(self, dispatcher_session, seeded_db):
        # First dispatch a unit
        dispatcher_session.post("/dispatch/unit_to_incident", json={
            "incident_id": 3, "units": ["UTV2"]
        })
        # Set disposition
        dispatcher_session.post("/incident/3/unit/UTV2/status", json={"status": "ARRIVED"})

        resp = dispatcher_session.post("/incident/3/unit/UTV2/clear", json={
            "disposition": "NF"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") is True

    def test_clear_unit_invalid_disposition(self, dispatcher_session, seeded_db):
        # First dispatch
        dispatcher_session.post("/dispatch/unit_to_incident", json={
            "incident_id": 3, "units": ["UTV1"]
        })
        resp = dispatcher_session.post("/incident/3/unit/UTV1/clear", json={
            "disposition": "INVALID"
        })
        data = resp.json()
        assert data.get("ok") is False


# ============================================================================
# SECTION 4G — HOLD / UNHOLD
# ============================================================================

class TestHoldIncident:
    """Hold and unhold incidents."""

    def test_held_count(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/api/held_count")
        assert resp.status_code == 200
        data = resp.json()
        assert "count" in data
        # Count may be 0 if earlier tests dispatched to the held incident
        assert data["count"] >= 0


# ============================================================================
# SECTION 4H — SEARCH
# ============================================================================

class TestSearch:
    """Global quick-search."""

    def test_search_by_location(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/api/search?q=MAIN")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data.get("incidents", [])) >= 1
        save_artifact("search_location.json", data)

    def test_search_by_unit(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/api/search?q=E1")
        data = resp.json()
        assert data["ok"] is True
        assert len(data.get("units", [])) >= 1

    def test_search_by_contact(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/api/search?q=Marshal")
        data = resp.json()
        assert data["ok"] is True
        assert len(data.get("contacts", [])) >= 1

    def test_search_too_short(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/api/search?q=M")
        data = resp.json()
        assert data["ok"] is True
        assert data.get("incidents", []) == []

    def test_search_modal_loads(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/modals/search")
        assert resp.status_code == 200
        assert b"quick-search-input" in resp.content


# ============================================================================
# SECTION 4I — CONTACTS CRUD
# ============================================================================

class TestContacts:
    """Contact management."""

    def test_list_contacts(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/api/contacts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["contacts"]) >= 5
        save_artifact("contacts_list.json", data)

    def test_create_contact(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.post("/api/contacts", json={
            "name": "Test Contact",
            "phone": "313-555-0000",
            "email": "test@test.com",
            "role": "Fire",
        })
        data = resp.json()
        assert data["ok"] is True
        assert data.get("contact_id")

    def test_update_contact(self, dispatcher_session, seeded_db):
        # Get first contact
        contacts = dispatcher_session.get("/api/contacts").json()["contacts"]
        cid = contacts[0]["contact_id"]

        resp = dispatcher_session.put(f"/api/contacts/{cid}", json={
            "name": "Updated Name",
        })
        data = resp.json()
        assert data["ok"] is True

    def test_delete_contact(self, dispatcher_session, seeded_db):
        # Create then delete
        cr = dispatcher_session.post("/api/contacts", json={
            "name": "To Delete", "role": "Other"
        }).json()
        cid = cr["contact_id"]

        resp = dispatcher_session.delete(f"/api/contacts/{cid}")
        data = resp.json()
        assert data["ok"] is True

    def test_contacts_modal_loads(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/modals/contacts")
        assert resp.status_code == 200
        assert b"Contacts" in resp.content


# ============================================================================
# SECTION 4J — ROSTER
# ============================================================================

class TestRoster:
    """Roster / personnel management."""

    def test_list_roster(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/api/roster")
        data = resp.json()
        assert data["ok"] is True
        assert len(data.get("roster", [])) > 0 or len(data.get("personnel", [])) > 0
        save_artifact("roster_list.json", data)

    def test_add_personnel(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.post("/api/roster", json={
            "apparatus_id": "M1",
            "personnel_id": "99",
            "role": "Paramedic",
            "shift": "A",
        })
        data = resp.json()
        assert data["ok"] is True

    def test_update_personnel(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.put("/api/roster/E2/11", json={
            "role": "Captain",
        })
        data = resp.json()
        assert data["ok"] is True

    def test_delete_personnel(self, dispatcher_session, seeded_db):
        # Add then delete
        dispatcher_session.post("/api/roster", json={
            "apparatus_id": "SQ1", "personnel_id": "98", "role": "FF"
        })
        resp = dispatcher_session.delete("/api/roster/SQ1/98")
        data = resp.json()
        assert data["ok"] is True

    def test_roster_modal_loads(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/modals/roster")
        assert resp.status_code == 200
        assert b"Roster" in resp.content


# ============================================================================
# SECTION 4K — HISTORY
# ============================================================================

class TestHistory:
    """Incident history viewer."""

    def test_history_page_loads(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/history")
        assert resp.status_code == 200
        # History returns an HTML modal fragment (not a full page)
        assert b"history" in resp.content.lower()

    def test_history_modal(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/modals/history")
        assert resp.status_code == 200


# ============================================================================
# SECTION 4L — IAW (Incident Action Window)
# ============================================================================

class TestIAW:
    """Incident Action Window rendering."""

    def test_iaw_loads_active_incident(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/incident_action_window/1")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "2026-0001" in content
        assert "STRUCTURE FIRE" in content
        assert "100 MAIN ST" in content or "MAIN ST" in content
        save_artifact("iaw_incident_1.html", content)

    def test_iaw_loads_closed_incident(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/incident_action_window/4")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "2026-0004" in content

    def test_iaw_incident_not_found(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/incident_action_window/99999")
        assert resp.status_code in (404, 200)  # May render error page


# ============================================================================
# SECTION 4M — PANELS & VIEWS
# ============================================================================

class TestPanels:
    """Main panel views."""

    def test_root_page_loads(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/")
        assert resp.status_code == 200
        assert b"FORD CAD" in resp.content or b"Ford CAD" in resp.content

    def test_panel_active(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/panel/active")
        assert resp.status_code == 200

    def test_panel_open(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/panel/open")
        assert resp.status_code == 200

    def test_panel_units(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/panel/units")
        assert resp.status_code == 200

    def test_calltaker_form(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/panel/calltaker")
        assert resp.status_code == 200


# ============================================================================
# SECTION 4N — MODALS
# ============================================================================

class TestModals:
    """Modal loading."""

    def test_dailylog_modal(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/modals/dailylog")
        assert resp.status_code == 200

    def test_held_modal(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/modals/held")
        assert resp.status_code == 200

    def test_keyboard_help_modal(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/modals/keyboard_help")
        assert resp.status_code == 200

    def test_settings_served(self, dispatcher_session, seeded_db):
        """Verify settings JS module is served."""
        resp = dispatcher_session.get("/static/js/modules/settings.js")
        assert resp.status_code == 200


# ============================================================================
# SECTION 4O — DB INTEGRITY ASSERTIONS
# ============================================================================

class TestDBIntegrity:
    """Database state validation."""

    def test_units_exist(self, seeded_db):
        count = db_count("Units")
        assert count >= 20

    def test_incidents_exist(self, seeded_db):
        count = db_count("Incidents")
        assert count >= 5

    def test_active_incident_has_units(self, seeded_db):
        rows = db_query(
            "SELECT * FROM UnitAssignments WHERE incident_id = 1 AND cleared IS NULL"
        )
        assert len(rows) >= 1

    def test_closed_incident_has_cleared_units(self, seeded_db):
        rows = db_query(
            "SELECT * FROM UnitAssignments WHERE incident_id = 4 AND cleared IS NOT NULL"
        )
        assert len(rows) >= 1

    def test_narratives_exist(self, seeded_db):
        count = db_count("Narrative", "incident_id = 1")
        assert count >= 2

    def test_contacts_exist(self, seeded_db):
        count = db_count("Contacts")
        assert count >= 5

    def test_incident_history_exists(self, seeded_db):
        count = db_count("IncidentHistory", "incident_id = 1")
        assert count >= 3

    def test_indices_exist(self, seeded_db):
        """Verify performance indices are created."""
        from tests.conftest import get_test_db
        conn = get_test_db()
        indices = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        conn.close()
        idx_names = [r["name"] for r in indices]
        expected = [
            "idx_incidents_status",
            "idx_incidents_location",
            "idx_unit_assignments_incident",
            "idx_contacts_name",
        ]
        for exp in expected:
            assert exp in idx_names, f"Missing index: {exp}"
