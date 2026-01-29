// ============================================================================
// FORD-CAD — CONTEXT MENU SYSTEM
// Professional-grade right-click menus for units, incidents, and crew
// ============================================================================

import { CAD_UTIL } from "./utils.js";

let _menu = null;
let _target = null;
let _context = {};
let _selectedIndex = -1;
let _items = [];

// ============================================================================
// CORE MENU FUNCTIONS
// ============================================================================

function _createMenuElement() {
  const el = document.createElement("div");
  el.className = "cad-context-menu";
  el.setAttribute("role", "menu");
  el.setAttribute("tabindex", "-1");
  return el;
}

function _renderItems(items) {
  _items = items.filter(i => !i.hidden);
  let html = "";

  _items.forEach((item, idx) => {
    if (item.separator) {
      html += `<div class="cad-context-menu-separator" role="separator"></div>`;
    } else if (item.submenu && item.submenu.length > 0) {
      html += `
        <div class="cad-context-menu-item has-submenu ${item.disabled ? 'disabled' : ''}"
             role="menuitem"
             data-index="${idx}"
             data-action="${item.action || ''}"
             aria-haspopup="true">
          <span class="cad-context-menu-label">${item.label}</span>
          <span class="cad-context-menu-arrow">&#9656;</span>
          <div class="cad-context-submenu" role="menu">
            ${item.submenu.map((sub, subIdx) => `
              <div class="cad-context-menu-item ${sub.disabled ? 'disabled' : ''}"
                   role="menuitem"
                   data-action="${sub.action || ''}"
                   data-value="${sub.value || ''}">
                <span class="cad-context-menu-label">${sub.label}</span>
              </div>
            `).join('')}
          </div>
        </div>
      `;
    } else {
      html += `
        <div class="cad-context-menu-item ${item.disabled ? 'disabled' : ''}"
             role="menuitem"
             data-index="${idx}"
             data-action="${item.action || ''}">
          <span class="cad-context-menu-label">${item.label}</span>
          ${item.shortcut ? `<span class="cad-context-menu-shortcut">${item.shortcut}</span>` : ''}
        </div>
      `;
    }
  });

  return html;
}

function show(x, y, items, context = {}) {
  hide(); // Close any existing menu

  _context = context;
  _menu = _createMenuElement();
  _menu.innerHTML = _renderItems(items);
  document.body.appendChild(_menu);

  // Position with viewport clamping
  const rect = _menu.getBoundingClientRect();
  const vw = window.innerWidth;
  const vh = window.innerHeight;

  let left = x;
  let top = y;

  if (x + rect.width > vw - 8) {
    left = vw - rect.width - 8;
  }
  if (y + rect.height > vh - 8) {
    top = vh - rect.height - 8;
  }

  _menu.style.left = `${Math.max(8, left)}px`;
  _menu.style.top = `${Math.max(8, top)}px`;

  // Wire up click handlers
  _menu.addEventListener("click", _handleMenuClick);
  _menu.addEventListener("mouseover", _handleMouseOver);

  // Focus for keyboard nav
  _menu.focus();
  _selectedIndex = -1;

  // Close on outside click (delayed to avoid immediate close)
  setTimeout(() => {
    document.addEventListener("click", _handleOutsideClick);
    document.addEventListener("contextmenu", _handleOutsideClick);
  }, 10);

  // Close on escape
  document.addEventListener("keydown", _handleKeyDown);
}

function hide() {
  if (_menu) {
    _menu.remove();
    _menu = null;
  }
  _target = null;
  _context = {};
  _items = [];
  _selectedIndex = -1;

  document.removeEventListener("click", _handleOutsideClick);
  document.removeEventListener("contextmenu", _handleOutsideClick);
  document.removeEventListener("keydown", _handleKeyDown);
}

// ============================================================================
// EVENT HANDLERS
// ============================================================================

function _handleMenuClick(e) {
  const item = e.target.closest(".cad-context-menu-item");
  if (!item || item.classList.contains("disabled")) return;

  const action = item.dataset.action;
  const value = item.dataset.value;

  if (action) {
    _executeAction(action, value);
  }

  // Don't close if clicking submenu parent
  if (!item.classList.contains("has-submenu")) {
    hide();
  }
}

function _handleMouseOver(e) {
  const item = e.target.closest(".cad-context-menu-item");
  if (item && !item.classList.contains("disabled")) {
    const idx = parseInt(item.dataset.index);
    if (!isNaN(idx)) {
      _selectItem(idx);
    }
  }
}

function _handleOutsideClick(e) {
  if (_menu && !_menu.contains(e.target)) {
    hide();
  }
}

function _handleKeyDown(e) {
  if (!_menu) return;

  switch (e.key) {
    case "Escape":
      e.preventDefault();
      hide();
      break;
    case "ArrowDown":
      e.preventDefault();
      _navigateItems(1);
      break;
    case "ArrowUp":
      e.preventDefault();
      _navigateItems(-1);
      break;
    case "Enter":
    case " ":
      e.preventDefault();
      _activateSelected();
      break;
  }
}

function _selectItem(idx) {
  const items = _menu?.querySelectorAll(".cad-context-menu-item:not(.disabled)");
  if (!items) return;

  items.forEach((el, i) => {
    el.classList.toggle("selected", i === idx);
  });
  _selectedIndex = idx;
}

function _navigateItems(delta) {
  const items = _menu?.querySelectorAll(".cad-context-menu-item:not(.disabled)");
  if (!items || items.length === 0) return;

  let newIdx = _selectedIndex + delta;
  if (newIdx < 0) newIdx = items.length - 1;
  if (newIdx >= items.length) newIdx = 0;

  _selectItem(newIdx);
}

function _activateSelected() {
  const items = _menu?.querySelectorAll(".cad-context-menu-item:not(.disabled)");
  if (!items || _selectedIndex < 0 || _selectedIndex >= items.length) return;

  const item = items[_selectedIndex];
  const action = item.dataset.action;
  const value = item.dataset.value;

  if (action) {
    _executeAction(action, value);
  }

  if (!item.classList.contains("has-submenu")) {
    hide();
  }
}

// ============================================================================
// ACTION EXECUTION
// ============================================================================

async function _executeAction(action, value) {
  const unitId = _context.unitId;
  const incidentId = _context.incidentId;
  const personnelId = _context.personnelId;
  const apparatusId = _context.apparatusId;

  try {
    switch (action) {
      // Coverage actions
      case "coverage_add":
        await CAD_UTIL.postJSON("/api/shift_override/start", {
          unit_id: unitId,
          reason: "Manual coverage"
        });
        CAD_UTIL.refreshPanels();
        break;

      case "coverage_remove":
        await CAD_UTIL.postJSON("/api/shift_override/end", {
          unit_id: unitId
        });
        CAD_UTIL.refreshPanels();
        break;

      // Status actions
      case "status_available":
        await CAD_UTIL.postJSON(`/api/unit_status/${unitId}/AVAILABLE`);
        CAD_UTIL.refreshPanels();
        break;

      case "status_oos":
        await CAD_UTIL.postJSON(`/api/unit_status/${unitId}/OOS`);
        CAD_UTIL.refreshPanels();
        break;

      case "status_107":
        await CAD_UTIL.postJSON(`/api/uaw/misc/${unitId}`, { misc: "10-7" });
        CAD_UTIL.refreshPanels();
        break;

      // Crew actions
      case "assign_apparatus":
        if (value && unitId) {
          await CAD_UTIL.postJSON("/api/crew/assign", {
            apparatus_id: value,
            personnel_id: unitId
          });
          CAD_UTIL.refreshPanels();
        }
        break;

      case "unassign_apparatus":
        if (apparatusId && personnelId) {
          await CAD_UTIL.postJSON("/api/crew/unassign", {
            apparatus_id: apparatusId,
            personnel_id: personnelId
          });
          CAD_UTIL.refreshPanels();
        } else if (_context.currentApparatus && unitId) {
          await CAD_UTIL.postJSON("/api/crew/unassign", {
            apparatus_id: _context.currentApparatus,
            personnel_id: unitId
          });
          CAD_UTIL.refreshPanels();
        }
        break;

      // View actions
      case "view_details":
        if (unitId && window.UAW?.open) {
          window.UAW.open(unitId);
        }
        break;

      case "view_incident":
        if (incidentId && window.IAW?.open) {
          window.IAW.open(incidentId);
        }
        break;

      // Dispatch action
      case "dispatch":
        if (unitId && window.PICKER?.openForUnit) {
          window.PICKER.openForUnit(unitId);
        } else if (unitId) {
          // Fallback: use CLI dispatch mode
          const cli = document.getElementById("cmd-input");
          if (cli) {
            cli.value = `${unitId} D`;
            cli.focus();
          }
        }
        break;

      // Remark action
      case "add_remark":
        if (window.REMARK?.openForUnit && unitId) {
          window.REMARK.openForUnit(unitId);
        } else if (window.CAD_MODAL?.open) {
          window.CAD_MODAL.open(`/modals/remark?unit_id=${unitId}`);
        }
        break;

      // Manage crew (open UAW to crew tab)
      case "manage_crew":
        if (unitId && window.UAW?.openCrewMode) {
          window.UAW.openCrewMode(unitId);
        } else if (unitId && window.UAW?.open) {
          window.UAW.open(unitId);
        }
        break;

      // Panel-level actions
      case "view_all_units":
        await CAD_UTIL.postJSON("/api/session/roster_view_mode", { mode: "ALL" });
        CAD_UTIL.refreshPanels();
        break;

      case "view_shift_units":
        await CAD_UTIL.postJSON("/api/session/roster_view_mode", { mode: "CURRENT" });
        CAD_UTIL.refreshPanels();
        break;

      case "add_unit_prompt":
        // Focus CLI with AU command starter
        const cliInput = document.getElementById("cmd-input");
        if (cliInput) {
          cliInput.value = "";
          cliInput.placeholder = "Type unit ID then AU (e.g., 32 AU)";
          cliInput.focus();
        }
        break;

      case "refresh_panels":
        CAD_UTIL.refreshPanels();
        break;
    }
  } catch (err) {
    console.error("[CONTEXTMENU] Action failed:", action, err);
    alert(`Action failed: ${err.message || err}`);
  }
}

// ============================================================================
// MENU BUILDERS
// ============================================================================

function getUnitMenuItems(unitId, context = {}) {
  const isPersonnel = context.isPersonnel;
  const isApparatus = context.isApparatus;
  const isCommand = context.isCommand;
  const hasCoverage = context.hasCoverage;
  const currentApparatus = context.currentApparatus;
  const apparatusList = context.apparatusList || [];

  const items = [];

  // Coverage options (for all units not on current shift)
  if (!hasCoverage) {
    items.push({
      label: "Add to Shift Coverage",
      action: "coverage_add"
    });
  } else {
    items.push({
      label: "Remove from Coverage",
      action: "coverage_remove"
    });
  }

  items.push({ separator: true });

  // Dispatch (for apparatus and command)
  if (isApparatus || isCommand) {
    items.push({
      label: "Dispatch",
      action: "dispatch"
    });
  }

  // Status submenu
  items.push({
    label: "Set Status",
    submenu: [
      { label: "Available", action: "status_available" },
      { label: "10-7 (Out of Service)", action: "status_107" },
      { label: "OOS", action: "status_oos" }
    ]
  });

  // Personnel-specific options
  if (isPersonnel) {
    if (currentApparatus) {
      items.push({
        label: `Unassign from ${currentApparatus}`,
        action: "unassign_apparatus"
      });
    }

    if (apparatusList.length > 0) {
      items.push({
        label: "Assign to Apparatus",
        submenu: apparatusList.map(a => ({
          label: a,
          action: "assign_apparatus",
          value: a
        }))
      });
    }
  }

  // Apparatus-specific options
  if (isApparatus) {
    items.push({
      label: "Manage Crew",
      action: "manage_crew"
    });
  }

  items.push({ separator: true });

  items.push({
    label: "Add Remark",
    action: "add_remark"
  });

  items.push({
    label: "View Details",
    action: "view_details"
  });

  return items;
}

function getIncidentMenuItems(incidentId, context = {}) {
  return [
    { label: "Open Incident", action: "view_incident" },
    { separator: true },
    { label: "Add Remark", action: "add_remark" },
    { label: "Dispatch Units", action: "dispatch" }
  ];
}

// ============================================================================
// PUBLIC API - Show menu for specific element types
// ============================================================================

function showForUnit(event, unitId, element) {
  event.preventDefault();
  event.stopPropagation();

  _target = element;

  // Extract context from element data attributes
  const isPersonnel = element?.dataset?.isPersonnel === "1";
  const isApparatus = element?.dataset?.isApparatus === "1";
  const isCommand = element?.dataset?.isCommand === "1";
  const hasCoverage = element?.dataset?.hasCoverage === "1";
  const currentApparatus = element?.dataset?.currentApparatus || null;

  // Get list of available apparatus for assignment
  const apparatusList = [];
  document.querySelectorAll('.unit-row[data-is-apparatus="1"]').forEach(row => {
    const id = row.dataset.unitId;
    if (id) apparatusList.push(id);
  });

  const context = {
    unitId,
    isPersonnel,
    isApparatus,
    isCommand,
    hasCoverage,
    currentApparatus,
    apparatusList
  };

  const items = getUnitMenuItems(unitId, context);
  show(event.clientX, event.clientY, items, context);
}

function showForIncident(event, incidentId, element) {
  event.preventDefault();
  event.stopPropagation();

  _target = element;

  const context = { incidentId };
  const items = getIncidentMenuItems(incidentId, context);
  show(event.clientX, event.clientY, items, context);
}

function showForCrewChip(event, personnelId, apparatusId, element) {
  event.preventDefault();
  event.stopPropagation();

  _target = element;

  const context = { personnelId, apparatusId };
  const items = [
    {
      label: `Unassign ${personnelId} from ${apparatusId}`,
      action: "unassign_apparatus"
    },
    { separator: true },
    {
      label: "View Details",
      action: "view_details"
    }
  ];

  show(event.clientX, event.clientY, items, context);
}

function showForUnitsPanel(event, element) {
  event.preventDefault();
  event.stopPropagation();

  // Don't show if clicking on a unit row (let that handler take over)
  if (event.target.closest(".unit-row") || event.target.closest(".crew-chip")) {
    return;
  }

  _target = element;

  const context = { panel: "units" };
  const items = [
    {
      label: "View All Department Units",
      action: "view_all_units"
    },
    {
      label: "View Current Shift Only",
      action: "view_shift_units"
    },
    { separator: true },
    {
      label: "Add Unit to Shift",
      action: "add_unit_prompt"
    },
    { separator: true },
    {
      label: "Refresh Units",
      action: "refresh_panels"
    }
  ];

  show(event.clientX, event.clientY, items, context);
}

// ============================================================================
// INITIALIZATION
// ============================================================================

function init() {
  // Global keyboard shortcut for context menu (Shift+F10)
  document.addEventListener("keydown", (e) => {
    if (e.key === "F10" && e.shiftKey) {
      e.preventDefault();
      const focused = document.activeElement;
      if (focused?.dataset?.unitId) {
        const rect = focused.getBoundingClientRect();
        showForUnit(
          { clientX: rect.left + 10, clientY: rect.bottom, preventDefault: () => {}, stopPropagation: () => {} },
          focused.dataset.unitId,
          focused
        );
      }
    }

    // Context menu key (on some keyboards)
    if (e.key === "ContextMenu") {
      e.preventDefault();
      const focused = document.activeElement;
      if (focused?.dataset?.unitId) {
        const rect = focused.getBoundingClientRect();
        showForUnit(
          { clientX: rect.left + 10, clientY: rect.bottom, preventDefault: () => {}, stopPropagation: () => {} },
          focused.dataset.unitId,
          focused
        );
      }
    }
  });

  console.log("[CONTEXTMENU] Module initialized (professional-grade right-click menus)");
}

// ============================================================================
// EXPORTS
// ============================================================================

export const CAD_CONTEXTMENU = {
  init,
  show,
  hide,
  showForUnit,
  showForIncident,
  showForCrewChip,
  showForUnitsPanel,
  getUnitMenuItems,
  getIncidentMenuItems
};

window.CAD_CONTEXTMENU = CAD_CONTEXTMENU;

export default CAD_CONTEXTMENU;
