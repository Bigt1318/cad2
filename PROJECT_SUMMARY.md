# FORD-CAD Project Summary
## Industrial Fire Brigade Computer-Aided Dispatch System

---

## 1. Agency Overview

**Organization:** Ford Motor Company — Kentucky Truck Plant (KTP) Fire Brigade
**Type:** Industrial Fire Brigade (not municipal 911)
**Facility:** Large automotive manufacturing plant with interior and exterior zones
**Personnel:** ~40 firefighters/EMTs across 4 shifts

### Shift Structure
| Shift | Hours | Battalion Chief |
|-------|-------|-----------------|
| A Shift | 0600-1800 | Batt1 (Bill Mullins) |
| B Shift | 1800-0600 | Batt2 (Daniel Highbaugh) |
| C Shift | 0600-1800 | Batt3 (Kevin Jevning) |
| D Shift | 1800-0600 | Batt4 (Shane Carpenter) |

**Fixed Command Staff:**
- 1578 — Matt Mesaros (Safety, Health & Environment Manager)
- Car1 — Jeremy Goodman (Fire Chief)

---

## 2. User Roles

### Dispatchers
- Create and manage incidents via Calltaker panel
- Dispatch units to incidents
- Monitor unit statuses and locations
- Manage daily log entries
- Send remarks and updates to units

### Officers (Battalion Chiefs)
- Command authority on incidents
- Can be designated as "Commanding Unit" on an incident
- Receive shift reports via email/Signal
- Review daily log for issues

### Firefighters/Personnel
- Two-digit badge numbers (11-18 for A, 21-28 for B, 31-38 for C, 41-48 for D)
- Can be assigned to apparatus as crew
- Status tracking (Available, Dispatched, Enroute, Arrived, etc.)
- Individual remarks and activities logged

### Admin
- Full system access
- User account management
- Roster configuration
- Run number management

---

## 3. Core Workflows

### Incident Lifecycle (Start to Finish)

**Step 1: Call Received**
- Dispatcher opens Calltaker panel (left side of screen)
- Enters: Location, Node (plant grid), Pole coordinates, Incident Type, Narrative, Caller info
- System auto-generates incident number (format: YYMMDD-NNN, e.g., 260129-001)

**Step 2: Incident Created**
- Incident appears in "Active Incidents" panel
- Status: OPEN
- No units assigned yet

**Step 3: Dispatch Units**
- Dispatcher clicks incident row → Opens IAW (Incident Action Window)
- Opens Dispatch Picker modal
- Selects units from available roster
- Units status changes to DISPATCHED
- Dispatcher can designate a Commanding Unit

**Step 4: Unit Status Progression**
Units progress through statuses:
```
AVAILABLE → DISPATCHED → ENROUTE → ARRIVED/ON_SCENE → [TRANSPORTING → AT_MEDICAL] → CLEARED
```

**Step 5: Incident Management**
- Add remarks via Remark modal
- Update narrative
- Track unit times (dispatched, enroute, arrived, cleared)
- Mark issues found (quality/safety issues discovered during inspections)

**Step 6: Disposition & Close**
- Each unit gets individual disposition when cleared
- Final incident disposition set
- Incident moves to "Open Incidents" (no active units) then to History
- Incident can also be CANCELLED or HELD

### Daily Log Workflow
Non-emergency activities tracked separately:
1. Select Type = "DAILY LOG" in Calltaker
2. Choose subtype (Building Checks, Training, Maintenance, etc.)
3. Complete activity, add narrative
4. Mark "Issue Found" if problem discovered (highlighted in reports)

---

## 4. Units & Apparatus

### Command Units
| Unit ID | Name | Role |
|---------|------|------|
| 1578 | Matt Mesaros | SHE Manager |
| Car1 | Jeremy Goodman | Fire Chief |
| Batt1 | Bill Mullins | A Shift Battalion Chief |
| Batt2 | Daniel Highbaugh | B Shift Battalion Chief |
| Batt3 | Kevin Jevning | C Shift Battalion Chief |
| Batt4 | Shane Carpenter | D Shift Battalion Chief |

### Personnel (Two-Digit IDs)
- A Shift: 11, 12, 13, 14, 15, 16, 17, 18
- B Shift: 21, 22, 23, 24, 25, 26, 27, 28
- C Shift: 31, 32, 33, 34, 35, 36, 37, 38
- D Shift: 41, 42, 43, 44, 45, 46, 47, 48

### Apparatus (Exterior)
| Unit ID | Name | Type |
|---------|------|------|
| Engine1 (E1) | Engine 1 | Fire Engine |
| Medic1 (M1) | Medic 1 | Ambulance |
| Tower1 (T1) | Tower 1 | Ladder/Aerial |
| Squirt1 (SQ1) | Squirt 1 | Mini pumper |
| UTV1 | UTV 1 | Utility vehicle |
| UTV2 | UTV 2 | Utility vehicle |

### Apparatus (Interior)
| Unit ID | Name | Type |
|---------|------|------|
| Engine2 (E2) | Engine 2 | Interior engine |
| Medic2 (M2) | Medic 2 | Interior ambulance |

### Crew Assignment
- Personnel can be assigned to apparatus (drag & drop or context menu)
- Crew chips display under apparatus in Units panel
- When apparatus is dispatched, crew members go with it

### Mutual Aid
- External units (e.g., HCEMS-Medic) can be added for large incidents
- Tracked separately with `is_mutual_aid` flag

---

## 5. Unique Requirements (Industrial Environment)

### Location System
Unlike street addresses, the plant uses an internal grid:
- **Node:** Building/area identifier
- **Pole Alpha:** Letter coordinate (A-X)
- **Pole Alpha Decimal:** Sub-coordinate
- **Pole Number:** Numeric coordinate (1-88)
- **Pole Number Decimal:** Sub-coordinate

### Daily Log Activities
Industrial fire brigades do extensive inspections:
- Building/Riser Checks
- Fire Extinguisher Checks
- AED Checks
- Safety Walks
- Vehicle Inspections
- Training
- Maintenance
- Standby (production support)
- Bump Tests (gas monitor calibration)

### Issue Tracking
- "Issue Found" flag on daily log entries
- Highlighted in shift reports for management review
- Quality/safety deficiencies discovered during inspections

### Shift Coverage
- Units can be added to coverage from other shifts (overtime, coverage)
- COV/UNCOV commands in CLI
- Coverage badge displayed on units panel

### Interior vs Exterior Operations
- Separate apparatus for interior (manufacturing floor) vs exterior (grounds)
- Different response profiles for plant interior fires vs exterior vegetation

---

## 6. Current Pain Points

### UI/UX Issues
- ~~Modals and popups inconsistent styling~~ (Fixed - dark glass theme)
- ~~Units panel layout broken~~ (Fixed - two-column restored)
- IAW (Incident Action Window) still needs polish for professional look
- Some buttons/controls still have old styling

### Missing Features
- No map integration (would need plant CAD drawings, not Google Maps)
- No automatic unit recommendations based on incident type
- No pre-planned responses (run cards)
- No apparatus out-of-service tracking (OOS with reason)
- No shift trade/swap management

### Data/Reporting
- Reports just added, need testing
- No export to PDF
- No integration with plant safety systems
- Historical data queries limited

### Technical Debt
- Some legacy code paths remain
- Module loading could be cleaner
- Error handling inconsistent in some areas

---

## 7. Priority Features (Requested)

### Immediate (User Requested)
1. **Daily reporting automation** — Auto-send shift reports 30 min before shift change (5:30 AM/PM) via email and Signal ✓ (Built)
2. **SMS messaging** — Send texts to responders via carrier email gateways ✓ (Built)
3. **Professional UI** — Match commercial CAD systems (Tyler, Caliber, etc.) — In Progress

### High Priority
4. **Contacts management** — Maintain phone/email for all personnel for messaging
5. **Report customization** — Allow filtering, date ranges, export formats
6. **Unit OOS tracking** — Mark apparatus out of service with reason and ETA

### Medium Priority
7. **Run cards/pre-plans** — Auto-suggest units based on incident type and location
8. **Keyboard shortcuts** — Full keyboard operation for dispatchers
9. **Multi-monitor support** — Detach panels to separate screens

---

## 8. Technical Architecture

### Stack
- **Backend:** Python 3.11+ with FastAPI
- **Database:** SQLite (single file: `cad.db`)
- **Frontend:** Vanilla JavaScript (ES6 modules), HTMX for reactivity
- **Templates:** Jinja2
- **Styling:** Custom CSS (no framework)

### Key Files
```
main.py                 — FastAPI app, all routes, database schema
reports.py              — Reporting system (email, Signal, SMS)
static/
  style.css             — Main stylesheet
  modals.css            — Modal/popup styles
  js/
    bootloader.js       — Module loader
    modules/
      modules.json      — Module manifest
      commandline.js    — CLI parser
      iaw.js            — Incident Action Window
      uaw2.js           — Unit Action Window
      contextmenu.js    — Right-click menus
      panels.js         — Panel refresh logic
      drag.js           — Drag & drop
      calltaker.js      — Calltaker panel logic
      toast.js          — Notifications
templates/
  index.html            — Main layout
  calltaker.html        — Calltaker panel
  units.html            — Units panel
  active_incidents.html — Active incidents panel
  iaw/                  — IAW fragments
  modals/               — Modal templates
```

### Database Tables
- `Incidents` — All incidents with status, type, location, times
- `Units` — All personnel and apparatus
- `UnitAssignments` — Units assigned to incidents with timestamps
- `PersonnelAssignments` — Crew assigned to apparatus
- `DailyLog` — Daily log entries
- `MasterLog` — Audit log of all actions
- `Narrative` — Incident narratives (append-only)
- `UnitRoster` — Shift assignments
- `UserAccounts` — Authentication
- `ShiftOverrides` — Coverage assignments
- `Contacts` — Contact info for messaging

### Technical Constraints
- **Offline operation:** System must work without internet (plant network only)
- **Single user primary:** One dispatcher typically, but multiple viewers possible
- **No external dependencies:** Can't rely on cloud services
- **Windows environment:** Runs on Windows workstations
- **Browser-based:** Chrome/Edge, no native app

### Running the System
```powershell
cd C:\cad2
.\.venv\Scripts\Activate.ps1
python -m uvicorn main:app --reload --port 8000
# Access at http://127.0.0.1:8000
```

---

## 9. UI Design Language

### Current Theme
- Light theme for panels (white/gray backgrounds)
- Dark glass effect for popups/modals (rgba(15, 23, 34, 0.98) with backdrop blur)
- Ford blue (#003a8f) for header and accents
- Status colors:
  - Dispatched: Orange (#f97316)
  - Enroute: Yellow (#eab308)
  - Arrived/On Scene: Green (#16a34a)
  - Transporting: Purple (#a855f7)
  - At Medical: Cyan (#06b6d4)
  - OOS/Unavailable: Gray (#64748b)

### Interaction Patterns
- Right-click context menus for unit actions
- Click row to open action window
- Drag & drop for unit assignment
- Command line for power users (bottom of screen)
- HTMX for panel refresh without full page reload

### CLI Commands
```
HELP                    — Show all commands
<unit> ST <status>      — Set unit status
<unit> DI <inc#>        — Dispatch unit to incident
<unit> CLR              — Clear unit from incident
<unit> COV              — Add unit to shift coverage
<unit> UNCOV            — Remove from coverage
<inc#>                  — Open incident action window
HELD                    — Show held incidents
DAILYLOG                — Open daily log
```

---

## 10. Reference Commercial Systems

The goal is to match the professional look/feel of:
- **Tyler/New World CAD** — Clean, information-dense
- **Caliber/Harris)** — Dark theme option, good status visibility
- **Spillman Flex** — Modern responsive design
- **10-8 Systems** — Industrial-focused
- **Interact CAD** — Fire-specific workflows

Key characteristics to emulate:
- High information density without clutter
- Clear visual hierarchy
- Instant status recognition via color
- Keyboard-first operation
- Minimal clicks for common actions

---

## 11. Contact & Support

**Developer:** [User's contact info]
**Repository:** https://github.com/Bigt1318/cad2.git
**Branch:** master

---

*Document generated: 2026-01-29*
*Last commit: 5fcac4f — Major UI overhaul*
