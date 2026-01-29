// ============================================================================
// FORD-CAD — REMARK ENGINE (CANONICAL)
// Phase-3 Stabilized Edition
// ============================================================================
// Responsibilities:
//   • Open the global Remark overlay
//   • Collect remark form data
//   • Submit remarks to the SINGLE canonical backend route
//   • Prevent double-submit
//   • Refresh panels after submit
//
// Phase-3 Rules (ENFORCED):
//   • JS does NOT decide narrative vs Daily Log
//   • JS does NOT assume an incident exists
//   • JS submits ONLY to POST /remark
//   • Backend performs all routing & stamping
// ============================================================================

import { CAD_MODAL } from "./modal.js";
import { CAD_UTIL } from "./utils.js";

export const REMARK = {
  // ------------------------------------------------------------
  // OPEN GLOBAL REMARK MODAL
  // ------------------------------------------------------------
  // Optional context may be passed (incident_id, unit_id),
  // but routing decisions are handled by the backend.
  // ------------------------------------------------------------
  open(context = {}) {
    try {
      const inc = context?.incident_id ? Number(context.incident_id) : null;
      if (!inc) {
        alert("Select an incident first.");
        return;
      }
      CAD_MODAL.open(`/incident/${encodeURIComponent(inc)}/remark`);
    } catch (err) {
      console.error("[REMARK] Failed to open remark modal:", err);
    }
  },

  // ------------------------------------------------------------
  // SUBMIT REMARK (CANONICAL)
  // payload = {
  //   incident_id?: number,
  //   unit_id?: string,
  //   text: string (required)
  // }
  // ------------------------------------------------------------
  async submit(payload) {
    if (!payload?.text || !payload.text.trim()) {
      alert("Remark text is required.");
      return;
    }

    try {
      this.lockButtons();

      await CAD_UTIL.postJSON("/remark", payload);

      // Close modal after successful submit
      CAD_MODAL.close();

      // Refresh all panels to reflect new state
      if (window.CAD?.panels?.refreshAll) {
        window.CAD.panels.refreshAll();
      }
    } catch (err) {
      console.error("[REMARK] Submit failed:", err);
      alert("Unable to save remark.");
    } finally {
      this.unlockButtons();
    }
  },

  // ------------------------------------------------------------
  // PREVENT DOUBLE SUBMIT
  // ------------------------------------------------------------
  lockButtons() {
    const btns = document.querySelectorAll(
      ".remark-btn, .pill-btn, button[type='submit']"
    );
    btns.forEach((b) => (b.disabled = true));
  },

  unlockButtons() {
    const btns = document.querySelectorAll(
      ".remark-btn, .pill-btn, button[type='submit']"
    );
    btns.forEach((b) => (b.disabled = false));
  },
};

// -----------------------------------------------------------------------------
// GLOBAL EXPOSURE (templates use window.REMARK.*)
// -----------------------------------------------------------------------------
window.REMARK = REMARK;

// Helper for the remark_modal.html submit button
REMARK.submitFromModal = async function submitFromModal() {
  const inc = (document.getElementById("remark-incident-id")?.value || "").trim();
  const unit = (document.getElementById("remark-unit-id")?.value || "").trim();
  const text = (document.getElementById("remark-text")?.value || "").trim();

  await REMARK.submit({
    incident_id: inc ? Number(inc) : undefined,
    unit_id: unit || undefined,
    text,
  });
};

// Prevent accidental runtime mutation
Object.freeze(REMARK);

console.log("[REMARK] Module loaded (Phase-3 Canonical)");

export default REMARK;
