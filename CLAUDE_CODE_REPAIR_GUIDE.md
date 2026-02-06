# FORD-CAD Repair Guide for Claude Code
## Complete System Analysis & Fix Instructions

**Generated:** 2026-02-04  
**System:** FORD-CAD v4 (Industrial Fire Brigade Dispatch)  
**Repo:** https://github.com/Bigt1318/cad2.git

---

## 🎯 PRIORITY 1: CSS Consolidation (Critical)

### Problem
Multiple CSS files with conflicting/overlapping styles cause visual inconsistencies:
- `static/css/ford-cad-v4.css` (44KB) - NEW primary theme
- `static/css/design-system.css` (34KB) - OLD design system
- `static/css/themes.css` (8KB) - OLD theme variables
- `static/style.css` (50KB) - LEGACY styles
- `static/modals.css` (47KB) - Modal-specific styles

### Fix
1. **Keep:** `static/css/ford-cad-v4.css` as primary theme
2. **Keep:** `static/modals.css` for modal styling
3. **Archive/Remove:** `static/css/design-system.css`, `static/css/themes.css`, `static/style.css`
4. **Update templates** to only reference:
   ```html
   <link rel="stylesheet" href="/static/css/ford-cad-v4.css">
   <link rel="stylesheet" href="/static/modals.css">
   ```
5. **Migrate any missing styles** from old CSS files to `ford-cad-v4.css`

### Files to Edit
- `templates/index.html` - Update stylesheet links
- `templates/login.html` - Update stylesheet links  
- `templates/admin.html` - Update stylesheet links
- Any other templates with `<link rel="stylesheet">`

---

## 🎯 PRIORITY 2: Remove Debug Code

### Problem
51 `console.log` statements in production JavaScript create noise and potential info leaks.

### Fix
Run this command to find all debug logs:
```bash
grep -rn "console.log" static/js/
```

Then either:
- **Option A:** Remove all `console.log` statements
- **Option B:** Wrap in debug flag:
```javascript
const DEBUG = false;
if (DEBUG) console.log("...");
```

### Files with most debug logs
- `static/js/modules/commandline.js` - Heavy debugging
- `static/js/modules/contextmenu.js`
- `static/js/modules/iaw.js`
- `static/js/modules/uaw2.js`

---

## 🎯 PRIORITY 3: Login Page Theme

### Problem
Login page (`templates/login.html`) has inline styles that may conflict with the V4 theme.

### Fix
1. Move inline `<style>` block to `ford-cad-v4.css`
2. Use consistent CSS variables from V4 theme
3. Ensure Ford blue gradient header matches main app

---

## 🟡 MEDIUM PRIORITY: Modal Styling Consistency

### Problem
Some modals (IAW, UAW, Dispatch Picker) may not fully match the dark glass theme.

### Fix
Ensure all modals use these V4 patterns:
```css
.modal-overlay {
  background: rgba(15, 23, 34, 0.85);
  backdrop-filter: blur(8px);
}
.modal-content {
  background: rgba(15, 23, 42, 0.98);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
}
```

### Files
- `static/modals.css`
- `templates/modals/*.html`
- `templates/iaw/*.html`

---

## 🟡 MEDIUM PRIORITY: Panel Layout Fixes

### Calltaker Panel (Left Side)
- Needs more compact form layout
- Field spacing too large on smaller screens
- File: `templates/calltaker.html`

### Units Panel (Right Side)  
- Two-column layout (Command/Personnel | Apparatus)
- Ensure proper scrolling within each column
- File: `templates/units.html`

### Active Incidents Panel (Center)
- Table styling needs consistency
- Row hover states
- Status badge colors
- File: `templates/active_incidents.html`

---

## 🟢 LOW PRIORITY: Feature Polish

### Command Line (Bottom)
- Hint text refinement
- Auto-complete improvements
- File: `static/js/modules/commandline.js`

### Context Menus
- Ensure all right-click menus have consistent styling
- File: `static/js/modules/contextmenu.js`

### Toast Notifications
- Position and animation consistency
- File: `static/js/modules/toast.js`

---

## 📋 TESTING CHECKLIST

After fixes, test these workflows:

### Login Flow
- [ ] Login page loads with correct styling
- [ ] Can login as dispatcher (any unit ID)
- [ ] Can login as admin (1578, CAR1, BATT1-4, 17, 47)
- [ ] Session persists across page refresh

### Incident Workflow
- [ ] Create new incident via Calltaker panel
- [ ] Incident appears in Active Incidents
- [ ] Open IAW (Incident Action Window) by clicking incident
- [ ] Dispatch units via Dispatch Picker
- [ ] Unit status changes (Dispatched → Enroute → Arrived → Cleared)
- [ ] Add remarks to incident
- [ ] Close incident with disposition

### Unit Management
- [ ] Units panel shows two columns
- [ ] Can change unit status via right-click menu
- [ ] Drag/drop personnel to apparatus works
- [ ] Crew chips display under apparatus
- [ ] Coverage toggle works (COV/UNCOV)

### Daily Log
- [ ] Can create daily log entry
- [ ] "Issue Found" checkbox works
- [ ] Entry appears in Daily Log panel

### Admin Section
- [ ] Admin button visible for admin users
- [ ] Dashboard shows correct statistics
- [ ] Reset functions work (with proper confirmation)
- [ ] Export to CSV works

---

## 🔧 RECOMMENDED APPROACH

### Step 1: CSS Cleanup (Do First)
```bash
# Backup old CSS
mkdir -p static/css/archive
mv static/css/design-system.css static/css/archive/
mv static/css/themes.css static/css/archive/
mv static/style.css static/css/archive/

# Update templates to remove old CSS references
```

### Step 2: Test Everything
Run the server and test all workflows listed above.

### Step 3: Fix Bugs Found
Document any visual glitches or broken features, fix one at a time.

### Step 4: Remove Debug Code
```bash
# Find all console.log
grep -rn "console.log" static/js/ > debug_logs.txt
# Review and remove/wrap each one
```

### Step 5: Final Polish
- Responsive testing (tablet-sized screen is primary)
- Touch-friendly button sizes (min 44px)
- Keyboard navigation testing

---

## 📁 KEY FILE REFERENCE

| Purpose | File |
|---------|------|
| Backend (all routes) | `main.py` (13,098 lines) |
| Reports/Email | `reports.py` |
| Primary CSS | `static/css/ford-cad-v4.css` |
| Modal CSS | `static/modals.css` |
| Main layout | `templates/index.html` |
| Login page | `templates/login.html` |
| Admin page | `templates/admin.html` |
| Calltaker panel | `templates/calltaker.html` |
| Units panel | `templates/units.html` |
| IAW modal | `templates/iaw/*.html` |
| JS Bootloader | `static/js/bootloader.js` |
| Command Line JS | `static/js/modules/commandline.js` |
| IAW JS | `static/js/modules/iaw.js` |
| UAW JS | `static/js/modules/uaw2.js` |
| Context Menus | `static/js/modules/contextmenu.js` |

---

## 💡 TIPS FOR CLAUDE CODE

1. **Start server before editing:**
   ```bash
   cd C:\cad2
   .\.venv\Scripts\Activate.ps1
   python -m uvicorn main:app --reload --port 8000
   ```

2. **Test in browser at:** `http://localhost:8000`

3. **Login as admin:** Use unit ID `17` or `CAR1` to see admin features

4. **Check console:** Browser DevTools console will show JS errors

5. **CSS changes:** Refresh browser to see CSS changes (may need hard refresh Ctrl+Shift+R)

6. **DB reset:** If data gets corrupted, delete `cad.db` and restart server - it will recreate

---

## 🎨 DESIGN REFERENCE

### Colors (Ford V4 Theme)
```css
--ford-blue: #003478;
--ford-blue-dark: #00264d;
--bg-app: #f1f5f9;
--bg-surface: #ffffff;
--bg-elevated: #f8fafc;
--text-primary: #0f172a;
--text-secondary: #475569;
--text-muted: #64748b;
--border-default: #cbd5e1;
```

### Status Colors
```css
--status-dispatched: #f97316;  /* Orange */
--status-enroute: #eab308;     /* Yellow */
--status-arrived: #16a34a;     /* Green */
--status-transporting: #a855f7; /* Purple */
--status-at-medical: #06b6d4;  /* Cyan */
--status-oos: #64748b;         /* Gray */
```

---

**Good luck! The system is solid - just needs UI polish for production.**
