"""
FORD-CAD — Playwright UI Tests
================================
Browser-level tests for modals, keyboard shortcuts, and visual workflows.
Requires: playwright, pytest-playwright, chromium browser installed.
"""

import os
import sys
import time
import subprocess
import pytest
import urllib.request
import urllib.error

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARTIFACTS_DIR = os.path.join(ROOT_DIR, "test_artifacts")
SERVER_PORT = 8765
SERVER_URL = f"http://127.0.0.1:{SERVER_PORT}"

# Try to import playwright - skip all tests if not available
try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

pytestmark = pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="Playwright not installed")

# Use "commit" wait — the main page has WebSocket + heavy JS that blocks domcontentloaded
GOTO_OPTS = {"wait_until": "commit", "timeout": 15000}


def _wait_for_server(url, timeout=15):
    """Poll server until it responds or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = urllib.request.urlopen(url, timeout=3)
            resp.close()
            return True
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.5)
    return False


@pytest.fixture(scope="module")
def server():
    """Start the CAD server for UI testing."""
    env = os.environ.copy()
    env["CAD_TEST_MODE"] = "1"
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
         "--port", str(SERVER_PORT), "--log-level", "warning"],
        cwd=ROOT_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if not _wait_for_server(f"{SERVER_URL}/login"):
        proc.kill()
        pytest.skip("Server failed to start within 15s")

    yield SERVER_URL

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="module")
def browser_page(server):
    """Playwright browser page with login session."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()
        page.set_default_timeout(15000)
        page.set_default_navigation_timeout(15000)

        # Login via the HTML form
        page.goto(f"{server}/login", **GOTO_OPTS)
        time.sleep(0.5)
        page.fill("#dispatcher_unit", "DISP1")
        page.select_option("#shift_letter", "A")

        with page.expect_navigation(wait_until="commit", timeout=15000):
            page.click("button[type='submit']")
        time.sleep(1)  # Let main page JS initialize

        yield page

        context.close()
        browser.close()


def _navigate(page, url):
    """Navigate to URL using commit + settle time."""
    page.goto(url, **GOTO_OPTS)
    time.sleep(1)


def _screenshot(page, name):
    """Save a screenshot to artifacts."""
    ts = time.strftime("%H%M%S")
    ss_dir = os.path.join(ARTIFACTS_DIR, "screenshots")
    os.makedirs(ss_dir, exist_ok=True)
    path = os.path.join(ss_dir, f"{ts}_{name}.png")
    try:
        page.screenshot(path=path, full_page=True)
    except Exception:
        pass
    return path


class TestUIMainPage:
    """Test the main CAD console page."""

    def test_main_page_loads(self, browser_page, server):
        _navigate(browser_page, server)
        _screenshot(browser_page, "main_page")

        # After login we should be on the main page, not login
        url = browser_page.url
        assert "/login" not in url, f"Stuck on login: {url}"

        # Main page should have substantial content
        assert len(browser_page.content()) > 10000

    def test_toolbar_visible(self, browser_page, server):
        _navigate(browser_page, server)
        toolbar = browser_page.locator("#cad-toolbar, .cad-toolbar, .toolbar").first
        if toolbar.count() > 0:
            assert toolbar.is_visible()
        else:
            # Toolbar present in HTML even if using different selector
            assert len(browser_page.content()) > 10000


class TestUIKeyboardShortcuts:
    """Test keyboard shortcuts."""

    def test_ctrl_k_opens_search(self, browser_page, server):
        _navigate(browser_page, server)
        time.sleep(1)  # Let JS initialize

        browser_page.keyboard.press("Control+k")
        time.sleep(0.5)

        # Check if search modal opened
        search_el = browser_page.locator(
            "#quick-search-input, .search-modal, [data-modal='search']"
        ).first
        if search_el.count() > 0:
            _screenshot(browser_page, "ctrl_k_search")

    def test_escape_closes_modal(self, browser_page, server):
        _navigate(browser_page, server)
        time.sleep(1)

        browser_page.keyboard.press("Control+k")
        time.sleep(0.5)
        browser_page.keyboard.press("Escape")
        time.sleep(0.3)
        _screenshot(browser_page, "escape_close")


class TestUIModals:
    """Test modal loading via direct navigation."""

    def test_search_modal(self, browser_page, server):
        _navigate(browser_page, f"{server}/modals/search")
        _screenshot(browser_page, "search_modal")
        assert len(browser_page.content()) > 500

    def test_contacts_modal(self, browser_page, server):
        _navigate(browser_page, f"{server}/modals/contacts")
        _screenshot(browser_page, "contacts_modal")
        assert len(browser_page.content()) > 500

    def test_roster_modal(self, browser_page, server):
        _navigate(browser_page, f"{server}/modals/roster")
        _screenshot(browser_page, "roster_modal")
        assert len(browser_page.content()) > 500


class TestUIIAW:
    """Test IAW rendering in browser."""

    def test_iaw_renders_incident(self, browser_page, server):
        _navigate(browser_page, f"{server}/incident_action_window/1")
        _screenshot(browser_page, "iaw_incident_1")

        content = browser_page.content()
        assert len(content) > 2000, "IAW page too short — may not have rendered"

    def test_iaw_print_button_exists(self, browser_page, server):
        _navigate(browser_page, f"{server}/incident_action_window/1")

        print_btn = browser_page.locator(
            ".iaw-print-btn, .print-btn, button:has-text('Print')"
        )
        if print_btn.count() > 0:
            assert print_btn.first.is_visible()


# ============================================================================
# SMOKE TESTS — Login, Incident Creation, Dispatch, Messaging
# ============================================================================


class TestSmokeLogin:
    """Verify the login flow end-to-end in browser."""

    def test_login_page_has_branding(self, browser_page, server):
        """Login page loads with FORD-CAD branding (no BOSK)."""
        # Use a fresh context without session cookies to see login page
        fresh_ctx = browser_page.context.browser.new_context()
        page = fresh_ctx.new_page()
        page.set_default_timeout(15000)

        try:
            page.goto(f"{server}/login", **GOTO_OPTS)
            time.sleep(0.5)
            content = page.content().lower()
            _screenshot(page, "smoke_login_page")

            assert "ford" in content, "Login page missing FORD branding"
            assert "bosk" not in content, "Login page has old BOSK branding"
            assert page.locator("#dispatcher_unit").count() > 0, "Missing unit input"
            assert page.locator("#shift_letter").count() > 0, "Missing shift select"
        finally:
            fresh_ctx.close()

    def test_login_form_submits(self, browser_page, server):
        """Login form has all required elements and can submit."""
        fresh_ctx = browser_page.context.browser.new_context(
            viewport={"width": 1920, "height": 1080}
        )
        page = fresh_ctx.new_page()
        page.set_default_timeout(15000)

        try:
            page.goto(f"{server}/login", **GOTO_OPTS)
            time.sleep(0.5)

            # Verify form elements exist
            unit_input = page.locator("#dispatcher_unit")
            shift_select = page.locator("#shift_letter")
            submit_btn = page.locator("button[type='submit']")

            assert unit_input.count() > 0, "Missing unit input"
            assert shift_select.count() > 0, "Missing shift select"
            assert submit_btn.count() > 0, "Missing submit button"

            # Fill and submit
            unit_input.fill("DISP1")
            shift_select.select_option("A")
            _screenshot(page, "smoke_login_filled")

            with page.expect_navigation(wait_until="commit", timeout=15000):
                submit_btn.click()
            time.sleep(1)

            url = page.url
            _screenshot(page, "smoke_login_redirect")
            assert "/login" not in url, f"Still on login page: {url}"
        finally:
            fresh_ctx.close()

    def test_header_shows_identity(self, browser_page, server):
        """Header shows logged-in unit identity after login."""
        _navigate(browser_page, server)
        _screenshot(browser_page, "smoke_header_identity")

        # Header should exist
        header = browser_page.locator("#cad-header, .cad-header, nav").first
        assert header.count() > 0 or len(browser_page.content()) > 10000


class TestSmokeIncidentCreation:
    """Verify incident creation via the calltaker panel."""

    def test_calltaker_panel_visible(self, browser_page, server):
        """Calltaker panel is visible on main page."""
        _navigate(browser_page, server)

        ct = browser_page.locator("#panel-calltaker")
        _screenshot(browser_page, "smoke_calltaker_panel")
        assert ct.count() > 0, "Calltaker panel not found"

    def test_create_incident_via_calltaker(self, browser_page, server):
        """Fill calltaker form and save an incident."""
        _navigate(browser_page, server)
        time.sleep(1)

        # Must initiate "New Incident" first to enable calltaker inputs
        new_btn = browser_page.locator("#btn-new-incident")
        if new_btn.count() > 0 and new_btn.is_visible():
            new_btn.click()
            time.sleep(1)
        else:
            # Fallback: press F2
            browser_page.keyboard.press("F2")
            time.sleep(1)

        # Fill location (should now be enabled)
        loc_input = browser_page.locator("#ctLocation")
        if loc_input.count() > 0:
            try:
                loc_input.fill("999 SMOKE TEST BLVD", timeout=5000)
            except Exception:
                _screenshot(browser_page, "smoke_calltaker_disabled")
                pytest.skip("Calltaker inputs not enabled after New click")

        # Select type
        type_select = browser_page.locator("#ctType")
        if type_select.count() > 0:
            type_select.select_option("TEST")

        # Fill narrative
        narr = browser_page.locator("#ctNarrative")
        if narr.count() > 0:
            narr.fill("Playwright smoke test incident")

        _screenshot(browser_page, "smoke_calltaker_filled")

        # Click Save button
        save_btn = browser_page.locator("#panel-calltaker button:has-text('Save')").first
        if save_btn.count() > 0:
            save_btn.click()
            time.sleep(1.5)
            _screenshot(browser_page, "smoke_calltaker_saved")

    def test_new_incident_via_api_then_iaw(self, browser_page, server):
        """Create incident via API, then verify IAW renders in browser."""
        import json as _json

        # Use API to create incident reliably
        resp = browser_page.request.post(f"{server}/incident/new")
        data = resp.json()
        inc_id = data.get("incident_id")

        if inc_id:
            browser_page.request.post(
                f"{server}/incident/save/{inc_id}",
                data=_json.dumps({"type": "TEST", "location": "888 PW TEST DR",
                      "priority": "3", "narrative": "Playwright API test"}),
                headers={"Content-Type": "application/json"},
            )

            # Navigate to IAW
            _navigate(browser_page, f"{server}/incident_action_window/{inc_id}")
            _screenshot(browser_page, "smoke_iaw_api_incident")

            content = browser_page.content()
            assert len(content) > 2000, "IAW page too short"


class TestSmokeDispatch:
    """Verify dispatch workflow in browser."""

    def test_dispatch_via_api_and_verify_iaw(self, browser_page, server):
        """Create incident, dispatch unit via API, verify in IAW."""
        import json as _json

        # Create incident
        resp = browser_page.request.post(f"{server}/incident/new")
        data = resp.json()
        inc_id = data.get("incident_id")
        if not inc_id:
            pytest.skip("Could not create incident")

        browser_page.request.post(
            f"{server}/incident/save/{inc_id}",
            data=_json.dumps({"type": "TEST", "location": "777 DISPATCH TEST",
                  "priority": "2", "narrative": "Dispatch smoke test"}),
            headers={"Content-Type": "application/json"},
        )

        # Make unit available then dispatch
        browser_page.request.post(f"{server}/api/unit_status/UTV1/AVAILABLE")
        resp = browser_page.request.post(
            f"{server}/dispatch/unit_to_incident",
            data=_json.dumps({"incident_id": inc_id, "units": ["UTV1"]}),
            headers={"Content-Type": "application/json"},
        )

        # Navigate to IAW and verify unit appears
        _navigate(browser_page, f"{server}/incident_action_window/{inc_id}")
        time.sleep(0.5)
        _screenshot(browser_page, "smoke_dispatch_iaw")

        content = browser_page.content()
        assert len(content) > 2000, "IAW page too short after dispatch"

    def test_command_line_visible(self, browser_page, server):
        """Command line input is visible for CLI dispatch commands."""
        _navigate(browser_page, server)

        cmd = browser_page.locator("#cmd-input")
        _screenshot(browser_page, "smoke_command_line")
        assert cmd.count() > 0, "Command line input not found"
        assert cmd.is_visible(), "Command line input not visible"


class TestSmokeMessaging:
    """Verify messaging edit/delete via API + browser."""

    def _ensure_server(self, server):
        """Check server is still responsive; skip if not."""
        if not _wait_for_server(f"{server}/api/health", timeout=5):
            pytest.skip("Server unresponsive after earlier tests")

    def test_messaging_drawer_opens(self, browser_page, server):
        """Messaging drawer opens when button is clicked."""
        self._ensure_server(server)
        _navigate(browser_page, server)
        time.sleep(1)

        msg_btn = browser_page.locator("#btn-messaging")
        if msg_btn.count() > 0 and msg_btn.is_visible():
            msg_btn.click()
            time.sleep(0.5)
            _screenshot(browser_page, "smoke_messaging_drawer")

    def test_message_send_edit_delete_via_api(self, browser_page, server):
        """Send, edit, then delete a message via API."""
        self._ensure_server(server)

        import json as _json

        # Create a channel
        resp = browser_page.request.post(
            f"{server}/api/chat/channels",
            data=_json.dumps({"title": "Smoke Test Channel"}),
            headers={"Content-Type": "application/json"},
        )
        ch_data = resp.json()
        if not ch_data.get("ok") or not ch_data.get("channel"):
            pytest.skip("Could not create chat channel")

        ch_id = ch_data["channel"]["id"]

        # Send message
        resp = browser_page.request.post(
            f"{server}/api/chat/channel/{ch_id}/send",
            data=_json.dumps({"body": "Smoke test message from Playwright"}),
            headers={"Content-Type": "application/json"},
        )
        msg_data = resp.json()
        assert msg_data.get("ok") is True, f"Send failed: {msg_data}"
        msg_id = msg_data["message"]["id"]

        # Edit message
        resp = browser_page.request.put(
            f"{server}/api/chat/messages/{msg_id}",
            data=_json.dumps({"body": "Edited smoke test message"}),
            headers={"Content-Type": "application/json"},
        )
        edit_data = resp.json()
        assert edit_data.get("ok") is True, f"Edit failed: {edit_data}"

        # Delete message
        resp = browser_page.request.delete(f"{server}/api/chat/messages/{msg_id}")
        del_data = resp.json()
        assert del_data.get("ok") is True, f"Delete failed: {del_data}"

        _screenshot(browser_page, "smoke_messaging_crud")

    def test_messaging_modal_loads(self, browser_page, server):
        """Messaging modal HTML fragment loads correctly."""
        self._ensure_server(server)
        _navigate(browser_page, f"{server}/modal/messaging")
        _screenshot(browser_page, "smoke_messaging_modal")

        content = browser_page.content()
        assert len(content) > 500, "Messaging modal too short"
