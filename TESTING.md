# FORD-CAD Testing Guide

## Quick Start

```bash
# Run all API tests (fast, ~15s)
python run_tests.py --quick

# Run full suite including browser UI tests (~60s)
python run_tests.py

# Generate HTML report
python run_tests.py --html
```

## Test Structure

```
tests/
  conftest.py              # Fixtures, seed data, DB helpers
  test_api_core.py         # Core API: session, dispatch, status, search, contacts, roster
  test_api_modules.py      # Modules: reporting, chat, themes, events, playbooks, reminders
  test_e2e_workflows.py    # Full lifecycle: incident create -> dispatch -> clear
  test_ui_playwright.py    # Browser tests: modals, keyboard shortcuts, IAW
```

## Test Categories

| File | Tests | Scope |
|------|-------|-------|
| `test_api_core.py` | 67 | Session auth, incident CRUD, dispatch, status, remarks, clear, search, contacts, roster, history, IAW, panels, modals, DB integrity |
| `test_api_modules.py` | 25 | Reporting, messaging/chat, themes, event stream, playbooks, reminders, mobile MDT, admin |
| `test_e2e_workflows.py` | 6 | Full incident lifecycle, dispatch+mirror, search->navigate, report generation, contact CRUD, roster CRUD |
| `test_ui_playwright.py` | 9 | Page load, toolbar, Ctrl+K search, ESC close, modal loading, IAW render |

## Prerequisites

```bash
pip install pytest pytest-html httpx
pip install playwright pytest-playwright  # For UI tests
python -m playwright install chromium     # Install browser
```

## Architecture

- **Test DB**: `cad_test.db` (auto-created, auto-cleaned)
- **Session-scoped**: Single TestClient shared across tests for speed
- **Seed data**: 21 units, 5 incidents, 5 contacts, personnel assignments
- **Artifacts**: Saved to `test_artifacts/<timestamp>/`

## Artifacts

Test runs produce artifacts in `test_artifacts/`:
- `json_snapshots/` — API response snapshots
- `screenshots/` — Playwright screenshots
- `exported_reports/` — Generated report files

## Running Individual Tests

```bash
# Single test class
python -m pytest tests/test_api_core.py::TestSession -v

# Single test
python -m pytest tests/test_api_core.py::TestSession::test_session_login_dispatcher -v

# By keyword
python -m pytest tests/ -k "search" -v
```
