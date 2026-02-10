# FORD-CAD Regression Matrix

Repeatable pass/fail verification for every release. Fill in **Pass/Fail** and **Date** columns each cycle.

---

## Quick Reference

```bash
# Automated gates (run first — all must pass before manual checks)
python run_tests.py --quick          # 100 API/E2E tests (~15s)
python run_tests.py                  # 109 tests incl. Playwright (~40s)
python scripts/check_branding.py     # Zero "BOSK" violations
```

---

## A. Automated Test Gates

| # | Gate | Command | Expected | Pass/Fail | Date |
|---|------|---------|----------|-----------|------|
| A1 | API + E2E tests | `python run_tests.py --quick` | 100 passed | | |
| A2 | Full suite (API + Playwright) | `python run_tests.py` | 120 passed (3 may skip) | | |
| A3 | Branding check | `python scripts/check_branding.py` | 0 violations | | |

---

## B. Session & Authentication

| # | Test Case | Steps | Expected Result | Pass/Fail | Date |
|---|-----------|-------|-----------------|-----------|------|
| B1 | Login page loads | Navigate to `/login` | Page loads with FORD-CAD branding | | |
| B2 | Dispatcher login | Login as DISP1, shift A | Redirects to main console | | |
| B3 | Admin login | Login as 1578, shift A | Redirects to main console, admin features visible | | |
| B4 | Header identity | After login | Header shows unit ID / display name, shift letter | | |
| B5 | Connection status | After login | Green dot visible, title="Connected" | | |
| B6 | Logout | Open drawer, click Logout | Returns to login page, session cleared | | |
| B7 | Session persistence | Refresh page after login | Stays logged in, not redirected to login | | |

---

## C. Incident Lifecycle

| # | Test Case | Steps | Expected Result | Pass/Fail | Date |
|---|-----------|-------|-----------------|-----------|------|
| C1 | Create draft | Ctrl+N or toolbar "New" | Draft created, calltaker form opens | | |
| C2 | Save incident | Fill location, type, priority; submit | Incident appears in Active panel with auto-number | | |
| C3 | Prefill fields | POST `/incident/new` with JSON body | Draft pre-populated with provided fields | | |
| C4 | Edit incident | Open IAW, modify fields, save | Changes persist on reload | | |
| C5 | Add remark | Type remark in IAW narrative box | Remark appears in timeline with timestamp | | |
| C6 | Incident history | Open History modal | Past incidents listed, searchable | | |
| C7 | IAW print | Open IAW, click Print | Print-friendly view renders | | |

---

## D. Dispatch & Unit Management

| # | Test Case | Steps | Expected Result | Pass/Fail | Date |
|---|-----------|-------|-----------------|-----------|------|
| D1 | Dispatch unit | IAW dispatch picker, select unit | Unit status → DISPATCHED, appears in IAW cards | | |
| D2 | Multi-unit dispatch | Dispatch 2+ units | All units show DISPATCHED | | |
| D3 | Unit ENROUTE | Set unit enroute | Status updates in Units panel + IAW | | |
| D4 | Unit ARRIVED | Set unit arrived | Status updates, timestamp recorded | | |
| D5 | Unit TRANSPORTING | Set unit transporting | Status updates | | |
| D6 | Unit AT_MEDICAL | Set unit at medical | Status updates | | |
| D7 | Unit ordering | Check admin units list | Canonical order: Command → Personnel → Apparatus → Mutual Aid | | |
| D8 | Self-Initiated (SI) | CLI: `SI <unit>` while unit on incident | Unit auto-clears, mini calltaker opens, new incident created | | |
| D9 | Force dispatch | Dispatch already-assigned unit with force | Old assignment cleared, unit dispatched to new incident | | |

---

## E. Clear & Disposition

| # | Test Case | Steps | Expected Result | Pass/Fail | Date |
|---|-----------|-------|-----------------|-----------|------|
| E1 | Clear single unit | Clear unit with disposition code | Unit → AVAILABLE, disposition recorded | | |
| E2 | Clear last unit | Clear final unit on incident | `requires_event_disposition: true` returned, dialog opens | | |
| E3 | Clear All Units | UAW "Clear All" button | Event disposition dialog opens (not auto-close) | | |
| E4 | Event disposition | Submit event dispo after last-unit clear | Incident closes with `final_disposition` set | | |
| E5 | Invalid disposition | Submit invalid dispo code via context menu | HTTP 400, clear error message | | |
| E6 | Force clear | Clear unit with `force: true` | Skips disposition requirement | | |

---

## F. Messaging

| # | Test Case | Steps | Expected Result | Pass/Fail | Date |
|---|-----------|-------|-----------------|-----------|------|
| F1 | Open drawer | Click messaging toolbar button | Drawer slides open with channel list | | |
| F2 | Send DM | Select unit, type message, send | Message appears in thread | | |
| F3 | Edit message | Right-click/hover → Edit own message | Edited content saved, "(edited)" label shown | | |
| F4 | Delete message | Hover trash icon or right-click → Delete | Message grayed out / removed | | |
| F5 | Channel creation | Create group channel | Channel appears in list, members added | | |
| F6 | Settings panel | Click gear icon in messaging drawer | Settings panel loads | | |
| F7 | Settings persistence | Toggle sound off, refresh page | Sound preference persists | | |

---

## G. Reporting

| # | Test Case | Steps | Expected Result | Pass/Fail | Date |
|---|-----------|-------|-----------------|-----------|------|
| G1 | Open modal | Toolbar or Ctrl+R | Reporting modal loads with 4 tabs | | |
| G2 | Run blotter (HTML) | Select blotter, HTML format, run | Report renders with data | | |
| G3 | Run blotter (JSON) | Select blotter, JSON format, run | Valid JSON returned | | |
| G4 | Report history | History tab in reporting modal | Past runs listed with timestamps | | |
| G5 | Schedule creation | Create daily schedule | Schedule saved, appears in list | | |
| G6 | Delivery channels | Check delivery status tab | Shows configured/unconfigured channels | | |
| G7 | Graceful degradation | Run delivery with unconfigured channel | Logs "would send" message, no crash | | |
| G8 | CLI REPORT command | Type `REPORT` in command line | ReportConfirm.triggerManualReport() fires, report generated | | |

---

## H. Search

| # | Test Case | Steps | Expected Result | Pass/Fail | Date |
|---|-----------|-------|-----------------|-----------|------|
| H1 | Open search | Ctrl+F or toolbar | Search modal opens | | |
| H2 | Search by location | Enter location string | Matching incidents returned | | |
| H3 | Search by unit | Enter unit ID | Matching incidents returned | | |
| H4 | Search by contact | Enter contact name | Matching contacts returned | | |
| H5 | Click result | Click incident in results | IAW opens for that incident | | |
| H6 | Short query rejected | Enter < 2 chars | Appropriate error/no results | | |

---

## I. Admin & Settings

| # | Test Case | Steps | Expected Result | Pass/Fail | Date |
|---|-----------|-------|-----------------|-----------|------|
| I1 | Admin panel access | Login as 1578, open admin | Admin panel loads | | |
| I2 | Non-admin denied | Login as DISP1, try admin endpoint | Access denied (403) | | |
| I3 | Units management | Admin units list | Units in canonical order | | |
| I4 | Settings page | Click preferences button | Settings page loads | | |

---

## J. Tier-3 Modules

| # | Test Case | Steps | Expected Result | Pass/Fail | Date |
|---|-----------|-------|-----------------|-----------|------|
| J1 | Event stream | Open event stream modal | Timeline loads with events | | |
| J2 | Reminders | Open reminders modal | Rules displayed, toggleable | | |
| J3 | Playbooks | Open playbooks modal | Playbooks listed with trigger/action | | |
| J4 | Themes | Open themes modal | 5 presets available, preview works | | |
| J5 | Theme apply | Select preset, apply | Colors change instantly | | |
| J6 | Theme persistence | Apply theme, refresh | Theme persists via localStorage + DB | | |
| J7 | NFIRS modal | Open NFIRS from IAW | Modal loads with `.cad-modal` wrapper, tabs work | | |
| J8 | Mobile MDT | Navigate to `/mobile/mdt` | MDT loads with timeline/chat/photos tabs | | |

---

## K. UI/UX & Accessibility

| # | Test Case | Steps | Expected Result | Pass/Fail | Date |
|---|-----------|-------|-----------------|-----------|------|
| K1 | Modal focus trap | Open any modal, press Tab repeatedly | Focus cycles within modal, never escapes | | |
| K2 | Esc closes modal | Open modal, press Escape | Modal closes | | |
| K3 | Aria labels | Inspect Settings button | Has `aria-label="Preferences"` | | |
| K4 | Dialog roles | Inspect modal HTML | `role="dialog"`, `aria-modal="true"` present | | |
| K5 | Clock contrast | Inspect header clock | Green text on dark background, readable | | |
| K6 | Keyboard shortcuts modal | Press F1 | Keyboard help modal opens with correct wrapper | | |

---

## L. Responsive Layout

| # | Test Case | Steps | Expected Result | Pass/Fail | Date |
|---|-----------|-------|-----------------|-----------|------|
| L1 | 1920x1080 (desktop) | Resize browser | All 3 panels visible side-by-side | | |
| L2 | 1366x768 (laptop) | Resize browser | Panels may wrap, all content scrollable | | |
| L3 | 1200px breakpoint | Resize to 1200px wide | Panels wrap, workspace scrolls vertically | | |
| L4 | 900px breakpoint | Resize to 900px wide | Panels stack vertically, all scroll independently | | |
| L5 | 768px (tablet) | Resize to 768px wide | Touch-friendly layout, toolbar wraps | | |
| L6 | Dashboard modal scroll | Open dashboard on short screen | Modal scrolls internally, no content cut off | | |

---

## M. Data Integrity

| # | Test Case | Steps | Expected Result | Pass/Fail | Date |
|---|-----------|-------|-----------------|-----------|------|
| M1 | Pole field storage | Create incident with pole alpha/number | Sub-fields stored separately in DB columns | | |
| M2 | Pole field retrieval | Edit incident with pole data | Sub-fields returned individually in edit_data | | |
| M3 | Incident number sequence | Create 3 incidents | Numbers increment: YYYY-0001, 0002, 0003 | | |
| M4 | No console errors | Navigate all major flows | No JS errors in DevTools console | | |
| M5 | No 404 resources | Navigate all major flows | No 404s for CSS/JS/API in Network tab | | |

---

## Sign-Off

| Role | Name | Date | Notes |
|------|------|------|-------|
| Developer | | | |
| QA Tester | | | |
| Release Manager | | | |

---

*Generated for FORD-CAD production hardening. Update this matrix when new features are added.*
