// ============================================================================
// FORD CAD — ISSUE FOUND ENGINE (CANONICAL)
// Phase-3 Stabilized Edition
// ============================================================================
// Responsibilities:
//   • Open Issue Found modals (new / view)
//   • Submit Issue Found report to canonical backend endpoint
//   • Prevent double-submit
//   • Refresh CAD panels after backend confirmation
//
// Explicitly Forbidden:
//   • Writing narrative
//   • Incident lifecycle control
//   • Reopening IAW
//   • Incident-scoped routing logic
// ============================================================================

import { BOSK_MODAL } from "./modal.js";
import { BOSK_UTIL } from "./utils.js";

export const ISSUE = {

    // ------------------------------------------------------------
    // OPEN NEW ISSUE FOUND MODAL
    // ------------------------------------------------------------
    openNew(incident_id) {
        if (!incident_id) {
            alert("No incident selected.");
            return;
        }

        try {
            BOSK_MODAL.open("/modals/issue_found/new", { incident_id });
        } catch (err) {
            console.error("[ISSUE] Failed to open new issue modal:", err);
        }
    },

    // ------------------------------------------------------------
    // OPEN VIEW ISSUE FOUND MODAL
    // ------------------------------------------------------------
    openView(incident_id) {
        if (!incident_id) {
            alert("No incident selected.");
            return;
        }

        try {
            BOSK_MODAL.open("/modals/issue_found/view", { incident_id });
        } catch (err) {
            console.error("[ISSUE] Failed to open issue view modal:", err);
        }
    },

    // ------------------------------------------------------------
    // SUBMIT ISSUE FOUND REPORT (CANONICAL)
    // payload = {
    //   incident_id: number,
    //   issue_text: string,
    //   followup_required?: 0 | 1
    // }
    // ------------------------------------------------------------
    async submit(payload) {

        if (!payload?.incident_id || !payload?.issue_text) {
            alert("Issue text is required.");
            return;
        }

        try {
            this.lockButtons();

            await BOSK_UTIL.postJSON(
                "/issue_found",
                payload
            );

            // Close modal after successful submit
            BOSK_MODAL.close();

            // Refresh CAD panels to reflect issue flag state
            if (window.BOSK?.panels?.refreshAll) {
                window.BOSK.panels.refreshAll();
            }

        } catch (err) {
            console.error("[ISSUE] Submit failed:", err);
            alert("Unable to submit Issue Found report.");
        } finally {
            this.unlockButtons();
        }
    },

    // ------------------------------------------------------------
    // PREVENT DOUBLE SUBMIT
    // ------------------------------------------------------------
    lockButtons() {
        document
            .querySelectorAll(".issue-btn, .pill-btn, button[type='submit']")
            .forEach(b => b.disabled = true);
    },

    unlockButtons() {
        document
            .querySelectorAll(".issue-btn, .pill-btn, button[type='submit']")
            .forEach(b => b.disabled = false);
    }
};

// Freeze for runtime safety
Object.freeze(ISSUE);

console.log("[ISSUE] Module loaded (Ford CAD — Phase-3 Canonical)");

export default ISSUE;
