// ============================================================================
// FORD-CAD — DRAG ENGINE
// Phase-3 Canonical (Non-invasive)
// ============================================================================
// Responsibilities:
//   • Provide universal drag behavior for modal windows
//
// Critical rule:
//   • This module MUST NOT override feature modules (IAW/UAW/REMARK/ISSUE/etc).
//   • It only injects startDrag if a module object is present but missing it.
// ============================================================================

export const CAD_DRAG = {
  target: null,
  offsetX: 0,
  offsetY: 0,
  active: false,

  startDrag(event, modalSelector = ".cad-modal") {
    const modal = event.target.closest(modalSelector);
    if (!modal) return;

    this.target = modal;
    const rect = modal.getBoundingClientRect();
    this.offsetX = event.clientX - rect.left;
    this.offsetY = event.clientY - rect.top;
    this.active = true;
    modal.style.zIndex = 9999;

    document.addEventListener("mousemove", this._move);
    document.addEventListener("mouseup", this._stop);
  },

  _move: (e) => {
    if (!CAD_DRAG.active || !CAD_DRAG.target) return;
    const modal = CAD_DRAG.target;

    let x = e.clientX - CAD_DRAG.offsetX;
    let y = e.clientY - CAD_DRAG.offsetY;

    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const rect = modal.getBoundingClientRect();

    if (x < 0) x = 0;
    if (y < 0) y = 0;
    if (x + rect.width > vw) x = vw - rect.width;
    if (y + rect.height > vh) y = vh - rect.height;

    modal.style.left = `${x}px`;
    modal.style.top = `${y}px`;
  },

  _stop: () => {
    CAD_DRAG.active = false;
    document.removeEventListener("mousemove", CAD_DRAG._move);
    document.removeEventListener("mouseup", CAD_DRAG._stop);
  },
};

// ---------------------------------------------------------------------------
// Global exposure (safe)
// ---------------------------------------------------------------------------
window.CAD_DRAG = CAD_DRAG;

function _ensureStartDrag(name) {
  try {
    const obj = window[name];
    if (!obj) return;
    if (typeof obj.startDrag !== "function") {
      obj.startDrag = (e) => CAD_DRAG.startDrag(e);
    }
  } catch (_) {}
}

// These are referenced by templates as onmousedown="X.startDrag(event)"
// Ensure startDrag exists without overriding real module implementations.
_ensureStartDrag("IAW");
_ensureStartDrag("DISP");
_ensureStartDrag("ISSUE");
_ensureStartDrag("PICKER");
_ensureStartDrag("REMARK");

console.log("[DRAG] CAD_DRAG exposed (non-invasive).");

export default CAD_DRAG;
