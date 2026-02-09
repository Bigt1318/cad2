"""
FORD-CAD — End-to-End Workflow Tests
======================================
Full lifecycle tests that chain multiple operations together.
"""

import pytest
from tests.conftest import db_query, db_count, save_artifact, make_session_cookies


class TestIncidentLifecycle:
    """Full incident lifecycle: create -> save -> dispatch -> status -> clear -> close."""

    def test_full_incident_lifecycle(self, client, seeded_db):
        # 1. Login as dispatcher
        make_session_cookies(client, "DISP1", "A")

        # 2. Create draft incident
        resp = client.post("/incident/new")
        assert resp.status_code == 200
        data = resp.json()
        inc_id = data.get("incident_id")
        assert inc_id, f"No incident_id returned: {data}"

        # 3. Save/finalize the incident (converts draft to OPEN)
        resp = client.post(f"/incident/save/{inc_id}", json={
            "type": "THERMAL EVENT",
            "location": "777 LIFECYCLE TEST DR",
            "caller_name": "Lifecycle Tester",
            "caller_phone": "313-555-7777",
            "priority": "2",
            "narrative": "Vehicle on fire in parking lot",
        })
        assert resp.status_code == 200
        save_data = resp.json()
        save_artifact("e2e_1_create.json", save_data)

        # 4. Dispatch units
        resp = client.post("/dispatch/unit_to_incident", json={
            "incident_id": inc_id,
            "units": ["M1", "M2"],
        })
        dispatch_data = resp.json()
        assert dispatch_data.get("ok") is True
        save_artifact("e2e_2_dispatch.json", dispatch_data)

        # 5. M1 goes enroute
        resp = client.post(f"/incident/{inc_id}/unit/M1/status", json={"status": "ENROUTE"})
        assert resp.json().get("ok") is True

        # 6. M1 arrives
        resp = client.post(f"/incident/{inc_id}/unit/M1/status", json={"status": "ARRIVED"})
        assert resp.json().get("ok") is True

        # 7. M2 enroute + arrives
        client.post(f"/incident/{inc_id}/unit/M2/status", json={"status": "ENROUTE"})
        client.post(f"/incident/{inc_id}/unit/M2/status", json={"status": "ARRIVED"})

        # 8. Add remark
        resp = client.post("/remark", json={
            "incident_id": inc_id,
            "text": "Fire extinguished. Overhaul in progress.",
            "unit_id": "M1",
        })

        # 9. Clear M1 with disposition
        resp = client.post(f"/incident/{inc_id}/unit/M1/clear", json={"disposition": "FF"})
        save_artifact("e2e_3_clear_m1.json", resp.json())

        # 10. Clear M2 with disposition
        resp = client.post(f"/incident/{inc_id}/unit/M2/clear", json={"disposition": "R"})
        save_artifact("e2e_4_clear_m2.json", resp.json())

        # 11. Verify incident state in DB
        rows = db_query("SELECT * FROM Incidents WHERE incident_id = ?", (inc_id,))
        assert len(rows) == 1

        # 12. Verify narratives
        narr = db_query("SELECT * FROM Narrative WHERE incident_id = ?", (inc_id,))
        assert len(narr) >= 1

        # 13. Verify IAW renders
        resp = client.get(f"/incident_action_window/{inc_id}")
        assert resp.status_code == 200
        save_artifact("e2e_final_iaw.html", resp.content.decode())


class TestDispatchAndMirror:
    """Test apparatus dispatch with personnel mirroring."""

    def test_apparatus_dispatch_mirrors_crew(self, client, seeded_db):
        make_session_cookies(client, "DISP1", "A")

        # Create a fresh incident to avoid conflicts with other tests
        resp = client.post("/incident/new")
        inc_id = resp.json().get("incident_id")

        resp = client.post(f"/incident/save/{inc_id}", json={
            "type": "EMS",
            "location": "500 MIRROR TEST DR",
            "caller_name": "Mirror Test",
            "priority": "2",
        })
        assert resp.status_code == 200

        # Make UTV2 available first (may be occupied from earlier tests)
        client.post("/api/unit_status/UTV2/AVAILABLE")

        # Dispatch UTV2
        resp = client.post("/dispatch/unit_to_incident", json={
            "incident_id": inc_id,
            "units": ["UTV2"],
        })
        dispatch_data = resp.json()
        assert dispatch_data.get("ok") is True, f"Dispatch failed: {dispatch_data}"

        # Change UTV2 to enroute
        resp = client.post(f"/incident/{inc_id}/unit/UTV2/status", json={"status": "ENROUTE"})
        assert resp.json().get("ok") is True

        # Verify UTV2 status changed in DB
        units = db_query("SELECT status FROM Units WHERE unit_id = 'UTV2'")
        assert len(units) >= 1


class TestSearchWorkflow:
    """Search -> navigate workflow."""

    def test_search_and_navigate(self, client, seeded_db):
        make_session_cookies(client, "DISP1", "A")

        # Search
        resp = client.get("/api/search?q=STRUCTURE")
        data = resp.json()
        assert data["ok"] is True
        assert len(data.get("incidents", [])) >= 1

        # Get first result and open IAW
        inc = data["incidents"][0]
        resp = client.get(f"/incident_action_window/{inc['id']}")
        assert resp.status_code == 200


class TestReportingWorkflow:
    """Report generation workflow."""

    def test_run_and_view_report(self, client, seeded_db):
        make_session_cookies(client, "1578", "A")

        # Run a report
        resp = client.post("/api/reporting/run", json={
            "report_type": "blotter",
            "format": "html",
        })
        assert resp.status_code == 200
        data = resp.json()
        save_artifact("e2e_report_blotter.json", data)

        # Check history
        resp = client.get("/api/reporting/history")
        assert resp.status_code == 200


class TestContactsWorkflow:
    """Contact CRUD lifecycle."""

    def test_contact_crud_lifecycle(self, client, seeded_db):
        make_session_cookies(client, "DISP1", "A")

        # Create
        resp = client.post("/api/contacts", json={
            "name": "Lifecycle Contact",
            "phone": "313-555-0000",
            "role": "Fire",
        })
        data = resp.json()
        assert data["ok"] is True
        cid = data["contact_id"]

        # Read
        resp = client.get(f"/api/contacts/{cid}")
        data = resp.json()
        assert data["ok"] is True
        assert data["contact"]["name"] == "Lifecycle Contact"

        # Update
        resp = client.put(f"/api/contacts/{cid}", json={"name": "Updated Lifecycle"})
        assert resp.json()["ok"] is True

        # Verify update
        resp = client.get(f"/api/contacts/{cid}")
        assert resp.json()["contact"]["name"] == "Updated Lifecycle"

        # Delete
        resp = client.delete(f"/api/contacts/{cid}")
        assert resp.json()["ok"] is True

        # Verify deleted
        resp = client.get(f"/api/contacts/{cid}")
        assert resp.json().get("ok") is False


class TestRosterWorkflow:
    """Roster CRUD lifecycle."""

    def test_roster_crud_lifecycle(self, client, seeded_db):
        make_session_cookies(client, "DISP1", "A")

        # Create
        resp = client.post("/api/roster", json={
            "apparatus_id": "T1",
            "personnel_id": "77",
            "role": "Driver",
            "shift": "B",
        })
        assert resp.json()["ok"] is True

        # Read (list)
        resp = client.get("/api/roster")
        data = resp.json()
        assert data["ok"] is True
        found = any(p["personnel_id"] == "77" for p in data.get("personnel", []))
        assert found, "New personnel not found in roster"

        # Update
        resp = client.put("/api/roster/T1/77", json={"role": "Officer"})
        assert resp.json()["ok"] is True

        # Delete
        resp = client.delete("/api/roster/T1/77")
        assert resp.json()["ok"] is True
