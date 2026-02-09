"""
FORD-CAD — Module API Tests
=============================
Tests: Reporting, Messaging/Chat, Themes, Event Stream, Playbooks, Reminders, Mobile
"""

import pytest
from tests.conftest import db_query, db_count, save_artifact, make_session_cookies


# ============================================================================
# REPORTING MODULE
# ============================================================================

class TestReporting:
    """Reporting v2 endpoints."""

    def test_reporting_templates(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/api/reporting/templates")
        assert resp.status_code == 200
        data = resp.json()
        assert "templates" in data
        assert len(data["templates"]) >= 1
        save_artifact("reporting_templates.json", data)

    def test_reporting_delivery_status(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/api/reporting/delivery/status")
        assert resp.status_code == 200

    def test_reporting_run_blotter(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.post("/api/reporting/run", json={
            "report_type": "blotter",
            "format": "json",
        })
        assert resp.status_code == 200
        data = resp.json()
        save_artifact("report_blotter.json", data)

    def test_reporting_history(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/api/reporting/history")
        assert resp.status_code == 200
        data = resp.json()
        assert "history" in data

    def test_reporting_modal(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/modals/reporting")
        assert resp.status_code == 200

    def test_reporting_schedules(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/api/reporting/schedules")
        assert resp.status_code == 200


# ============================================================================
# MESSAGING / CHAT
# ============================================================================

class TestMessaging:
    """Chat v2 channel-based messaging."""

    def test_chat_channels_list(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/api/chat/channels")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") is True
        save_artifact("chat_channels.json", data)

    def test_chat_create_channel(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.post("/api/chat/channels", json={
            "title": "Test Ops Channel",
            "members": [],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") is True
        save_artifact("chat_create_channel.json", data)

    def test_chat_send_message(self, dispatcher_session, seeded_db):
        # First create a channel
        cr = dispatcher_session.post("/api/chat/channels", json={
            "title": "Msg Test Channel",
        }).json()
        if cr.get("ok") and cr.get("channel"):
            ch_id = cr["channel"]["id"]
            resp = dispatcher_session.post(f"/api/chat/channel/{ch_id}/send", json={
                "body": "Test message from automated suite",
            })
            assert resp.status_code == 200
            save_artifact("chat_send_message.json", resp.json())

    def test_messaging_modal(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/modal/messaging")
        assert resp.status_code == 200


# ============================================================================
# THEMES
# ============================================================================

class TestThemes:
    """User theme system."""

    def test_theme_presets(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/api/themes/presets")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") is True
        assert len(data.get("presets", [])) >= 3
        save_artifact("theme_presets.json", data)

    def test_theme_active(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/api/themes/active")
        assert resp.status_code == 200

    def test_theme_save(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.post("/api/themes/save", json={
            "slot": 1,
            "name": "Test Theme",
            "tokens": {"--cad-bg-app": "#1a1a2e"},
        })
        assert resp.status_code == 200

    def test_theme_modal(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/modals/themes")
        assert resp.status_code == 200


# ============================================================================
# EVENT STREAM
# ============================================================================

class TestEventStream:
    """Event stream / timeline."""

    def test_event_stream_list(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/api/event-stream")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") is True
        save_artifact("eventstream.json", data)

    def test_event_stream_modal(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/modals/event-stream")
        assert resp.status_code == 200

    def test_event_stream_filter(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/api/event-stream?category=incident")
        assert resp.status_code == 200


# ============================================================================
# PLAYBOOKS
# ============================================================================

class TestPlaybooks:
    """Workflow automation playbooks."""

    def test_playbooks_list(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/api/playbooks")
        assert resp.status_code == 200
        data = resp.json()
        save_artifact("playbooks.json", data)

    def test_playbooks_modal(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/modals/playbooks")
        assert resp.status_code == 200


# ============================================================================
# REMINDERS
# ============================================================================

class TestReminders:
    """Smart reminders."""

    def test_reminders_rules(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/api/reminders/rules")
        assert resp.status_code == 200

    def test_reminders_active(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/api/reminders/active")
        assert resp.status_code == 200

    def test_reminders_modal(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/modals/reminders")
        assert resp.status_code == 200


# ============================================================================
# MOBILE
# ============================================================================

class TestMobile:
    """Mobile MDT endpoints."""

    def test_mobile_mdt(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/mobile/mdt/E1")
        assert resp.status_code == 200

    def test_mobile_timeline(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/mobile/mdt/E1/timeline")
        assert resp.status_code == 200
        assert b"Timeline" in resp.content

    def test_mobile_photos(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/mobile/mdt/E1/photos")
        assert resp.status_code == 200
        assert b"Photos" in resp.content

    def test_mobile_messages(self, dispatcher_session, seeded_db):
        resp = dispatcher_session.get("/mobile/mdt/E1/messages")
        assert resp.status_code == 200
        assert b"Chat" in resp.content


# ============================================================================
# ADMIN ENDPOINTS
# ============================================================================

class TestAdmin:
    """Admin-only endpoints and role-gating."""

    def test_admin_units_list(self, admin_session, seeded_db):
        make_session_cookies(admin_session, "1578", "A")
        resp = admin_session.get("/api/admin/units?user=1578")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    def test_admin_access_denied_for_dispatcher(self, dispatcher_session, seeded_db):
        make_session_cookies(dispatcher_session, "DISP1", "A")
        resp = dispatcher_session.get("/api/admin/units?user=DISP1")
        # Should be 403
        assert resp.status_code == 403
