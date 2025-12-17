// ============================================================================
// FORD CAD — EVENT DISPOSITION ENGINE (CANONICAL)
// Phase-3 Stabilized Edition
// ============================================================================
// Responsibilities:
//   • Open Event Disposition modal
//   • Submit Event Disposition to canonical backend endpoint
//   • Prevent double-submit
//   • Refresh CAD panels after backend confirmation
//
// Explicitly Forbidden:
//   • Writing narrative
//   • Closing incidents client-side
//   • Reopening IAW
//   • Incident lifecycle decisions
// ============================================================================

import { BOSK_MODAL } from "./modal.js";
import { BOSK_UTIL } from "./utils.js";

export const DISP = {

    // ------------------------------------------------------------
    // OPEN EVENT DISPOSITION MODAL
    // ------------------------------------------------------------
    open(incident_id) {
        if (!incident_id) {
            alert("No incident selected.");
            return;
        }

        try {
            BOSK_MODAL.open("/modals/event_disposition", { incident_id });
        } catch (err) {
            console.error("[DISPOSITION] Failed to open modal:", err);
        }
    },

    // ------------------------------------------------------------
    // SUBMIT EVENT DISPOSITION (CANONICAL)
    // formData = {
    //   incident_id: number,
    //   disposition: string,
    //   notes?: string
    // }
    // ------------------------------------------------------------
    async submit(formData) {

        if (!formData?.incident_id || !formData?.disposition) {
            alert("Disposition and incident are required.");
            return;
        }

        try {
            this.lockButtons();

            await BOSK_UTIL.postJSON(
                "/incident/event_disposition",
                formData
            );

            // Close modal after successful submission
            BOSK_MODAL.close();

            // Refresh all CAD panels (Active/Open/Held/Units)
            if (window.BOSK?.panels?.refreshAll) {
                window.BOSK.panels.refreshAll();
            }

        } catch (err) {
            console.error("[DISPOSITION] Submit failed:", err);
            alert("Unable to submit event disposition.");
        } finally {
            this.unlockButtons();
        }
    },

    // ------------------------------------------------------------
    // PREVENT DOUBLE SUBMIT
    // ------------------------------------------------------------
    lockButtons() {
        document
            .querySelectorAll(".disp-btn, .pill-btn, button[type='submit']")
            .forEach(b => b.disabled = true);
    },

    unlockButtons() {
        document
            .querySelectorAll(".disp-btn, .pill-btn, button[type='submit']")
            .forEach(b => b.disabled = false);
    }
};

// Freeze for runtime safety
Object.freeze(DISP);

console.log("[DISPOSITION] Module loaded (Ford CAD — Phase-3 Canonical)");

export default DISP;
