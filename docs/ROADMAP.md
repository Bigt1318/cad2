# FORD-CAD Development Roadmap

## Current State Assessment

### What You've Built (Impressive)
- **Solid architecture**: FastAPI + HTMX + SQLite is a great choice for offline-first
- **Comprehensive CLI**: Professional command structure with aliases (18 D, 18 AR, etc.)
- **Proper audit trail**: MasterLog + IncidentHistory for full accountability
- **Modular frontend**: Bootloader + module system is well-organized
- **Incident lifecycle**: Calltaker → Dispatch → Status → Disposition → Close flow exists
- **Unit management**: Status tracking, crew assignments, shift roster

### Pain Points (What Needs Fixing)

#### P0 - Critical Fixes
1. **Shift context / Unit filtering** - Units not showing correctly for selected shift
2. **Daily Log** - Not behaving as running timeline, visibility bugs
3. **Toolbar** - Buttons need to work reliably

#### P1 - UX Improvements
4. **IAW (Incident Action Window)** - Too bulky, needs compact header
5. **Theme system** - No user preferences yet
6. **Settings** - No operational preferences

#### P2 - Feature Gaps (vs Commercial CAD)
7. **Keyboard shortcuts** - F2 new call, F5 refresh, etc.
8. **Sound alerts** - New incident, priority dispatch
9. **Quick status buttons** - One-click status changes
10. **Auto-refresh** - Panels should poll for changes

---

## Development Phases

### Phase 3.1 — Stabilization (Current Priority)

**Goal**: Make what exists work reliably

1. **Fix shift filtering**
   - Ensure unit panel respects session shift
   - 1578 + Car1 always visible
   - Current shift BC only (not all BCs)
   - "View All Units" toggle working

2. **Daily Log as timeline**
   - Display as reverse-chronological feed
   - Remove narrative requirement
   - Fix visibility/persistence bugs
   - AR routing: incident remark vs daily log

3. **Toolbar wiring**
   - New Incident → opens calltaker
   - Refresh → refreshes all panels
   - Daily Log → opens daily log viewer
   - History → opens history search
   - Held → shows held count + opens modal

### Phase 3.2 — User Experience

**Goal**: Make it feel professional

1. **Theme System**
   - CSS variable-based themes
   - User preference stored in session/DB
   - Options: Light (Ford Blue), Dark, High Contrast
   - Per-user persistence

2. **Compact IAW**
   - Mini-calltaker header (Type | Location | Priority in one line)
   - Collapsible sections
   - Better information density
   - Faster scanning

3. **Settings Panel**
   - Theme selection
   - Sound on/off
   - Auto-refresh interval
   - Notification preferences
   - Default incident type

4. **Keyboard Shortcuts**
   - F2: New Incident
   - F5: Refresh
   - F9: Daily Log
   - ESC: Close modal
   - Ctrl+Enter: Submit form

### Phase 3.3 — Polish & Professionalism

**Goal**: Commercial-grade feel

1. **Sound System**
   - New incident alert
   - High priority dispatch tone
   - Unit status change chime
   - Mutable per user preference

2. **Auto-refresh**
   - Panel polling (configurable 15-60s)
   - WebSocket option for real-time
   - Visual indicator when refresh pending

3. **Unit Cards**
   - Compact status display
   - Drag handle for dispatch
   - Right-click context menu
   - Double-click for UAW

4. **Toast Notifications**
   - Success/error feedback
   - Non-blocking alerts
   - Auto-dismiss

### Phase 4 — Multi-User Ready

**Goal**: LAN deployment

1. **Session management**
   - Multiple simultaneous dispatchers
   - Conflict handling (unit already dispatched)
   - Activity indicators

2. **Real-time sync**
   - WebSocket for instant updates
   - Optimistic UI with rollback

3. **User roles**
   - Dispatcher permissions
   - Admin-only settings
   - Read-only observer mode

---

## Commercial CAD Features to Emulate

### From Tyler New World
- Drag-and-drop dispatch (you have this!)
- Command line shortcuts (you have this!)
- Split-panel layout (you have this!)
- Status color coding (you have this!)

### From Mark43 (Modern UX)
- Clean card-based UI
- Collapsible incident details
- Timeline view for incident history
- Dark mode option

### From Hexagon/Intergraph
- Keyboard-driven workflow
- Audible alerts
- Multi-monitor support (future)

### Industrial-Specific Needs
- Offline-first (you have this!)
- Fast boot time
- Minimal training required
- Works on older hardware

---

## Immediate Next Steps

1. **Pick one pain point** and I'll fix it
2. **Theme system** is quick win for user-friendliness
3. **Shift filtering** is highest impact for actual use

What do you want me to tackle first?
