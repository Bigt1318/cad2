// ============================================================================
// BOSK-CAD — PANEL REFRESH CONTROLLER
// Phase-3 Enterprise Edition
// ============================================================================
// Controls regeneration of:
//   • Active Incidents Panel
//   • Open Incidents Panel
//   • Held Incidents Panel
//   • Units Panel
//
// Integrates with:
//   • utils.js (refreshHTMX + refreshPanels)
//   • layout.js watcher (for held badge refresh)
//   • IAW action sequencing
//
// Provides:
//   • Direct reload buttons
//   • Automatic fallback refresh
//   • Hook for periodic refresh interval (optional)
//   • Enterprise-safe error handling
// ============================================================================

import { BOSK_UTIL } from "./utils.js";

export const PANELS = {

    // ------------------------------------------------------------
    // MANUAL GLOBAL REFRESH (used by toolbar refresh button)
    // ------------------------------------------------------------
    refreshAll() {
        console.log("[PANELS] Manual refresh triggered.");

        BOSK_UTIL.refreshHTMX("#panel-active", "/panel/active");
        BOSK_UTIL.refreshHTMX("#panel-open", "/panel/open");
        BOSK_UTIL.refreshHTMX("#panel-held", "/panel/held");
        BOSK_UTIL.refreshHTMX("#panel-units", "/panel/units");

        // Also refresh held-call badge watcher
        this.refreshHeldBadge();
    },

    // ------------------------------------------------------------
    // ACTIVE INCIDENTS
    // ------------------------------------------------------------
    refreshActive() {
        BOSK_UTIL.refreshHTMX("#panel-active", "/panel/active");
    },

    // ------------------------------------------------------------
    // OPEN INCIDENTS
    // ------------------------------------------------------------
    refreshOpen() {
        BOSK_UTIL.refreshHTMX("#panel-open", "/panel/open");
    },

    // ------------------------------------------------------------
    // HELD INCIDENTS
    // ------------------------------------------------------------
    refreshHeld() {
        BOSK_UTIL.refreshHTMX("#panel-held", "/panel/held");
        this.refreshHeldBadge();
    },

    // ------------------------------------------------------------
    // UNITS PANEL
    // ------------------------------------------------------------
    refreshUnits() {
        BOSK_UTIL.refreshHTMX("#panel-units", "/panel/units");
    },

    // ------------------------------------------------------------
    // REFRESH HELD BADGE (Used by layout watcher & manual refresh)
    // ------------------------------------------------------------
    async refreshHeldBadge() {
        try {
            const res = await fetch("/held_count");
            const js = await res.json();

            const badge = document.querySelector("#held-count-badge");
            const btn   = document.querySelector("#btn-held-calls");

            if (!badge || !btn) return;

            const count = js.count || 0;

            badge.textContent = count > 0 ? count : "";

            if (count > 0) {
                btn.classList.add("bosk-held-alert");
            } else {
                btn.classList.remove("bosk-held-alert");
            }

        } catch (err) {
            console.warn("[PANELS] Failed to refresh held badge.");
        }
    },

    // ------------------------------------------------------------
    // SAFETY REFRESH (Triggered when state corruption is detected)
    // ------------------------------------------------------------
    safeRefreshAll() {
        try {
            console.warn("[PANELS] Safe refresh triggered.");
            this.refreshAll();
        } catch (err) {
            console.error("[PANELS] Safe refresh failed:", err);
        }
    },

    // ------------------------------------------------------------
    // OPTIONAL: PERIODIC REFRESH LOOP
    // Disabled by default (enable if needed)
    // ------------------------------------------------------------
    enableAutoRefresh(interval_ms = 8000) {
        console.log(`[PANELS] Auto-refresh enabled (${interval_ms}ms).`);
        this._intervalHandle = setInterval(() => {
            this.refreshAll();
        }, interval_ms);
    },

    disableAutoRefresh() {
        if (this._intervalHandle) {
            clearInterval(this._intervalHandle);
            this._intervalHandle = null;
            console.log("[PANELS] Auto-refresh disabled.");
        }
    }
};

// Enterprise freeze: prevents accidental mutation of the controller
Object.freeze(PANELS);

console.log("[PANELS] Module loaded (Phase-3 Enterprise Edition)");

export default PANELS;
