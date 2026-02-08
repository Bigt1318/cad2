// ============================================================================
// FORD-CAD — DRAG DISPATCH (CANONICAL)
// Fixes:
//   • No IAW auto-open on drag/drop (suppresses post-drop click)
//   • Always refresh panels after any successful drag command
//   • Uses default disposition "C" for clear unless backend forces prompt
//   • Crew assignment: drag personnel → apparatus row
//   • Crew unassignment: drag crew chip → units panel background
// ============================================================================

import { CAD_UTIL } from "./utils.js";
import DISP from "./disposition.js";

const SUPPRESS_CLICK_MS = 450;
let _suppressUntil = 0;
let _dragGhost = null;

function _suppressIncidentClicksBriefly() {
  _suppressUntil = Date.now() + SUPPRESS_CLICK_MS;
}

// Capture-phase click blocker to prevent onclick="IAW.open(...)" after drops
document.addEventListener(
  "click",
  (e) => {
    if (Date.now() <= _suppressUntil) {
      const row = e.target?.closest?.(".incident-row");
      if (row) {
        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation?.();
      }
    }
  },
  true
);

function _jsonFromDataTransfer(dt) {
  try {
    const raw = dt.getData("application/json") || dt.getData("text/plain") || "";
    if (!raw) return null;
    return JSON.parse(raw);
  } catch (_) {
    return null;
  }
}

function _setDragPayload(e, payload) {
  try {
    e.dataTransfer.setData("application/json", JSON.stringify(payload));
    e.dataTransfer.setData("text/plain", JSON.stringify(payload));
    e.dataTransfer.effectAllowed = "move";
  } catch (_) {}
}

function _unitIdFromDragStartTarget(target) {
  // Units panel rows: <div class="unit-row" data-unit-id="12">
  const row = target.closest?.(".unit-row");
  if (row?.dataset?.unitId) return row.dataset.unitId;

  // Incident unit chips (active/open panels): <button class="unit-chip"> ... <span class="unit-chip-id">12</span>
  const chip = target.closest?.(".unit-chip");
  if (chip) {
    const idEl = chip.querySelector?.(".unit-chip-id");
    const id = (idEl?.textContent || "").trim();
    if (id) return id;
  }

  return null;
}

// Extract drag payload info including crew chip detection
function _getDragPayloadFromTarget(target) {
  // Crew chip: <span class="crew-chip" data-personnel-id="12" data-apparatus-id="Engine1">
  const crewChip = target.closest?.(".crew-chip");
  if (crewChip?.dataset?.personnelId) {
    return {
      type: "crew_chip",
      personnel_id: crewChip.dataset.personnelId,
      apparatus_id: crewChip.dataset.apparatusId || null,
    };
  }

  // Unit row in units panel
  const row = target.closest?.(".unit-row");
  if (row?.dataset?.unitId) {
    return {
      type: "unit",
      unit_id: row.dataset.unitId,
      is_personnel: row.dataset.isPersonnel === "1",
      is_apparatus: row.dataset.isApparatus === "1",
      from_incident_id: _incidentIdFromElement(target),
    };
  }

  // Incident unit chips
  const chip = target.closest?.(".unit-chip");
  if (chip) {
    const idEl = chip.querySelector?.(".unit-chip-id");
    const id = (idEl?.textContent || "").trim();
    if (id) {
      return {
        type: "unit",
        unit_id: id,
        is_personnel: false,
        is_apparatus: false,
        from_incident_id: _incidentIdFromElement(target),
      };
    }
  }

  return null;
}

// Check if drop target is an apparatus row
function _isDropOnApparatusRow(el) {
  const row = el.closest?.(".unit-row");
  return row?.dataset?.isApparatus === "1";
}

function _getApparatusIdFromDropTarget(el) {
  const row = el.closest?.(".unit-row");
  if (row?.dataset?.isApparatus === "1") {
    return row.dataset.unitId || null;
  }
  return null;
}

// Crew assignment API calls
async function _assignCrewToApparatus(personnelId, apparatusId) {
  return CAD_UTIL.postJSON("/api/crew/assign", {
    apparatus_id: String(apparatusId),
    personnel_id: String(personnelId),
  });
}

async function _unassignCrewFromApparatus(personnelId, apparatusId = null) {
  const payload = { personnel_id: String(personnelId) };
  if (apparatusId) payload.apparatus_id = String(apparatusId);
  return CAD_UTIL.postJSON("/api/crew/unassign", payload);
}

function _incidentIdFromElement(el) {
  const row = el.closest?.(".incident-row");
  const id = row?.dataset?.incidentId;
  return id ? Number(id) : null;
}

async function _clearUnitFromIncident(unitId, incidentId) {
  // Default = C, but if backend rejects due to required disposition/hold reason,
  // then prompt (only when required).
  let disposition = "C";
  let comment = "";

  try {
    const res = await CAD_UTIL.postJSON("/api/uaw/clear_unit", {
      incident_id: Number(incidentId),
      unit_id: String(unitId),
      disposition,
      comment,
    });

    // If backend indicates additional required flow, open disposition modal (NOT IAW)
    const needs =
      !!(res?.requires_event_disposition || res?.last_unit_cleared || res?.requires_disposition);
    if (needs) {
      try { DISP.open(Number(incidentId)); } catch (_) {}
    }
    return { ok: true };
  } catch (err) {
    const msg = String(err?.message || err || "");

    // Prompt only if required
    const looksRequired =
      /required|disposition|hold|reason|last unit/i.test(msg);

    if (!looksRequired) throw err;

    disposition =
      (prompt("Unit disposition required. Enter code (R/NA/NF/C/CT/O) or H to HOLD:", "C") || "C")
        .trim()
        .toUpperCase();

    if (disposition === "H") {
      comment = (prompt("Held reason (required):", "") || "").trim();
      if (!comment) throw new Error("Held requires a reason.");

      const held = await CAD_UTIL.postJSON(`/incident/${encodeURIComponent(Number(incidentId))}/hold`, {
        reason: comment,
      });
      if (held?.ok === false) throw new Error(held?.error || "Unable to hold incident.");
      return { ok: true };
    }

    comment = (prompt("Disposition note (optional):", "") || "").trim();

    await CAD_UTIL.postJSON("/api/uaw/clear_unit", {
      incident_id: Number(incidentId),
      unit_id: String(unitId),
      disposition,
      comment,
    });

    return { ok: true };
  }
}

async function _dispatchUnitToIncident(unitId, incidentId) {
  await CAD_UTIL.postJSON("/api/cli/dispatch", {
    units: [String(unitId)],
    incident_id: Number(incidentId),
    mode: "DE",
  });

  // Play dispatch sound
  try { window.SOUNDS?.unitDispatched?.(); } catch (_) {}

  // Best-effort set unit to DISPATCHED (some builds do this automatically)
  try {
    await CAD_UTIL.postJSON(
      `/api/unit_status/${encodeURIComponent(String(unitId))}/DISPATCHED`,
      {}
    );
  } catch (_) {}
}

function _isDropOnUnitsPanel(el) {
  return !!el.closest?.("#panel-units, .panel-units, #panel-units *");
}

function _isDropOnIncidentRow(el) {
  return !!el.closest?.(".incident-row");
}

// ============================================================================
// DRAG GHOST
// ============================================================================
function _createDragGhost(label) {
  _removeDragGhost();
  const ghost = document.createElement("div");
  ghost.className = "drag-ghost";
  ghost.textContent = label;
  Object.assign(ghost.style, {
    position: "fixed", top: "-100px", left: "-100px",
    padding: "4px 10px", borderRadius: "4px",
    background: "var(--ford-blue, #003478)", color: "#fff",
    fontSize: "0.8em", fontWeight: "600", fontFamily: "inherit",
    whiteSpace: "nowrap", zIndex: "99999", pointerEvents: "none",
    boxShadow: "0 2px 8px rgba(0,0,0,0.3)"
  });
  document.body.appendChild(ghost);
  _dragGhost = ghost;
  return ghost;
}

function _removeDragGhost() {
  if (_dragGhost) {
    _dragGhost.remove();
    _dragGhost = null;
  }
}

// ============================================================================
// DROP ZONE HIGHLIGHTING
// ============================================================================
function _addDropHighlight(el) {
  const row = el?.closest?.(".incident-row");
  if (row) row.classList.add("drag-drop-target");
  const apparatus = el?.closest?.(".unit-row[data-is-apparatus='1']");
  if (apparatus) apparatus.classList.add("drag-drop-target");
  const panel = el?.closest?.("#panel-units, .panel-units");
  if (panel && !row && !apparatus) panel.classList.add("drag-drop-target");
}

function _removeAllDropHighlights() {
  document.querySelectorAll(".drag-drop-target").forEach(el => el.classList.remove("drag-drop-target"));
}

// Inject drop-zone highlight styles once
(function _injectDragStyles() {
  if (document.getElementById("drag-dispatch-styles")) return;
  const style = document.createElement("style");
  style.id = "drag-dispatch-styles";
  style.textContent = `
    .drag-drop-target {
      outline: 2px solid var(--ford-blue, #003478) !important;
      outline-offset: -2px;
      background: rgba(0, 52, 120, 0.08) !important;
      transition: outline 0.15s, background 0.15s;
    }
    .drag-ghost {
      animation: ghost-fade-in 0.15s ease;
    }
    @keyframes ghost-fade-in {
      from { opacity: 0; transform: scale(0.85); }
      to   { opacity: 1; transform: scale(1); }
    }
  `;
  document.head.appendChild(style);
})();

// Delegated dragstart
document.addEventListener("dragstart", (e) => {
  const payload = _getDragPayloadFromTarget(e.target);
  if (!payload) return;

  // Create drag ghost with label
  let label = "";
  if (payload.type === "crew_chip") {
    label = payload.personnel_id || "Crew";
  } else {
    label = payload.unit_id || "Unit";
  }
  const ghost = _createDragGhost(label);
  e.dataTransfer.setDragImage(ghost, 0, 0);

  _setDragPayload(e, payload);
});

// Clean up ghost and highlights on drag end
document.addEventListener("dragend", () => {
  _removeDragGhost();
  _removeAllDropHighlights();
});

// Allow dropping on incident rows + units panel + apparatus rows (for crew assignment)
document.addEventListener("dragover", (e) => {
  if (_isDropOnIncidentRow(e.target) || _isDropOnUnitsPanel(e.target) || _isDropOnApparatusRow(e.target)) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    _addDropHighlight(e.target);
  }
});

// Remove highlight when leaving a drop zone
document.addEventListener("dragleave", (e) => {
  const row = e.target?.closest?.(".incident-row");
  if (row) row.classList.remove("drag-drop-target");
  const apparatus = e.target?.closest?.(".unit-row[data-is-apparatus='1']");
  if (apparatus) apparatus.classList.remove("drag-drop-target");
  const panel = e.target?.closest?.("#panel-units, .panel-units");
  if (panel) panel.classList.remove("drag-drop-target");
});

// Delegated drop
document.addEventListener("drop", async (e) => {
  const isOnIncident = _isDropOnIncidentRow(e.target);
  const isOnUnitsPanel = _isDropOnUnitsPanel(e.target);
  const isOnApparatus = _isDropOnApparatusRow(e.target);

  if (!(isOnIncident || isOnUnitsPanel || isOnApparatus)) return;

  e.preventDefault();
  e.stopPropagation();

  _suppressIncidentClicksBriefly();
  _removeAllDropHighlights();

  const payload = _jsonFromDataTransfer(e.dataTransfer);
  if (!payload) return;

  try {
    // ============================================================
    // CREW CHIP HANDLING
    // ============================================================
    if (payload.type === "crew_chip") {
      const personnelId = payload.personnel_id;
      const fromApparatusId = payload.apparatus_id;

      // Crew chip dropped on units panel background → unassign from apparatus
      if (isOnUnitsPanel && !isOnApparatus) {
        const res = await _unassignCrewFromApparatus(personnelId, fromApparatusId);
        if (res?.ok === false) {
          throw new Error(res?.error || "Crew unassign failed");
        }
        CAD_UTIL.refreshPanels({ source: "drag-crew-unassign", personnel_id: personnelId });
        return;
      }

      // Crew chip dropped on a different apparatus → reassign
      if (isOnApparatus) {
        const toApparatusId = _getApparatusIdFromDropTarget(e.target);
        if (toApparatusId && toApparatusId !== fromApparatusId) {
          const res = await _assignCrewToApparatus(personnelId, toApparatusId);
          if (res?.ok === false) {
            throw new Error(res?.error || "Crew reassign failed");
          }
          CAD_UTIL.refreshPanels({ source: "drag-crew-reassign", personnel_id: personnelId });
        }
        return;
      }

      return;
    }

    // ============================================================
    // UNIT HANDLING (dispatch, clear, crew assign)
    // ============================================================
    const unitId = payload.unit_id ? String(payload.unit_id) : null;
    const fromIncidentId = payload.from_incident_id ? Number(payload.from_incident_id) : null;
    const isPersonnel = !!payload.is_personnel;

    if (!unitId) return;

    // Personnel dropped on apparatus row → assign to crew
    if (isOnApparatus && isPersonnel && !fromIncidentId) {
      const apparatusId = _getApparatusIdFromDropTarget(e.target);
      if (apparatusId) {
        const res = await _assignCrewToApparatus(unitId, apparatusId);
        if (res?.ok === false) {
          throw new Error(res?.error || "Crew assign failed");
        }
        CAD_UTIL.refreshPanels({ source: "drag-crew-assign", personnel_id: unitId, apparatus_id: apparatusId });
        return;
      }
    }

    const dropIncidentId = _incidentIdFromElement(e.target);

    // Case 1: Drop onto incident row -> dispatch or transfer
    if (dropIncidentId) {
      // Transfer semantics: clear old then dispatch new
      if (fromIncidentId && fromIncidentId !== dropIncidentId) {
        // Confirm cross-incident transfer
        const ok = confirm(`Transfer ${unitId} from incident #${fromIncidentId} to incident #${dropIncidentId}?`);
        if (!ok) return;
        await _clearUnitFromIncident(unitId, fromIncidentId);
        await _dispatchUnitToIncident(unitId, dropIncidentId);
      } else if (!fromIncidentId) {
        // Dispatch from units panel onto incident
        await _dispatchUnitToIncident(unitId, dropIncidentId);
      }
      CAD_UTIL.refreshPanels({ source: "drag-drop", incident_id: dropIncidentId, unit_id: unitId });
      return;
    }

    // Case 2: Drop onto units panel -> clear from incident (auto-clear)
    if (isOnUnitsPanel && fromIncidentId) {
      await _clearUnitFromIncident(unitId, fromIncidentId);
      CAD_UTIL.refreshPanels({ source: "drag-clear", incident_id: fromIncidentId, unit_id: unitId });
      return;
    }
  } catch (err) {
    console.error("[DRAG_DISPATCH] drop failed:", err);
    try { CAD_UTIL.notify(String(err?.message || err)); } catch (_) {}
  }
});

