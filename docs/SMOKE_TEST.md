# FORD-CAD Smoke Test Checklist

Run through this checklist after any deployment or significant code change.

## Prerequisites
- Server running on `http://localhost:8000`
- At least one active incident in database
- At least one unit in `AVAILABLE` status

---

## 1. Login & Session
- [ ] Navigate to `/login` — page loads with FORD-CAD branding (no "BOSK")
- [ ] Login as dispatcher (DISP1, shift A) — redirects to main console
- [ ] Header shows correct user/unit, shift letter, connection dot is green
- [ ] Logout via drawer — redirected to login page

## 2. Create Incident
- [ ] Open calltaker form (Ctrl+N or toolbar button)
- [ ] Fill required fields: location, type, priority
- [ ] Submit — incident appears in Active panel
- [ ] Incident number auto-assigned

## 3. Dispatch
- [ ] Click incident in Active panel — IAW opens
- [ ] Dispatch a unit via IAW dispatch picker
- [ ] Unit status changes to DISPATCHED in Units panel
- [ ] Unit appears in IAW unit cards

## 4. Unit Status Changes
- [ ] Set unit ENROUTE — status updates in both IAW and Units panel
- [ ] Set unit ARRIVED — status updates
- [ ] Set unit OPERATING (if applicable)
- [ ] Verify timestamps recorded in IAW timeline

## 5. Clear & Close
- [ ] Clear unit with disposition — unit returns to AVAILABLE
- [ ] Close incident — moves from Active to history
- [ ] Verify incident appears in History modal

## 6. Messaging
- [ ] Open messaging drawer (toolbar button)
- [ ] Send a DM to another unit
- [ ] Message appears in thread
- [ ] Edit message (right-click > Edit) — edited label appears
- [ ] Delete message (hover trash icon or right-click > Delete) — message grayed out
- [ ] Open settings gear — settings panel loads
- [ ] Toggle "Message Sounds" off — verify no beep on next message
- [ ] Close settings — preferences persist after page refresh

## 7. Reports
- [ ] Open reporting modal (Ctrl+R or toolbar)
- [ ] Generate a Blotter report (HTML format)
- [ ] Report renders with data
- [ ] Verify report header shows "FORD-CAD" (no BOSK)

## 8. Search
- [ ] Open search modal (Ctrl+F or toolbar)
- [ ] Search by location — results appear
- [ ] Search by unit ID — results appear
- [ ] Click result — IAW opens for that incident

## 9. Admin
- [ ] Login as admin unit (1578)
- [ ] Access admin panel — loads without errors
- [ ] Verify branding shows FORD-CAD throughout

## 10. No Console Errors
- [ ] Open browser DevTools Console
- [ ] Navigate through main flows above
- [ ] No JavaScript errors (warnings OK)
- [ ] No 404s for CSS/JS/API resources

---

## Automated Tests
```bash
# Quick API tests (~15s)
python run_tests.py --quick

# Full suite with Playwright UI tests (~40s)
python run_tests.py

# Branding ban check
python scripts/check_branding.py
```

All 100+ tests should pass. Branding check should return 0 violations.
