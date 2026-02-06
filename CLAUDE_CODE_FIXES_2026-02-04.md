# FORD-CAD Bug Fixes - Claude Code Prompt
## Generated: 2026-02-04

Copy this prompt into Claude Code to fix the remaining issues.

---

## PROMPT FOR CLAUDE CODE:

I need you to fix several bugs in FORD-CAD. Here are the issues with exact locations and fix instructions:

### 1. UAW (Unit Action Window) - CRITICAL
**File:** `main.py`
**Error:** `NameError: name '_load_unit_for_uaw' is not defined` (lines 2839, 2858, 2876)

**Fix:** Add this function before the UAW routes (around line 2835):

```python
def _load_unit_for_uaw(unit_id: str):
    """Load unit data for UAW modal."""
    conn = get_conn()
    c = conn.cursor()
    unit = c.execute(
        "SELECT * FROM Units WHERE unit_id = ?", (unit_id,)
    ).fetchone()
    if not unit:
        conn.close()
        return None, None
    
    # Find active incident if any
    active = c.execute("""
        SELECT incident_id FROM UnitAssignments 
        WHERE unit_id = ? AND cleared IS NULL
        ORDER BY assigned DESC LIMIT 1
    """, (unit_id,)).fetchone()
    
    conn.close()
    return dict(unit), active["incident_id"] if active else None
```

### 2. Response Plans - Missing Template
**File:** `main.py` line ~10623
**Error:** Template `admin/response_plans.html` not found

**Fix Option A:** Create the missing template directory and file:
```bash
mkdir -p templates/admin
```
Then create `templates/admin/response_plans.html` with a basic admin page layout.

**Fix Option B:** Change the template path in main.py to use existing location:
```python
# Change from:
return templates.TemplateResponse("admin/response_plans.html", {...})
# To:
return templates.TemplateResponse("response_plans.html", {...})
```
And create `templates/response_plans.html`.

### 3. Calendar JS Module - MISSING
**File:** Need to create `static/js/modules/calendar.js`
**Problem:** Calendar modal references `CALENDAR.prevMonth()` and `CALENDAR.nextMonth()` but the module doesn't exist.

**Fix:** Create `static/js/modules/calendar.js`:

```javascript
// Calendar Module with 2-2-3 Shift Schedule
window.CALENDAR = {
    currentDate: new Date(),
    
    async init() {
        await this.render();
    },
    
    async render() {
        const container = document.getElementById('calendar-days');
        if (!container) return;
        
        const year = this.currentDate.getFullYear();
        const month = this.currentDate.getMonth();
        
        // Fetch shift schedule
        let schedule = {};
        try {
            const res = await fetch(`/api/shift/schedule?days=42`);
            const data = await res.json();
            if (data.schedule) {
                data.schedule.forEach(s => {
                    schedule[s.date] = s;
                });
            }
        } catch (e) {
            console.warn('Failed to load shift schedule');
        }
        
        // Build calendar grid
        const firstDay = new Date(year, month, 1).getDay();
        const daysInMonth = new Date(year, month + 1, 0).getDate();
        
        let html = '';
        // Empty cells for days before first
        for (let i = 0; i < firstDay; i++) {
            html += '<div class="calendar-day empty"></div>';
        }
        
        // Days of month
        for (let day = 1; day <= daysInMonth; day++) {
            const dateStr = `${year}-${String(month+1).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
            const shift = schedule[dateStr];
            const shiftClass = shift ? `shift-${shift.day_shift.toLowerCase()}` : '';
            const isToday = this.isToday(year, month, day) ? 'today' : '';
            
            html += `<div class="calendar-day ${shiftClass} ${isToday}" data-date="${dateStr}">
                <span class="day-num">${day}</span>
                ${shift ? `<span class="shift-label">${shift.day_shift}</span>` : ''}
            </div>`;
        }
        
        container.innerHTML = html;
        
        // Update title
        const title = document.querySelector('.calendar-month-title');
        if (title) {
            title.textContent = this.currentDate.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
        }
    },
    
    isToday(year, month, day) {
        const today = new Date();
        return today.getFullYear() === year && 
               today.getMonth() === month && 
               today.getDate() === day;
    },
    
    prevMonth() {
        this.currentDate.setMonth(this.currentDate.getMonth() - 1);
        this.render();
    },
    
    nextMonth() {
        this.currentDate.setMonth(this.currentDate.getMonth() + 1);
        this.render();
    }
};

// Auto-init when modal opens
document.addEventListener('DOMContentLoaded', () => {
    // Watch for calendar modal
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((m) => {
            m.addedNodes.forEach((node) => {
                if (node.querySelector && node.querySelector('.calendar-modal')) {
                    CALENDAR.init();
                }
            });
        });
    });
    observer.observe(document.body, { childList: true, subtree: true });
});
```

Then add to `static/js/modules/modules.json`:
```json
"/static/js/modules/calendar.js?v=20260204a"
```

### 4. Add OOS Status to Valid Statuses
**File:** `main.py` 
**Location:** Search for `VALID_UNIT_STATUSES` (appears twice, around lines 4720 and 6020)

**Fix:** Add "OOS" and "UNAVAILABLE" to both VALID_UNIT_STATUSES sets:

```python
VALID_UNIT_STATUSES = {
    "DISPATCHED",
    "ENROUTE", 
    "ARRIVED",
    "ON_SCENE",
    "TRANSPORTING",
    "AT_MEDICAL",
    "CLEARED",
    "AVAILABLE",
    "OOS",           # Add this
    "UNAVAILABLE",   # Add this
}
```

### 5. Calendar Modal CSS (in ford-cad-v4.css)
Add these styles for shift colors:

```css
/* Calendar Shift Colors */
.calendar-day.shift-a { background: rgba(59, 130, 246, 0.2); border-left: 3px solid #3b82f6; }
.calendar-day.shift-b { background: rgba(234, 179, 8, 0.2); border-left: 3px solid #eab308; }
.calendar-day.shift-c { background: rgba(34, 197, 94, 0.2); border-left: 3px solid #22c55e; }
.calendar-day.shift-d { background: rgba(168, 85, 247, 0.2); border-left: 3px solid #a855f7; }
.calendar-day.today { font-weight: 700; box-shadow: inset 0 0 0 2px var(--ford-blue); }
.calendar-day .shift-label { 
    font-size: 10px; 
    font-weight: 600; 
    position: absolute;
    bottom: 2px;
    right: 4px;
    opacity: 0.8;
}
.calendar-day { position: relative; }
.legend-item .dot {
    display: inline-block;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    margin-right: 4px;
}
.dot.shift-a { background: #3b82f6; }
.dot.shift-b { background: #eab308; }
.dot.shift-c { background: #22c55e; }
.dot.shift-d { background: #a855f7; }
```

---

## VERIFICATION AFTER FIXES

Test these endpoints:

1. **UAW:** `GET /unit/Engine1/uaw` - Should return HTML, not error
2. **Response Plans:** `GET /admin/response_plans` - Should show page
3. **Calendar:** Open calendar modal and verify shift colors display
4. **Unit Status:** `POST /api/unit_status/Engine1/OOS` - Should return `{"ok":true}`

---

## WORKING FEATURES (Don't Break These)

- ✅ Settings API (POST with nested structure works)
- ✅ Analytics API 
- ✅ Shift Schedule API (`/api/shift/schedule`)
- ✅ Daily Log
- ✅ Incident lifecycle (create, dispatch, status, clear, close)
- ✅ Admin stats
- ✅ Export to CSV
- ✅ Dispatch picker
- ✅ NFIRS modal
- ✅ Roster modal (HTML loads)
- ✅ Reports modal (HTML loads)
