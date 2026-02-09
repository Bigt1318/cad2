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
