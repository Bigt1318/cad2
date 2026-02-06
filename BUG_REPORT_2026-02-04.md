# FORD-CAD Bug Report
## Comprehensive Testing Results - 2026-02-04

---

## 🔴 CRITICAL BUGS (System Breaking)

### 1. UAW (Unit Action Window) - NameError
**Endpoint:** `/unit/{unit_id}/uaw` and `/unit/{unit_id}/uaw_full`
**Error:** `NameError: name '_load_unit_for_uaw' is not defined`
**Location:** main.py line 2839, 2858, 2876
**Impact:** Cannot open Unit Action Window - blocks unit management workflow
**Fix:** Define the `_load_unit_for_uaw` function or import it if it exists elsewhere

### 2. Response Plans Page - Missing Template
**Endpoint:** `/admin/response_plans`
**Error:** Template `admin/response_plans.html` not found
**Impact:** Cannot access Response Plans admin page
**Fix:** Create `templates/admin/response_plans.html` or change the template path

---

## 🟡 MEDIUM BUGS (Functional Issues)

### 3. Incident `/new` Endpoint Ignores Data
**Endpoint:** `POST /incident/new`
**Issue:** Creates empty draft incident, ignores all passed data (location, type, narrative, etc.)
**Expected:** Should save the data passed in the request body
**Workaround:** Must call `/incident/save/{id}` separately after creating
**Fix:** Update the `/new` endpoint to accept and save initial data

### 4. Pole Alpha/Number Field Merge Bug
**Issue:** When saving incident with `pole_alpha: "C"` and `pole_number: "15"`, they get merged into `pole_alpha: "C-15"` and `pole_number` becomes empty
**Expected:** Fields should remain separate
**Location:** main.py lines 2167-2174
**Fix:** Review pole concatenation logic

### 5. Unit Status Endpoint Parameter Issue
**Endpoint:** `POST /unit_status`
**Error:** Returns "Missing parameters" even with valid JSON body
**Fix:** Check what parameters the endpoint actually expects

---

## 🟢 MINOR ISSUES (Inconveniences)

### 6. API Field Name Inconsistencies
- Incident save uses `type` not `incident_type`
- Dispatch uses `units` not `unit_ids`
- Daily log uses `details` not `narrative`
- Unit clear uses short codes (`R`, `C`, `NA`) not full words

**Recommendation:** Add field aliases or document expected field names

### 7. Session Cookie Handling
**Issue:** 405 Method Not Allowed after login redirect (POST to `/`)
**Impact:** Minor - login still works, just throws an ignorable error
**Fix:** Ensure redirect target accepts GET

---

## ✅ WORKING FEATURES (Tested OK)

| Feature | Status | Notes |
|---------|--------|-------|
| Login (admin/regular) | ✅ Works | Unit-based auth working |
| Incident Creation | ✅ Works | Via `/new` + `/save` |
| Incident Save | ✅ Works | Field name = `type` |
| Dispatch Units | ✅ Works | Field name = `units` |
| Unit Status Changes | ✅ Works | ENROUTE, ARRIVED, etc. |
| Unit Clear | ✅ Works | Use short codes (R, C, NA, etc.) |
| Incident Close | ✅ Works | Returns NFIRS warning if incomplete |
| Incident Reopen | ✅ Works | |
| Daily Log | ✅ Works | Field = `details`, not `narrative` |
| Crew Assignment | ✅ Works | |
| Admin Stats | ✅ Works | |
| Admin Page | ✅ Works | |
| Dispatch Picker | ✅ Works | |
| IAW (Incident Action Window) | ✅ Works | |
| Session Status | ✅ Works | |
| Settings API | ✅ Works | |
| Contacts API | ✅ Works | (empty list) |
| History | ✅ Works | |

---

## 📊 SYSTEM STATS

- **Total API Endpoints:** 121
- **Total Units:** 42
- **Available Units:** 42
- **Templates:** 25+ files
- **JS Modules:** 26 files
- **Console.log statements:** 0 (cleaned up!)
- **CSS Files:** Consolidated (archive created)

---

## 🔧 RECOMMENDED FIXES (Priority Order)

### Priority 1: Fix UAW (Critical)
```python
# Add this function to main.py before the UAW routes:
def _load_unit_for_uaw(unit_id: str):
    """Load unit data for UAW modal."""
    conn = get_conn()
    c = conn.cursor()
    unit = c.execute(
        "SELECT * FROM Units WHERE unit_id = ?", (unit_id,)
    ).fetchone()
    if not unit:
        return None, None
    
    # Find active incident if any
    active = c.execute("""
        SELECT incident_id FROM UnitAssignments 
        WHERE unit_id = ? AND cleared IS NULL
        ORDER BY assigned DESC LIMIT 1
    """, (unit_id,)).fetchone()
    
    return dict(unit), active["incident_id"] if active else None
```

### Priority 2: Create Response Plans Template
Create `templates/admin/response_plans.html` or update the route to use existing template location.

### Priority 3: Fix Incident New Endpoint
Update POST `/incident/new` to accept and save initial data, not just create empty draft.

---

## 📁 FILES NEEDING CHANGES

| File | Issue | Change Needed |
|------|-------|---------------|
| main.py | UAW broken | Add `_load_unit_for_uaw` function |
| main.py | Pole field merge | Fix concatenation logic |
| main.py | Incident new | Accept initial data |
| templates/admin/ | Missing dir | Create directory |
| templates/admin/response_plans.html | Missing | Create template |

---

## 🧪 TEST COMMANDS USED

```bash
# Login
curl -X POST http://localhost:8888/login -d "dispatcher_unit=17&password=test123"

# Create incident
curl -X POST http://localhost:8888/incident/new -H "Content-Type: application/json" -d '{}'

# Save incident (use "type" not "incident_type")
curl -X POST http://localhost:8888/incident/save/{id} -d '{"type": "THERMAL EVENT", "location": "..."}'

# Dispatch (use "units" not "unit_ids")  
curl -X POST http://localhost:8888/incident/{id}/dispatch_units -d '{"units": ["Engine1"]}'

# Clear unit (use short codes: R, C, NA, NF, CT, O, FA, FF, MF, MT, PR)
curl -X POST http://localhost:8888/incident/{id}/unit/{unit}/clear -d '{"disposition": "R"}'

# Daily log (use "details" not "narrative")
curl -X POST http://localhost:8888/api/dailylog/add -d '{"subtype": "BUILDING_CHECK", "details": "..."}'
```

---

**Report Generated:** 2026-02-04 14:52 UTC  
**Tester:** Rosie (AI Assistant)

---

## 🔴 ADDITIONAL BUG: Settings API Wipes Data

### Problem
`POST /api/settings` expects nested structure `{"settings": {...}}`

If client sends flat structure like `{"theme": "dark"}`, the API:
1. Returns `{"ok": true}` (success!)
2. But saves empty `{}` to database
3. **All user settings are lost**

**Location:** main.py line 3351: `settings_json = json.dumps(payload.get("settings", {}))`

### Fix
Add validation or accept both formats:
```python
# Accept both nested and flat structures
settings = payload.get("settings") or payload
if not settings or not isinstance(settings, dict):
    return {"ok": False, "error": "No settings provided"}
settings_json = json.dumps(settings)
```

---

## Summary of All Bugs Found

| Bug | Severity | Status |
|-----|----------|--------|
| UAW undefined function | 🔴 Critical | Blocks feature |
| Response Plans missing template | 🔴 Critical | Blocks feature |
| Settings API wipes data | 🔴 Critical | Data loss |
| Incident /new ignores data | 🟡 Medium | Workaround exists |
| Pole field merge | 🟡 Medium | Minor data issue |
| Admin login requires password | 🟢 Low | By design |
