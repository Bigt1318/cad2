// ============================================================================
// FORD CAD — LEGACY BRIDGE (SAFE)
// Phase-3 Canonical
// ============================================================================
// Purpose:
//   • Provide backwards-compatible global functions for older inline handlers
//   • MUST NOT mutate frozen / non-extensible global objects (ex: window.BOSK)
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

  // Prefer whatever the app exposes (some builds mount to window.BOSK.disposition)
  const boskOpen = globalThis?.BOSK?.disposition?.open;
  if (typeof boskOpen === "function") {
    boskOpen(id);
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
// Attempt (non-fatal) BOSK namespace exposure
//   - ONLY if possible without throwing
// -----------------------------
safeAttach(globalThis.BOSK, "dispositionIncident", dispositionIncident);
safeAttach(globalThis.BOSK, "iawOpen", iawOpen);
safeAttach(globalThis.BOSK, "iawClose", iawClose);
safeAttach(globalThis.BOSK, "uawOpen", uawOpen);


export default {};
