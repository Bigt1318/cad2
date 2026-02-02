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
