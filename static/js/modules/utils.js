// ============================================================================
// FORD CAD — UTILITY ENGINE (CANONICAL)
// Phase-3 Stabilized Edition
// ============================================================================
// Purpose:
//   • Safe fetch / POST wrappers
//   • HTMX panel refresh helpers
//   • Formatting utilities
//   • Frontend-safe helper functions
//
// Explicitly Forbidden:
//   • Modal orchestration
//   • IAW reopening
//   • Workflow sequencing
//   • Routing decisions
// ============================================================================

export const BOSK_UTIL = {

    // ---------------------------------------------------------------------
    // SAFE JSON POST WRAPPER
    // ---------------------------------------------------------------------
    async postJSON(url, data = {}) {
        try {
            const res = await fetch(url, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(data)
            });

            if (!res.ok) {
                throw new Error(`POST ${url} failed (${res.status})`);
            }

            return await res.json();

        } catch (err) {
            console.error("[UTIL] POST ERROR:", url, err);
            alert("Error communicating with server.");
            throw err;
        }
    },

    // ---------------------------------------------------------------------
    // SAFE FETCH WRAPPER (HTML / TEXT)
    // ---------------------------------------------------------------------
    async safeFetch(url) {
        try {
            const res = await fetch(url);

            if (!res.ok) {
                throw new Error(`Fetch failed (${res.status}) — ${url}`);
            }

            return await res.text();

        } catch (err) {
            console.error("[UTIL] FETCH ERROR:", url, err);
            alert("Unable to load requested content.");
            throw err;
        }
    },

    // ---------------------------------------------------------------------
    // HTMX PANEL REFRESH — CANONICAL
    // ---------------------------------------------------------------------
    refreshPanels() {
        this.refreshHTMX("#panel-active", "/panel/active");
        this.refreshHTMX("#panel-open", "/panel/open");
        this.refreshHTMX("#panel-held", "/panel/held");
        this.refreshHTMX("#panel-units", "/panel/units");
    },

    // ---------------------------------------------------------------------
    // GENERIC HTMX REFRESH HELPER
    // ---------------------------------------------------------------------
    refreshHTMX(targetSelector, url) {
        const el = document.querySelector(targetSelector);
        if (!el) return;

        el.setAttribute("hx-get", url);
        el.setAttribute("hx-trigger", "load");
        el.dispatchEvent(new Event("load"));
    },

    // ---------------------------------------------------------------------
    // TIMESTAMP FORMATTER (DISPLAY ONLY)
    // ---------------------------------------------------------------------
    formatTime(ts) {
        if (!ts) return "";

        const d = new Date(ts);
        if (isNaN(d.getTime())) return ts;

        return d.toLocaleString("en-US", {
            month: "2-digit",
            day: "2-digit",
            year: "2-digit",
            hour: "2-digit",
            minute: "2-digit"
        });
    },

    // ---------------------------------------------------------------------
    // UNIT AVAILABILITY HELPER (UI ONLY)
    // ---------------------------------------------------------------------
    isUnitAvailable(statusText) {
        if (!statusText) return false;
        const s = statusText.toUpperCase().trim();
        return (s === "AVAILABLE" || s === "A" || s === "AVL");
    },

    // ---------------------------------------------------------------------
    // GLOBAL ERROR HELPER
    // ---------------------------------------------------------------------
    showError(msg) {
        alert(msg || "An unexpected error occurred.");
    },

    // ---------------------------------------------------------------------
    // LOG WRAPPER (UI DIAGNOSTICS ONLY)
    // ---------------------------------------------------------------------
    log(...args) {
        console.log("[FORD CAD]", ...args);
    }
};

// Expose for legacy modules still migrating
window.BOSK_UTIL = BOSK_UTIL;

// Freeze for safety
Object.freeze(BOSK_UTIL);

console.log("[UTIL] Module loaded (Ford CAD — Phase-3 Canonical)");
