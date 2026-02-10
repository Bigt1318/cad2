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
let _menuX = 0;
let _menuY = 0;

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
        <div class="cad-context-menu-item ${item.disabled ? 'disabled' : ''} ${item.cssClass || ''}"
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
  _menuX = x;
  _menuY = y;
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

      case "view_profile":
        if (unitId && window.CAD_MODAL?.open) {
          window.CAD_MODAL.open(`/modals/employee_profile?unit_id=${encodeURIComponent(unitId)}`);
        }
        break;

      case "view_incident":
        if (incidentId && window.IAW?.open) {
          window.IAW.open(incidentId);
        }
        break;

      // Dispatch action - auto-dispatch to single incident or show picker
      case "dispatch":
        if (unitId) {
          // Check how many incidents exist
          const activeRows = document.querySelectorAll("#panel-active tr[data-row-num]");
          const openRows = document.querySelectorAll("#panel-open tr[data-row-num]");
          const heldRows = document.querySelectorAll("#panel-held tr[data-row-num]");
          const totalIncidents = activeRows.length + openRows.length + heldRows.length;

          if (totalIncidents === 0) {
            alert("No incidents. Create one first.");
          } else if (totalIncidents === 1) {
            // Auto-dispatch to single incident
            const row = activeRows[0] || openRows[0] || heldRows[0];
            const incidentId = row?.dataset?.incidentId;
            if (incidentId && window.CAD_UTIL?.postJSON) {
              window.CAD_UTIL.postJSON("/api/cli/dispatch", {
                incident_id: Number(incidentId),
                units: [unitId],
                mode: "D"
              }).then(res => {
                if (res?.ok) {
                  window.CAD_UTIL?.refreshPanels?.();
                  try { window.SOUNDS?.unitDispatched?.(); } catch (_) {}
                } else {
                  alert(res?.error || "Dispatch failed.");
                }
              }).catch(err => {
                alert(err?.message || "Dispatch failed.");
              });
            }
          } else {
            // Multiple incidents - use CLI for picker
            const cli = document.getElementById("cmd-input");
            if (cli) {
              cli.value = `${unitId} D`;
              cli.focus();
              // Trigger the command
              cli.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));
            }
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

      // Mark PAR (Personnel Accountability Report)
      case "mark_par":
        if (unitId) {
          await CAD_UTIL.postJSON(`/api/uaw/misc/${unitId}`, { misc: "PAR" });
          CAD_UTIL.refreshPanels();
          window.TOAST?.success?.(`${unitId} marked PAR`);
        }
        break;

      // Request Rehab
      case "request_rehab":
        if (unitId) {
          await CAD_UTIL.postJSON(`/api/uaw/misc/${unitId}`, { misc: "REHAB" });
          CAD_UTIL.refreshPanels();
          window.TOAST?.info?.(`${unitId} assigned to REHAB`);
        }
        break;

      // Transfer Command — show picker of other units on the same incident
      case "transfer_command":
        if (unitId) {
          const ctx2 = await CAD_UTIL.getJSON(`/api/uaw/context/${encodeURIComponent(unitId)}`);
          const incId2 = Number(ctx2?.active_incident_id || 0);
          if (!incId2) {
            window.TOAST?.error?.(`${unitId} is not on an active incident`);
            break;
          }
          // Get other units on scene
          try {
            const sceneRes = await CAD_UTIL.getJSON(`/api/uaw/scene_units/${encodeURIComponent(incId2)}`);
            const sceneUnits = (sceneRes?.units || []).filter(u => u.unit_id !== unitId);
            if (sceneUnits.length === 0) {
              // Only unit on scene — transfer command to self (make self command)
              await CAD_UTIL.postJSON("/api/uaw/transfer_command", {
                incident_id: incId2,
                unit_id: unitId
              });
              CAD_UTIL.refreshPanels();
              window.TOAST?.success?.(`${unitId} assigned as command`);
            } else {
              // Show picker
              const choices = sceneUnits.map(u => u.unit_id).join(", ");
              const target = prompt(`Transfer command from ${unitId} to which unit?\nUnits on scene: ${choices}`);
              if (target && target.trim()) {
                const targetUnit = target.trim().toUpperCase();
                const validUnit = sceneUnits.find(u => u.unit_id.toUpperCase() === targetUnit);
                if (!validUnit) {
                  window.TOAST?.error?.(`${targetUnit} is not on this incident`);
                  break;
                }
                await CAD_UTIL.postJSON("/api/uaw/transfer_command", {
                  incident_id: incId2,
                  unit_id: validUnit.unit_id
                });
                CAD_UTIL.refreshPanels();
                window.TOAST?.success?.(`Command transferred to ${validUnit.unit_id}`);
              }
            }
          } catch (e) {
            window.TOAST?.error?.(`Transfer failed: ${e.message || e}`);
          }
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

      // Incident actions
      case "hold_incident":
        if (incidentId) {
          const reason = (prompt("Hold reason (required):", "") || "").trim();
          if (!reason) {
            alert("Hold reason is required.");
            break;
          }
          await CAD_UTIL.postJSON(`/incident/${incidentId}/hold`, { reason });
          CAD_UTIL.refreshPanels();
          window.TOAST?.info?.(`Incident #${incidentId} placed on hold`);
        }
        break;

      case "unhold_incident":
        if (incidentId) {
          await CAD_UTIL.postJSON(`/incident/${incidentId}/unhold`, {});
          CAD_UTIL.refreshPanels();
          window.TOAST?.info?.(`Incident #${incidentId} removed from hold`);
        }
        break;

      case "close_incident":
        if (incidentId) {
          // Check for assigned units first, then show appropriate popup
          _showCloseIncidentFlow(incidentId, _menuX || 200, _menuY || 200);
        }
        break;

      case "incident_add_remark":
        if (incidentId && window.REMARK?.openForIncident) {
          window.REMARK.openForIncident(incidentId);
        } else if (incidentId && window.CAD_MODAL?.open) {
          window.CAD_MODAL.open(`/modals/remark?incident_id=${incidentId}`);
        }
        break;
    }
  } catch (err) {
    console.error("[CONTEXTMENU] Action failed:", action, err);
    alert(`Action failed: ${err.message || err}`);
  }
}

// ============================================================================
// INLINE DISPOSITION POPUP
// ============================================================================

let _dispoPopup = null;
let _dispoIncidentId = null;
let _dispoSelectedCode = null;

// Check for units and show appropriate close flow
async function _showCloseIncidentFlow(incidentId, x, y) {
  try {
    // Check how many units are assigned to this incident
    const res = await CAD_UTIL.getJSON(`/api/incident/${incidentId}/unit_count`);
    const unitCount = res?.count || 0;

    if (unitCount > 0) {
      // Units are assigned - show "Clear Units First" popup
      _showClearUnitsPopup(incidentId, unitCount, x, y);
    } else {
      // No units - show normal close popup
      _showInlineDispositionPopup(incidentId, x, y);
    }
  } catch (err) {
    console.error("[CONTEXTMENU] Failed to check unit count:", err);
    // Fallback to normal close popup
    _showInlineDispositionPopup(incidentId, x, y);
  }
}

// Popup for clearing units before closing
function _showClearUnitsPopup(incidentId, unitCount, x, y) {
  _closeDispositionPopup();

  _dispoIncidentId = incidentId;
  _dispoSelectedCode = null;

  const popup = document.createElement("div");
  popup.className = "cad-inline-dispo-popup";
  popup.innerHTML = `
    <div class="inline-dispo-header">
      <span class="inline-dispo-title">Close Incident #${incidentId}</span>
      <button class="inline-dispo-close" onclick="CAD_CONTEXTMENU.closeDispositionPopup()">&times;</button>
    </div>
    <div class="inline-dispo-warning">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"></circle>
        <line x1="12" y1="8" x2="12" y2="12"></line>
        <line x1="12" y1="16" x2="12.01" y2="16"></line>
      </svg>
      <span>${unitCount} unit(s) still assigned</span>
    </div>
    <div class="inline-dispo-label">Select disposition to clear all units & close</div>
    <div class="inline-dispo-grid">
      <button type="button" class="inline-dispo-btn" data-code="R" onclick="CAD_CONTEXTMENU.selectDispoCode('R', this)">
        <span class="dispo-label">Report</span><span class="dispo-code">R</span>
      </button>
      <button type="button" class="inline-dispo-btn" data-code="C" onclick="CAD_CONTEXTMENU.selectDispoCode('C', this)">
        <span class="dispo-label">Clear</span><span class="dispo-code">C</span>
      </button>
      <button type="button" class="inline-dispo-btn inline-dispo-cancel" data-code="X" onclick="CAD_CONTEXTMENU.selectDispoCode('X', this)">
        <span class="dispo-label">Cancel</span><span class="dispo-code">X</span>
      </button>
      <button type="button" class="inline-dispo-btn" data-code="FA" onclick="CAD_CONTEXTMENU.selectDispoCode('FA', this)">
        <span class="dispo-label">False Alarm</span><span class="dispo-code">FA</span>
      </button>
      <button type="button" class="inline-dispo-btn" data-code="NR" onclick="CAD_CONTEXTMENU.selectDispoCode('NR', this)">
        <span class="dispo-label">No Report</span><span class="dispo-code">NR</span>
      </button>
      <button type="button" class="inline-dispo-btn" data-code="UF" onclick="CAD_CONTEXTMENU.selectDispoCode('UF', this)">
        <span class="dispo-label">Unfounded</span><span class="dispo-code">UF</span>
      </button>
      <button type="button" class="inline-dispo-btn" data-code="NC" onclick="CAD_CONTEXTMENU.selectDispoCode('NC', this)">
        <span class="dispo-label">Neg Contact</span><span class="dispo-code">NC</span>
      </button>
      <button type="button" class="inline-dispo-btn inline-dispo-medical" data-code="T" onclick="CAD_CONTEXTMENU.selectDispoCode('T', this)">
        <span class="dispo-label">Transported</span><span class="dispo-code">T</span>
      </button>
      <button type="button" class="inline-dispo-btn inline-dispo-medical" data-code="PRTT" onclick="CAD_CONTEXTMENU.selectDispoCode('PRTT', this)">
        <span class="dispo-label">Pt Refused</span><span class="dispo-code">PRTT</span>
      </button>
    </div>
    <input type="text" class="inline-dispo-comment" id="inline-dispo-comment" placeholder="Optional comment...">
    <div class="inline-dispo-actions">
      <button class="inline-dispo-cancel-btn" onclick="CAD_CONTEXTMENU.closeDispositionPopup()">Cancel</button>
      ${window.CAD_IS_ADMIN ? '<button class="inline-dispo-force-btn" onclick="CAD_CONTEXTMENU.forceClearUnits()" title="Force clear ghost unit assignments (Admin only)">Force Clear</button>' : ''}
      <button class="inline-dispo-submit-btn" id="inline-dispo-submit" disabled onclick="CAD_CONTEXTMENU.clearUnitsAndClose()">Clear Units & Close</button>
    </div>
  `;

  document.body.appendChild(popup);
  _dispoPopup = popup;

  // Position
  const rect = popup.getBoundingClientRect();
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  let left = x, top = y;
  if (x + rect.width > vw - 10) left = vw - rect.width - 10;
  if (y + rect.height > vh - 10) top = vh - rect.height - 10;
  popup.style.left = `${Math.max(10, left)}px`;
  popup.style.top = `${Math.max(10, top)}px`;

  setTimeout(() => {
    document.addEventListener("click", _handleDispoOutsideClick);
    document.addEventListener("keydown", _handleDispoKeydown);
  }, 100);
}

// Clear all units with disposition and close incident
async function _clearUnitsAndClose() {
  if (!_dispoIncidentId || !_dispoSelectedCode) return;

  const comment = (_dispoPopup?.querySelector('#inline-dispo-comment')?.value || "").trim();

  const submitBtn = _dispoPopup?.querySelector('#inline-dispo-submit');
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.textContent = "Clearing...";
  }

  try {
    // Clear all units with the selected disposition
    await CAD_UTIL.postJSON(`/api/incident/${_dispoIncidentId}/clear_all_and_close`, {
      disposition: _dispoSelectedCode,
      comment: comment
    });

    _closeDispositionPopup();
    CAD_UTIL.refreshPanels();
    window.TOAST?.success?.(`Incident #${_dispoIncidentId} closed with disposition: ${_dispoSelectedCode}`);
  } catch (err) {
    console.error("[CONTEXTMENU] Clear and close failed:", err);
    window.TOAST?.error?.(`Failed to close: ${err.message || err}`);
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = "Clear Units & Close";
    }
  }
}

// Force clear ghost unit assignments (admin only)
async function _forceClearUnits() {
  if (!_dispoIncidentId) return;

  if (!confirm(`Force clear all unit assignments from incident #${_dispoIncidentId}?\n\nThis will mark all units as cleared even if they appear stuck.`)) {
    return;
  }

  try {
    const res = await CAD_UTIL.postJSON(`/api/incident/${_dispoIncidentId}/force_clear_units`, {});

    if (res?.ok) {
      _closeDispositionPopup();
      CAD_UTIL.refreshPanels();
      window.TOAST?.success?.(`Force cleared ${res.cleared_count || 0} unit(s) from incident #${_dispoIncidentId}`);
    } else {
      window.TOAST?.error?.(res?.error || 'Force clear failed');
    }
  } catch (err) {
    console.error("[CONTEXTMENU] Force clear failed:", err);
    window.TOAST?.error?.(`Failed to force clear: ${err.message || err}`);
  }
}

function _showInlineDispositionPopup(incidentId, x, y) {
  _closeDispositionPopup();

  _dispoIncidentId = incidentId;
  _dispoSelectedCode = null;

  const popup = document.createElement("div");
  popup.className = "cad-inline-dispo-popup";
  popup.innerHTML = `
    <div class="inline-dispo-header">
      <span class="inline-dispo-title">Close Incident #${incidentId}</span>
      <button class="inline-dispo-close" onclick="CAD_CONTEXTMENU.closeDispositionPopup()">&times;</button>
    </div>
    <div class="inline-dispo-label">Select Disposition</div>
    <div class="inline-dispo-grid">
      <button type="button" class="inline-dispo-btn" data-code="R" onclick="CAD_CONTEXTMENU.selectDispoCode('R', this)">
        <span class="dispo-label">Report</span><span class="dispo-code">R</span>
      </button>
      <button type="button" class="inline-dispo-btn" data-code="C" onclick="CAD_CONTEXTMENU.selectDispoCode('C', this)">
        <span class="dispo-label">Clear</span><span class="dispo-code">C</span>
      </button>
      <button type="button" class="inline-dispo-btn inline-dispo-cancel" data-code="X" onclick="CAD_CONTEXTMENU.selectDispoCode('X', this)">
        <span class="dispo-label">Cancel</span><span class="dispo-code">X</span>
      </button>
      <button type="button" class="inline-dispo-btn" data-code="FA" onclick="CAD_CONTEXTMENU.selectDispoCode('FA', this)">
        <span class="dispo-label">False Alarm</span><span class="dispo-code">FA</span>
      </button>
      <button type="button" class="inline-dispo-btn" data-code="NR" onclick="CAD_CONTEXTMENU.selectDispoCode('NR', this)">
        <span class="dispo-label">No Report</span><span class="dispo-code">NR</span>
      </button>
      <button type="button" class="inline-dispo-btn" data-code="UF" onclick="CAD_CONTEXTMENU.selectDispoCode('UF', this)">
        <span class="dispo-label">Unfounded</span><span class="dispo-code">UF</span>
      </button>
      <button type="button" class="inline-dispo-btn" data-code="NC" onclick="CAD_CONTEXTMENU.selectDispoCode('NC', this)">
        <span class="dispo-label">Neg Contact</span><span class="dispo-code">NC</span>
      </button>
      <button type="button" class="inline-dispo-btn inline-dispo-medical" data-code="T" onclick="CAD_CONTEXTMENU.selectDispoCode('T', this)">
        <span class="dispo-label">Transported</span><span class="dispo-code">T</span>
      </button>
      <button type="button" class="inline-dispo-btn inline-dispo-medical" data-code="PRTT" onclick="CAD_CONTEXTMENU.selectDispoCode('PRTT', this)">
        <span class="dispo-label">Pt Refused</span><span class="dispo-code">PRTT</span>
      </button>
    </div>
    <input type="text" class="inline-dispo-comment" id="inline-dispo-comment" placeholder="Optional comment...">
    <div class="inline-dispo-actions">
      <button class="inline-dispo-cancel-btn" onclick="CAD_CONTEXTMENU.closeDispositionPopup()">Cancel</button>
      <button class="inline-dispo-submit-btn" id="inline-dispo-submit" disabled onclick="CAD_CONTEXTMENU.submitDisposition()">Close Incident</button>
    </div>
  `;

  document.body.appendChild(popup);
  _dispoPopup = popup;

  // Position with viewport clamping
  const rect = popup.getBoundingClientRect();
  const vw = window.innerWidth;
  const vh = window.innerHeight;

  let left = x;
  let top = y;

  if (x + rect.width > vw - 10) left = vw - rect.width - 10;
  if (y + rect.height > vh - 10) top = vh - rect.height - 10;

  popup.style.left = `${Math.max(10, left)}px`;
  popup.style.top = `${Math.max(10, top)}px`;

  // Close on outside click (delay to avoid immediate close from menu click)
  setTimeout(() => {
    document.addEventListener("click", _handleDispoOutsideClick);
    document.addEventListener("keydown", _handleDispoKeydown);
  }, 100);
}

function _closeDispositionPopup() {
  if (_dispoPopup) {
    _dispoPopup.remove();
    _dispoPopup = null;
  }
  _dispoIncidentId = null;
  _dispoSelectedCode = null;
  document.removeEventListener("click", _handleDispoOutsideClick);
  document.removeEventListener("keydown", _handleDispoKeydown);
}

function _handleDispoOutsideClick(e) {
  if (_dispoPopup && !_dispoPopup.contains(e.target)) {
    _closeDispositionPopup();
  }
}

function _handleDispoKeydown(e) {
  if (e.key === "Escape") {
    _closeDispositionPopup();
  }
}

function _selectDispoCode(code, btn) {
  if (!_dispoPopup) return;

  // Remove selection from all buttons
  _dispoPopup.querySelectorAll('.inline-dispo-btn').forEach(b => b.classList.remove('selected'));

  // Select this button
  btn.classList.add('selected');
  _dispoSelectedCode = code;

  // Enable submit
  const submitBtn = _dispoPopup.querySelector('#inline-dispo-submit');
  if (submitBtn) submitBtn.disabled = false;
}

async function _submitDisposition() {
  if (!_dispoIncidentId || !_dispoSelectedCode) return;

  const comment = (_dispoPopup?.querySelector('#inline-dispo-comment')?.value || "").trim();

  // Disable buttons while submitting
  const submitBtn = _dispoPopup?.querySelector('#inline-dispo-submit');
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.textContent = "Closing...";
  }

  try {
    const res = await CAD_UTIL.postJSON(`/incident/${_dispoIncidentId}/disposition`, {
      code: _dispoSelectedCode,
      comment: comment
    });

    _closeDispositionPopup();
    CAD_UTIL.refreshPanels();

    if (res?.status === "CLOSED" || res?.status === "HELD") {
      window.TOAST?.success?.(`Incident closed with disposition: ${_dispoSelectedCode}`);
    } else if (res?.remaining_units > 0) {
      window.TOAST?.warning?.(`Disposition saved. ${res.remaining_units} unit(s) still assigned - clear units first.`);
    } else {
      window.TOAST?.success?.(`Incident disposition set: ${_dispoSelectedCode}`);
    }
  } catch (err) {
    console.error("[CONTEXTMENU] Disposition failed:", err);
    window.TOAST?.error?.(`Failed to close incident: ${err.message || err}`);
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = "Close Incident";
    }
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

  // Add Remark — FIRST and prominent
  items.push({
    label: "Add Remark",
    action: "add_remark",
    cssClass: "menu-item-primary"
  });

  items.push({ separator: true });

  // Dispatch - available for all dispatchable units
  items.push({
    label: "Dispatch",
    action: "dispatch"
  });

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

  // Status submenu
  items.push({
    label: "Set Status",
    submenu: [
      { label: "Available", action: "status_available" },
      { label: "10-7 (Out of Service)", action: "status_107" },
      { label: "OOS", action: "status_oos" }
    ]
  });

  // Quick actions
  items.push({
    label: "Quick Actions",
    submenu: [
      { label: "Mark PAR", action: "mark_par" },
      { label: "Request Rehab", action: "request_rehab" },
      { label: "Transfer Command", action: "transfer_command" }
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
    label: "View Details",
    action: "view_details"
  });

  items.push({
    label: "View Profile",
    action: "view_profile"
  });

  return items;
}

function getIncidentMenuItems(incidentId, context = {}) {
  const status = context.status || "";
  const isHeld = status.toUpperCase() === "HELD";

  const items = [
    { label: "Add Remark", action: "incident_add_remark", cssClass: "menu-item-primary" },
    { separator: true },
    { label: "Open Incident", action: "view_incident" },
    { label: "Dispatch Units", action: "dispatch" },
    { separator: true }
  ];

  // Hold/Unhold based on current status
  if (isHeld) {
    items.push({ label: "Unhold Incident", action: "unhold_incident" });
  } else {
    items.push({ label: "Hold Incident", action: "hold_incident" });
  }

  items.push({ label: "Close Incident", action: "close_incident" });

  return items;
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

  // Get status from element data attribute or parent row
  const row = element?.closest?.("tr") || element;
  const status = row?.dataset?.status || element?.dataset?.status || "";

  const context = { incidentId, status };
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
  getIncidentMenuItems,
  // Inline disposition popup
  closeDispositionPopup: _closeDispositionPopup,
  selectDispoCode: _selectDispoCode,
  submitDisposition: _submitDisposition,
  clearUnitsAndClose: _clearUnitsAndClose,
  forceClearUnits: _forceClearUnits
};

window.CAD_CONTEXTMENU = CAD_CONTEXTMENU;

export default CAD_CONTEXTMENU;
