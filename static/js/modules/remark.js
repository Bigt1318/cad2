// ============================================================================
// BOSK-CAD — REMARK ENGINE (CANONICAL)
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

import { BOSK_MODAL } from "./modal.js";
import { BOSK_UTIL } from "./utils.js";

export const REMARK = {

    // ------------------------------------------------------------
    // OPEN GLOBAL REMARK MODAL
    // ------------------------------------------------------------
    // Optional context may be passed (incident_id, unit_id),
    // but routing decisions are handled by the backend.
    // ------------------------------------------------------------
    open(context = {}) {
        try {
            BOSK_MODAL.open("/modals/remark", context);
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

            await BOSK_UTIL.postJSON("/remark", payload);

            // Close modal after successful submit
            BOSK_MODAL.close();

            // Refresh all panels to reflect new state
            if (window.BOSK?.panels?.refreshAll) {
                window.BOSK.panels.refreshAll();
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
        btns.forEach(b => b.disabled = true);
    },

    unlockButtons() {
        const btns = document.querySelectorAll(
            ".remark-btn, .pill-btn, button[type='submit']"
        );
        btns.forEach(b => b.disabled = false);
    }
};

// Prevent accidental runtime mutation
Object.freeze(REMARK);

console.log("[REMARK] Module loaded (Phase-3 Canonical)");

export default REMARK;
