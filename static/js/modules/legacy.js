// ============================================================================
// FORD CAD — LEGACY BRIDGE (SAFE)
// Phase-3 Canonical
// ============================================================================
// Purpose:
//   • Provide backwards-compatible global functions for older inline handlers
//   • MUST NOT mutate frozen / non-extensible global objects (ex: window.FORD_CAD)
//   • MUST NOT throw during import (boot must continue)
//
// This fixes:
//   TypeError: Cannot add property dispositionIncident, object is not extensible
// ============================================================================

import IAW from "./iaw.js";
import UAW from "./uaw2.js";
import DISPOSITION from "./disposition.js";

// -----------------------------
// Safe attach helper
// -----------------------------
function safeAttach(target, key, value) {
  try {
    if (!target) return false;

    // If property already exists, assignment may still be allowed on sealed objects
    if (Object.prototype.hasOwnProperty.call(target, key)) {
      target[key] = value;
      return true;
    }

    // Only add new props if extensible
    if (Object.isExtensible(target)) {
      target[key] = value;
      return true;
    }

    return false;
  } catch (e) {
    return false;
  }
}

// -----------------------------
// Canonical wrappers
// -----------------------------
function dispositionIncident(incidentId) {
  const id = Number(incidentId);
  if (!id) return;

  // Prefer whatever the app exposes (some builds mount to window.FORD_CAD.disposition)
  const cadOpen = globalThis?.FORD_CAD?.disposition?.open;
  if (typeof cadOpen === "function") {
    cadOpen(id);
    return;
  }

  // Fallback to module export
  if (typeof DISPOSITION?.open === "function") {
    DISPOSITION.open(id);
    return;
  }

  console.warn("[LEGACY] dispositionIncident: no disposition opener available.");
}

function iawOpen(incidentId) {
  const id = Number(incidentId);
  if (!id) return;
  IAW.open(id);
}

function iawClose() {
  if (typeof IAW.close === "function") IAW.close();
}

function uawOpen(unitId, rowElem) {
  if (!unitId || !rowElem) return;
  UAW.open(unitId, rowElem);
}

// -----------------------------
// Expose globals for inline HTML
// -----------------------------
globalThis.dispositionIncident = dispositionIncident;
globalThis.iawOpen = iawOpen;
globalThis.iawClose = iawClose;
globalThis.uawOpen = uawOpen;

// -----------------------------
// Attempt (non-fatal) FORD_CAD namespace exposure
//   - ONLY if possible without throwing
// -----------------------------
safeAttach(globalThis.FORD_CAD, "dispositionIncident", dispositionIncident);
safeAttach(globalThis.FORD_CAD, "iawOpen", iawOpen);
safeAttach(globalThis.FORD_CAD, "iawClose", iawClose);
safeAttach(globalThis.FORD_CAD, "uawOpen", uawOpen);


export default {};
