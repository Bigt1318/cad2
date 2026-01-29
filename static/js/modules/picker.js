/* ============================================================================
   FORD CAD — DISPATCH PICKER ENGINE
   Phase-3 Stabilized (Option A — UI Retained, Canonical Dispatch Wiring Restored)
===============================================================================
Responsibilities:
  • Capture dispatcher intent
  • Allow unit selection (apparatus + crew)
  • Provide visual feedback
  • Submit ONE canonical dispatch request
  • Close picker, refresh panels, and reopen IAW (if applicable)

Explicitly NOT responsible for:
  • Deep availability validation logic (backend owns truth)
  • Writing narrative directly (backend owns logging)
  • Managing incident lifecycle beyond dispatch
============================================================================ */

import { CAD_MODAL } from "./modal.js";
import { CAD_UTIL } from "./utils.js";

export const PICKER = {

    /* ============================================================
       INTERNAL UI STATE
       ============================================================ */
    selected: new Set(),
    apparatusCrewMap: {},     // { "Engine2": ["21","22"] }
    crewParent: {},
    mutualAidVisible: false,

    /* ============================================================
       DRAG HANDLE SUPPORT (templates call PICKER.startDrag)
       ============================================================ */
    startDrag(event) {
        // Uses the canonical drag engine if it is globally exposed.
        window.CAD_DRAG?.startDrag?.(event);
    },

    /* ============================================================
       INIT — called after picker modal loads
       ============================================================ */
    init() {
        console.log("[PICKER] Initialized (Ford CAD / Phase-3)");

        this.selected.clear();
        this.apparatusCrewMap = {};
        this.crewParent = {};
        this.mutualAidVisible = false;

        // Build apparatus → crew mappings
        document.querySelectorAll(".dp-row.apparatus").forEach(app => {
            const appId = app.dataset.unit;
            const crew = [];

            document
                .querySelectorAll(`.dp-row.crew[data-parent='${appId}']`)
                .forEach(c => {
                    crew.push(c.dataset.unit);
                    this.crewParent[c.dataset.unit] = appId;
                });

            this.apparatusCrewMap[appId] = crew;
        });

        // Mutual aid collapse toggle
        const header = document.getElementById("mutual-aid-header");
        if (header) {
            header.addEventListener("click", () => this.toggleMutualAid());
        }

        this.applyMutualAidVisibility();
    },

    /* ============================================================
       MUTUAL AID COLLAPSE
       ============================================================ */
    toggleMutualAid() {
        this.mutualAidVisible = !this.mutualAidVisible;
        this.applyMutualAidVisibility();
    },

    applyMutualAidVisibility() {
        document.querySelectorAll(".dp-mutual-row")
            .forEach(r => {
                r.style.display = this.mutualAidVisible ? "flex" : "none";
            });

        const hdr = document.getElementById("mutual-aid-header");
        if (hdr) {
            const arrow = hdr.querySelector(".ma-arrow");
            if (arrow) arrow.innerText = this.mutualAidVisible ? "▼" : "►";
        }
    },

    /* ============================================================
       SELECTION VISUALS
       ============================================================ */
    markSelected(id, on) {
        document
            .querySelectorAll(`.dp-row[data-unit='${id}']`)
            .forEach(r => r.classList.toggle("selected", on));
    },

    /* ============================================================
       UNIT TOGGLES (INTENT ONLY — NO VALIDATION)
       ============================================================ */
    toggleUnit(id) {
        if (this.selected.has(id)) {
            this.selected.delete(id);
            this.markSelected(id, false);
        } else {
            this.selected.add(id);
            this.markSelected(id, true);
        }
    },

    toggleApparatus(appId) {
        const crew = this.apparatusCrewMap[appId] || [];
        const selecting = !this.selected.has(appId);

        this.markSelected(appId, selecting);
        selecting ? this.selected.add(appId) : this.selected.delete(appId);

        crew.forEach(c => {
            selecting ? this.selected.add(c) : this.selected.delete(c);
            this.markSelected(c, selecting);
        });
    },

    toggleCrew(appId, crewId) {
        const selecting = !this.selected.has(crewId);

        this.markSelected(crewId, selecting);
        selecting ? this.selected.add(crewId) : this.selected.delete(crewId);

        if (selecting) {
            this.selected.add(appId);
            this.markSelected(appId, true);
        }
    },

    /* ============================================================
       ONE-CLICK DISPATCH (templates call PICKER.dispatchUnit)
       ============================================================ */
    async dispatchUnit(unit_id, incident_id) {
        if (!incident_id) {
            alert("No incident selected.");
            return;
        }
        if (!unit_id) {
            alert("No unit selected.");
            return;
        }

        try {
            const res = await CAD_UTIL.postJSON("/dispatch/unit_to_incident", {
                incident_id,
                units: [unit_id]
            });

            if (res?.ok === false) {
                alert(res?.error || "Dispatch rejected by backend.");
                return;
            }

            CAD_MODAL.close();
            CAD_UTIL.refreshPanels();
            await CAD_UTIL.reopenIAW(incident_id);

        } catch (err) {
            console.error("[PICKER] Dispatch failed:", err);
            alert(err?.message || "Dispatch failed.");
        }
    },

    /* ============================================================
       SUBMIT DISPATCH — MULTI SELECT
       ============================================================ */
    async submitSelection(incident_id) {

        if (!incident_id) {
            alert("No incident selected.");
            return;
        }

        if (this.selected.size === 0) {
            alert("No units selected for dispatch.");
            return;
        }

        const units = Array.from(this.selected);

        try {
            const res = await CAD_UTIL.postJSON("/dispatch/unit_to_incident", {
                incident_id,
                units
            });

            if (res?.ok === false) {
                alert(res?.error || "Dispatch rejected by backend.");
                return;
            }

            CAD_MODAL.close();
            CAD_UTIL.refreshPanels();
            await CAD_UTIL.reopenIAW(incident_id);

        } catch (err) {
            console.error("[PICKER] Dispatch failed:", err);
            alert(err?.message || "Dispatch failed.");
        }
    }
};

/* ============================================================
   GLOBAL EXPOSURE — REQUIRED FOR onclick=""
   ============================================================ */
Object.freeze(PICKER);
window.PICKER = PICKER;

/* ============================================================
   HARD GUARD — if something overwrites window.PICKER later,
   put it back (this prevents "dispatchUnit is not a function")
   ============================================================ */
setTimeout(() => {
    if (!window.PICKER || typeof window.PICKER.dispatchUnit !== "function") {
        window.PICKER = PICKER;
        console.warn("[PICKER] window.PICKER was missing/overwritten — restored.");
    }
}, 0);

console.log("[PICKER] Module loaded (Ford CAD — Phase-3 Option A) :: v2026-01-06-A");

export default PICKER;
