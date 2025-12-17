// ============================================================================
// FORD CAD — GLOBAL MODAL ENGINE (CANONICAL)
// Phase-3 Stabilized Edition
// ============================================================================
// Purpose:
//   • Open and close overlay modals
//   • Fetch modal HTML from backend routes
//   • Inject optional context data into modal DOM
//   • Enforce SINGLE active modal at all times
//   • Lock background scroll while active
//
// Explicitly Forbidden:
//   • Workflow orchestration
//   • Backend routing decisions
//   • Modal stacking
//   • Reopening logic
// ============================================================================

import { BOSK_UTIL } from "./utils.js";

export const BOSK_MODAL = {

    container: null,
    active: false,

    // ---------------------------------------------------------------------
    // INITIALIZE MODAL ROOT (called once by bootloader)
    // ---------------------------------------------------------------------
    init() {
        if (this.container) return;

        this.container = document.createElement("div");
        this.container.id = "fordcad-modal-container";
        document.body.appendChild(this.container);

        // ESC key closes active modal
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape" && this.active) {
                this.close();
            }
        });

        console.log("[MODAL] Engine initialized (Ford CAD)");
    },

    // ---------------------------------------------------------------------
    // OPEN MODAL
    // url     → backend route returning modal HTML
    // context → optional object injected into modal dataset
    // ---------------------------------------------------------------------
    async open(url, context = null) {
        try {
            // Always hard-close any existing modal
            this.close(true);

            this.active = true;

            // Fetch modal HTML
            const html = await BOSK_UTIL.safeFetch(url);

            // Inject modal HTML
            this.container.innerHTML = html;

            const modal = this.container.querySelector(".bosk-modal");
            const overlay = this.container.querySelector(".bosk-modal-overlay");

            if (!modal || !overlay) {
                throw new Error("Modal HTML missing required root elements.");
            }

            // Inject context data as data-* attributes
            if (context && typeof context === "object") {
                Object.entries(context).forEach(([key, value]) => {
                    if (value !== undefined && value !== null) {
                        modal.dataset[key] = value;
                    }
                });
            }

            // Animate in
            modal.classList.add("modal-fade-in");
            this._lockScroll(true);

        } catch (err) {
            console.error("[MODAL] Open failed:", err);
            alert("Unable to load modal.");
            this._clear();
        }
    },

    // ---------------------------------------------------------------------
    // CLOSE MODAL
    // instant = true → no animation (used before reopening)
    // ---------------------------------------------------------------------
    close(instant = false) {
        if (!this.active) return;

        const modal = this.container.querySelector(".bosk-modal");

        if (instant || !modal) {
            this._clear();
            return;
        }

        modal.classList.remove("modal-fade-in");
        modal.classList.add("modal-fade-out");

        setTimeout(() => this._clear(), 250);
    },

    // ---------------------------------------------------------------------
    // INTERNAL — CLEAR MODAL CONTENT
    // ---------------------------------------------------------------------
    _clear() {
        this.container.innerHTML = "";
        this.active = false;
        this._lockScroll(false);
    },

    // ---------------------------------------------------------------------
    // LOCK / UNLOCK BACKGROUND SCROLL
    // ---------------------------------------------------------------------
    _lockScroll(state) {
        document.body.style.overflow = state ? "hidden" : "";
    }
};

// Freeze for runtime safety
Object.freeze(BOSK_MODAL);

console.log("[MODAL] Module loaded (Ford CAD — Phase-3 Canonical)");

export default BOSK_MODAL;
