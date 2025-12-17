// ============================================================================
// BOSK-CAD — LAYOUT CONTROLLER
// Phase-3 Enterprise Edition
// ============================================================================
// Controls:
//   - Held Call Watcher (badge + animation)
//   - Live Clock in Header
//   - Toolbar interactions (Held button -> open modal)
//   - Global refresh helpers
//   - BOSK-wide UI behavior hooks
// ============================================================================

import { BOSK_MODAL } from "./modal.js";
import { BOSK_UTIL } from "./utils.js";
import PANELS from "./panels.js";

export const LAYOUT = {

    // ======================================================================
    // INITIALIZATION (called automatically by bootloader.js)
    // ======================================================================
    init() {
        this.startClock();
        this.startHeldCallWatcher();
        console.log("[LAYOUT] Layout initialized.");
    },

    // ======================================================================
    // REAL-TIME CLOCK (header, top-right corner)
    // ======================================================================
    startClock() {
        const clockEl = document.getElementById("clock");
        if (!clockEl) {
            console.warn("[LAYOUT] Clock element not found.");
            return;
        }

        const updateClock = () => {
            const now = new Date();
            clockEl.textContent = now.toLocaleTimeString("en-US", {
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit"
            });
        };

        updateClock();
        setInterval(updateClock, 1000);
    },

    // ======================================================================
    // HELD CALL WATCHER (every 5 seconds)
    // Matches Phase-3 Canon Specification
    // ======================================================================
    startHeldCallWatcher() {
        const badge = document.getElementById("held-count-badge");
        const btn   = document.getElementById("btn-held-calls");

        if (!badge || !btn) {
            console.warn("[LAYOUT] Held Call button elements missing.");
            return;
        }

        const checkHeld = async () => {
            try {
                const res = await fetch("/held_count");
                const js = await res.json();
                const count = js.count || 0;

                badge.textContent = count > 0 ? count : "";

                if (count > 0) {
                    btn.classList.add("bosk-held-alert");
                } else {
                    btn.classList.remove("bosk-held-alert");
                }
            } catch (err) {
                console.error("[LAYOUT] Held watcher failed:", err);
            }
        };

        // Run once immediately + every 5 seconds
        checkHeld();
        setInterval(checkHeld, 5000);
    },

    // ======================================================================
    // TOOLBAR BEHAVIOR
    // The Held button must open panel/held using modal
    // ======================================================================
    initToolbar() {
        const btnHeld = document.getElementById("btn-held-calls");

        if (!btnHeld) {
            console.warn("[LAYOUT] Held Calls button not found.");
            return;
        }

        btnHeld.addEventListener("click", () => {
            btnHeld.classList.remove("bosk-held-alert");
            BOSK_MODAL.open("/panel/held");
        });
    },

    // ======================================================================
    // OPTIONAL: Refresh All Panels (toolbar refresh button)
    // ======================================================================
    toolbarRefresh() {
        PANELS.refreshAll();
    }
};


// ==========================================================================
// Enterprise Protection (no accidental runtime mutation)
// ==========================================================================
Object.freeze(LAYOUT);

console.log("[LAYOUT] Module loaded (Phase-3 Enterprise Edition)");

export default LAYOUT;
