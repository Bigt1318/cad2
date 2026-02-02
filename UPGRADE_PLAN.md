# FORD-CAD Upgrade Plan
## Complete System Audit & Production Readiness

**Audit Date:** February 2, 2026  
**Auditor:** Rosie (AI Assistant)

---

## 📊 Current System Status

### Backend (Python/FastAPI)
| Metric | Value | Status |
|--------|-------|--------|
| Main code | 9,389 lines | ✅ Substantial |
| Routes | 121 endpoints | ✅ Complete |
| Error handling | 114 points | ✅ Good coverage |
| Database | SQLite (160KB) | ✅ Working |
| Units loaded | 42 units | ✅ Correct |
| Roster entries | 36 assignments | ✅ Correct |

### Frontend
| Component | Files | Status |
|-----------|-------|--------|
| CSS files | 5 files | ⚠️ Needs cleanup |
| JS modules | 26 modules | ⚠️ 51 debug logs |
| Templates | 15 HTML files | ✅ Complete |
| Images | Present | ✅ OK |

### Database Tables
- ✅ Units (42 rows)
- ✅ UnitRoster (36 rows)
- ✅ Incidents (empty - ready)
- ✅ UnitAssignments (empty - ready)
- ✅ MasterLog (audit trail)
- ✅ Contacts (empty - ready)
- ✅ DailyLog (empty - ready)

---

## 🔴 Critical Issues (Must Fix)

### 1. CSS Conflicts
**Problem:** Multiple CSS files with overlapping styles
- `static/css/ford-cad-v4.css` (new theme)
- `static/css/design-system.css` (old)
- `static/css/themes.css` (old)
- `static/style.css` (legacy)
- `static/modals.css` (modals)

**Solution:** 
- Consolidate into single `ford-cad-v4.css`
- Keep `modals.css` separate
- Remove/archive old CSS files
- Update all template references

### 2. Login Page Styling
**Problem:** Login page uses old dark theme, doesn't match new design
**Solution:** Update `templates/login.html` to use Ford V4 theme

### 3. Debug Code in Production
**Problem:** 51 `console.log` statements in JavaScript
**Solution:** Remove or wrap in debug flag

---

## 🟡 High Priority (Should Fix)

### 4. Layout Issues
- Calltaker panel needs compact form layout
- Units panel needs proper two-column scrolling
- Incidents panel needs better table styling
- Command line hints need refinement

### 5. IAW/UAW Modals
- Incident Action Window needs V4 styling
- Unit Action Window needs V4 styling
- Dispatch picker needs styling update

### 6. Responsive Design
- Test on tablet (primary dispatch device)
- Ensure touch-friendly button sizes
- Test landscape/portrait modes

---

## 🟢 Medium Priority (Nice to Have)

### 7. Features to Test
- [ ] Create new incident
- [ ] Dispatch units to incident
- [ ] Unit status changes (Enroute, Arrived, etc.)
- [ ] Clear units from incident
- [ ] Close incident with disposition
- [ ] Daily log entry
- [ ] Held calls functionality
- [ ] History search
- [ ] Reports generation
- [ ] Crew assignment (drag & drop)
- [ ] Context menus (right-click)
- [ ] Command line shortcuts
- [ ] Sound alerts

### 8. Production Hardening
- [ ] Remove all console.log statements
- [ ] Add proper error messages for users
- [ ] Test database backup/restore
- [ ] Verify session timeout handling
- [ ] Test multi-user scenarios

### 9. Documentation
- [ ] Update RUN_INSTRUCTIONS.txt
- [ ] Create user manual
- [ ] Document keyboard shortcuts
- [ ] Create troubleshooting guide

---

## 📋 Action Plan (Recommended Order)

### Phase 1: CSS Cleanup (2-3 hours)
1. Backup existing CSS files
2. Update `ford-cad-v4.css` with all needed styles
3. Update `login.html` to use new theme
4. Remove old CSS references from templates
5. Test all pages render correctly

### Phase 2: UI Polish (3-4 hours)
1. Fix calltaker panel layout
2. Fix units panel two-column layout
3. Style IAW modal
4. Style UAW modal
5. Style dispatch picker
6. Test responsive on different screen sizes

### Phase 3: Functionality Testing (2-3 hours)
1. Test complete incident lifecycle
2. Test unit management
3. Test daily log
4. Test history/reports
5. Fix any bugs found

### Phase 4: Production Prep (1-2 hours)
1. Remove debug console.log statements
2. Test error handling
3. Verify database integrity
4. Create backup procedure
5. Final visual review

---

## 🚀 Quick Wins (Do First)

1. **Login page theme** - High visibility, quick fix
2. **Remove CSS conflicts** - Fixes many visual bugs at once
3. **Test core workflow** - Ensure basic dispatching works

---

## 💻 Commands to Run

### Start Development Server
```bash
cd /home/ubuntu/clawd/cad2
python3 -m uvicorn main:app --reload --port 8000
```

### Access the App
```
http://localhost:8000
```

### Test Login
- Any unit ID works (e.g., "17" for Troy Williams)
- Select shift A/B/C/D
- No password required for non-admin

---

## 📁 Key Files to Edit

| Task | File(s) |
|------|---------|
| Main theme | `static/css/ford-cad-v4.css` |
| Login page | `templates/login.html` |
| Main layout | `templates/index.html` |
| Calltaker | `templates/calltaker.html` |
| Units panel | `templates/units.html` |
| Modals | `static/modals.css` |
| IAW | `templates/iaw/*.html` |

---

**Estimated Total Time:** 8-12 hours for full production readiness

**Next Step:** Start with Phase 1 (CSS Cleanup) - want me to begin?

---

# Admin Section Implementation (Completed Feb 2, 2026)

## Overview

Comprehensive admin section for FORD-CAD with system reset, run number management, data purging, and system statistics - modeled after commercial CAD systems like Resgrid.

## Admin Access

Authorized admin users (by unit ID):
- `1578`, `CAR1`, `BATT1`, `BATT2`, `BATT3`, `BATT4`, `17`, `47`

## Features Implemented

### 1. Admin Dashboard (`/admin`)

Tabbed interface with four sections:

#### Dashboard Tab
- Total incidents count
- Open/Closed/Draft incident counts
- Current run number display
- Total units and available units
- MasterLog and DailyLog entry counts
- Last incident created
- Incidents by year breakdown

#### Reset & Maintenance Tab
| Action | Description | Confirmation Required |
|--------|-------------|----------------------|
| Reset Unit Status | Set all units to AVAILABLE, clear active assignments | Yes |
| Clear Closed Incidents | Archive and remove closed incidents only | Yes |
| Clear Audit Logs | Archive and purge MasterLog/DailyLog | Yes |
| Clear ALL Incidents | Archive and remove all incident data | Type "DELETE ALL" |
| Full System Reset | Archive everything, clear all data, reset run numbers | Type "RESET" |

#### Run Numbers Tab
- View current year's next run number
- Set custom run number sequence
- Reset run number to 1
- View run number history by year

#### Admin Logs Tab
- Recent admin actions from MasterLog
- Filtered to show only ADMIN_* events

### 2. Data Archiving

All destructive operations archive data to CSV before deletion:
- Location: `static/archives/`
- Naming: `{type}_{YYYY-MM-DD_HHMMSS}.csv`
- Examples:
  - `incidents_2026-02-02_143521.csv`
  - `masterlog_2026-02-02_143521.csv`
  - `closed_incidents_2026-02-02_150000.csv`

### 3. Export Functionality

- Export all incidents to CSV
- Export MasterLog to CSV
- Export DailyLog to CSV

### 4. Force Clear Ghost Units

For stuck incidents with phantom unit assignments:
- Admin-only "Force Clear" button in close incident popup
- Endpoint: `POST /api/incident/{id}/force_clear_units`
- Marks all unit assignments as cleared
- Resets unit statuses to AVAILABLE

## API Endpoints

### Statistics & Info
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/admin` | Admin dashboard HTML page |
| GET | `/admin/stats` | System statistics JSON |
| GET | `/admin/run_numbers` | Run number counters |

### Export
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/admin/export/incidents` | Export incidents to CSV |
| GET | `/admin/export/logs?log_type=masterlog` | Export MasterLog to CSV |
| GET | `/admin/export/logs?log_type=dailylog` | Export DailyLog to CSV |

### Reset Operations
| Method | Endpoint | Body | Description |
|--------|----------|------|-------------|
| POST | `/admin/reset/run_numbers` | `{confirm: true, force: true}` | Reset run counter to 1 |
| POST | `/admin/reset/units` | `{confirm: true}` | Reset all units to AVAILABLE |
| POST | `/admin/reset/logs` | `{confirm: true, keep_days: 0}` | Clear audit logs |
| POST | `/admin/reset/closed` | `{confirm: true}` | Clear closed incidents |
| POST | `/admin/reset/incidents` | `{confirm: "DELETE ALL"}` | Clear ALL incidents |
| POST | `/admin/reset/full` | `{confirm: "RESET"}` | Full system reset |

### Debugging
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/incident/{id}/assignments` | View unit assignments for incident |
| POST | `/api/incident/{id}/force_clear_units` | Force clear ghost assignments |
| GET | `/api/admin/logs` | Fetch admin log entries |

## Response Formats

### GET /admin/stats
```json
{
  "ok": true,
  "stats": {
    "total_incidents": 1234,
    "open_incidents": 12,
    "closed_incidents": 1222,
    "draft_incidents": 3,
    "current_run_number": "2026-00047",
    "next_seq": 48,
    "current_year": 2026,
    "total_units": 15,
    "available_units": 8,
    "masterlog_entries": 5432,
    "dailylog_entries": 890,
    "last_incident": {
      "incident_number": "2026-00046",
      "created": "2026-02-02 14:32:00"
    },
    "yearly_counts": [
      {"year": "2026", "count": 47},
      {"year": "2025", "count": 1187}
    ]
  }
}
```

### POST /admin/reset/full
```json
{
  "ok": true,
  "message": "Full system reset complete",
  "archived_files": [
    "static/archives/full_reset_incidents_2026-02-02_143521.csv",
    "static/archives/full_reset_masterlog_2026-02-02_143521.csv"
  ],
  "incidents_cleared": 1234,
  "masterlog_cleared": 5432,
  "dailylog_cleared": 890,
  "run_number_reset_to": 1
}
```

## Database Tables Affected

| Table | Clear Closed | Clear All | Full Reset |
|-------|--------------|-----------|------------|
| Incidents | Closed only | All | All |
| UnitAssignments | Related | All | All |
| Narrative | Related | All | All |
| IncidentHistory | Related | All | All |
| HeldSeen | Related | All | All |
| MasterLog | No | No | All |
| DailyLog | No | No | All |
| IncidentCounter | No | No | Reset to 1 |
| Units | No | No | Status reset |

## Safety Measures

1. **Authentication**: All admin endpoints check `_is_admin(user)`
2. **Confirmation**: Dangerous operations require explicit confirmation
3. **Double confirmation**: Full reset and clear-all require typing confirmation text
4. **Audit trail**: All admin actions logged to MasterLog before execution
5. **Data preservation**: Archives created before any deletion
6. **Preview counts**: Statistics shown before executing operations

## Files Modified/Created

### New Files
- `templates/admin.html` - Admin dashboard template
- `static/archives/.gitkeep` - Archives directory

### Modified Files
- `main.py` - Admin endpoints (~760 lines added)
- `templates/index.html` - CAD_USER/CAD_IS_ADMIN globals, admin button onclick
- `templates/_toolbar.html` - Admin button for toolbar
- `static/js/modules/contextmenu.js` - Force clear button for admins
- `static/modals.css` - Force clear button styling

## Bug Fixes Included

1. **IncidentHistory column names**: Fixed `event` → `event_type`, `detail` → `details`
2. **Missing column handling**: `clear_all_and_close` now handles missing `final_disposition_note`
3. **Admin button**: Added working onclick handlers to header and toolbar buttons

## Usage

### Access Admin Dashboard
1. Log in as an admin user (CAR1, BATT1, etc.)
2. Click "Admin" button in header OR toolbar
3. Dashboard opens in new tab

### Close Stuck Incident
1. Right-click incident → Close Incident
2. If "X unit(s) still assigned" appears:
   - Select disposition and click "Clear Units & Close", OR
   - Click red "Force Clear" button (admin only) to clear ghost assignments

### Full System Reset
1. Go to Admin → Reset & Maintenance tab
2. Click "Full Reset" button
3. Type "RESET" in confirmation dialog
4. Click Confirm
5. All data archived to `static/archives/` and cleared

## Testing Checklist

- [ ] Navigate to `/admin?user=CAR1` - should show dashboard
- [ ] Navigate to `/admin?user=DISPATCH` - should show 403
- [ ] Dashboard tab shows correct statistics
- [ ] Run Numbers tab shows current sequence
- [ ] Reset Unit Status works
- [ ] Clear Closed Incidents archives and removes only closed
- [ ] Clear All Incidents requires "DELETE ALL" confirmation
- [ ] Full System Reset requires "RESET" confirmation
- [ ] Export buttons generate CSV files
- [ ] Force Clear button appears for admin users on stuck incidents
- [ ] All actions logged to MasterLog
