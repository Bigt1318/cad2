# FORD-CAD Fixes Round 2
## User-Identified Issues - 2026-02-04

---

## 1. FONT SYSTEM OVERHAUL

### Current Problem
- Extra large is too big (doesn't fit screen)
- Small could be 2 sizes smaller
- Only basic fonts available

### Required Changes

**A. Font Size Scale (in settings.js and ford-cad-v4.css):**
```css
:root {
  --font-size-xs: 11px;
  --font-size-sm: 13px;
  --font-size-md: 15px;   /* default */
  --font-size-lg: 17px;
  --font-size-xl: 19px;
}
```

**B. Font Family Options - Add to settings:**
```javascript
const FONT_FAMILIES = {
  'system': '-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif',
  'arial': 'Arial, Helvetica, sans-serif',
  'georgia': 'Georgia, "Times New Roman", serif',
  'narrow': '"Arial Narrow", "Helvetica Condensed", sans-serif',
  'stencil': '"Stencil Std", "Army", fantasy',
  'mono': '"Consolas", "Monaco", monospace',
  'handwritten': '"Comic Sans MS", "Marker Felt", cursive',
  'emergency': '"Interstate", "Highway Gothic", "DIN", sans-serif',
  'bold': '"Arial Black", "Helvetica Bold", sans-serif',
};
```

**C. Add font family picker to settings modal**

---

## 2. CUSTOMIZABLE THEMES

### Required Features
- Save multiple theme presets (user can name them)
- Color picker for: background, text, accent, panels, borders
- Store in UserSettings as JSON array of presets

### Panel Positioning (Advanced - Phase 2)
- Allow drag-to-reorder panels
- Save panel layout preference
- Options: calltaker, units, open calls, active calls, command line

---

## 3. SETTINGS AUTO-APPLY

### Current Problem
Settings require clicking Save

### Fix (in settings.js)
```javascript
// Change all setting inputs to auto-save on change
settingInput.addEventListener('change', async (e) => {
    await CAD_SETTINGS.save();
    CAD_SETTINGS.apply(); // Apply immediately
});
```

Remove or hide the Save button for visual settings.

---

## 4. CLOCK FIX - CRITICAL

### Current Problems
- Shows "0000" (not updating)
- Dim green color barely visible

### Fix Location
`static/js/modules/clock.js`

**Check:**
1. Is `setInterval` actually running?
2. Is the element selector correct?
3. Add visible default color

```javascript
// In clock.js init:
function updateClock() {
    const now = new Date();
    const timeStr = now.toLocaleTimeString('en-US', { 
        hour12: false, 
        hour: '2-digit', 
        minute: '2-digit', 
        second: '2-digit' 
    });
    const el = document.getElementById('clock');
    if (el) {
        el.textContent = timeStr;
    }
}

// Ensure interval is set
setInterval(updateClock, 1000);
updateClock(); // Initial call
```

**CSS Fix (ford-cad-v4.css):**
```css
.header-clock {
    color: #22c55e; /* Brighter green */
    font-weight: 700;
    font-size: var(--text-xl);
    font-family: "Consolas", monospace;
    text-shadow: 0 0 10px rgba(34, 197, 94, 0.5);
}
```

Add clock color to user settings.

---

## 5. ANALYTICS PAGE

### Problems
- No controls
- Page doesn't scroll

### Fix (in admin.html or analytics section)
```css
.analytics-container {
    overflow-y: auto;
    max-height: calc(100vh - 200px);
}
```

Add date range picker and filter controls.

---

## 6. CALENDAR FIXES

### Problems
- Missing D shift (only shows A, B, C)
- Too small
- No event scheduling
- No notifications

### Fix A: Add D Shift
Check `reports.py` - the 2-2-3 rotation should include D shift for night shifts.

Update calendar.js to show both day AND night shifts:
```javascript
html += `<div class="calendar-day">
    <span class="day-num">${day}</span>
    <span class="shift-day">${shift.day_shift}</span>
    <span class="shift-night">${shift.night_shift}</span>
</div>`;
```

### Fix B: Calendar Size
```css
.calendar-modal { 
    min-width: 700px; 
    min-height: 500px;
}
.calendar-day {
    min-height: 60px;
    padding: 4px;
}
```

### Fix C: Google Calendar Integration (Future)
- Account: SERTCAD2022@gmail.com
- Consider using Google Calendar API for event sync
- Would need OAuth setup

---

## 7. REPORTING TOOL - BROKEN

### Problems
- "Doesn't work" / "is a mess"

### Investigation Needed
1. Check what errors appear in browser console
2. Check server logs when reports modal opens
3. Identify specific failures

### Send Report Button Fix
Instead of sending immediately:
1. Open preview modal showing report content
2. Show editable email recipient field
3. "Send" button in preview modal
4. Confirmation after send

---

## 8. APPARATUS ORDERING

### Problem
Order in admin settings differs from display

### Fix
1. Check if `display_order` column exists in Units table
2. Ensure query uses `ORDER BY display_order ASC`
3. Add user preference override in settings

```sql
-- In units query:
SELECT * FROM Units 
WHERE unit_type = 'APPARATUS'
ORDER BY COALESCE(user_order, display_order, 999), unit_id
```

Add drag-to-reorder in settings with per-user save.

---

## 9. INCIDENT LIFECYCLE BUGS

### Bug A: Unit Disappeared Without Dispatch
**Symptom:** Engine gone from apparatus list without being dispatched
**Likely Cause:** Status changed incorrectly or unit_type changed

**Debug:**
```sql
SELECT * FROM Units WHERE unit_id = 'Engine1';
SELECT * FROM UnitAssignments WHERE unit_id = 'Engine1' AND cleared IS NULL;
```

### Bug B: Active Incidents Not Auto-Refreshing
**Fix in panels.js:**
```javascript
// Ensure auto-refresh is running
setInterval(() => {
    if (CAD_SETTINGS.get('autoRefresh')) {
        refreshActiveIncidents();
        refreshUnitsPanel();
    }
}, CAD_SETTINGS.get('autoRefreshInterval') * 1000 || 5000);
```

Check HTMX triggers are firing.

### Bug C: Command Line Codes Changed

**Expected commands that aren't working:**
- `NEW` → Should create new incident
- `{unit} SI` → Self-initiate (NOT "show incidents")

**Fix in commandline.js:**
```javascript
// Add/restore these handlers:
case 'NEW':
    openCalltaker(); // or createNewIncident()
    break;

case 'SI':
    // Self-initiate: unit starts incident at their location
    selfInitiateIncident(parts[0]); // unit_id from command
    break;
```

### Bug D: Self-Initiate While Assigned
**Problem:** Unit on Incident A tries to SI → creates incident but doesn't show until cleared

**Required Logic:**
1. If unit is assigned to incident, first clear them (auto-disposition)
2. Create new SI incident
3. Auto-dispatch unit to new incident
4. Show new incident immediately

```javascript
async function selfInitiateIncident(unitId) {
    // Check if unit is currently assigned
    const currentAssignment = await fetch(`/api/unit/${unitId}/current_assignment`).then(r => r.json());
    
    if (currentAssignment.incident_id) {
        // Auto-clear from current incident
        await fetch(`/api/incident/${currentAssignment.incident_id}/unit/${unitId}/clear`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({disposition: 'SI'}) // Special SI disposition
        });
    }
    
    // Create new incident
    const newInc = await fetch('/incident/new', {method: 'POST'}).then(r => r.json());
    
    // Save with SI type
    await fetch(`/incident/save/${newInc.incident_id}`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            type: 'SELF-INITIATED',
            location: `Unit ${unitId} location`,
            narrative: `Self-initiated by ${unitId}`
        })
    });
    
    // Auto-dispatch unit
    await fetch(`/incident/${newInc.incident_id}/dispatch_units`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({units: [unitId]})
    });
    
    // Refresh panels
    refreshActiveIncidents();
    refreshUnitsPanel();
}
```

---

## PRIORITY ORDER

1. **Critical (breaks functionality):**
   - Clock showing 0000
   - Active incidents not refreshing
   - Command line SI command wrong
   - Unit disappearing bug

2. **High (user experience):**
   - Settings auto-apply
   - Calendar missing D shift
   - Reporting tool broken

3. **Medium (polish):**
   - Font sizes/families
   - Analytics scroll
   - Apparatus ordering

4. **Lower (feature additions):**
   - Theme presets
   - Panel repositioning
   - Google Calendar integration

---

## TESTING CHECKLIST

After fixes:
- [ ] Clock shows current time and updates
- [ ] Type `NEW` in command line → opens calltaker
- [ ] Type `34 SI` → creates incident and dispatches unit 34
- [ ] SI while unit is assigned → auto-clears and dispatches to new
- [ ] Active incidents refresh automatically
- [ ] Calendar shows all 4 shifts (A, B, C, D)
- [ ] Settings changes apply immediately
- [ ] Font size changes visible
- [ ] Analytics page scrolls
