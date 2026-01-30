// ============================================================================
// FORD CAD — ACTION BINDINGS (INLINE → JS)
// Phase-3 Canonical
// ============================================================================

import IAW from "./iaw.js";
import { CAD_UTIL } from "./utils.js";
import { CAD_MODAL } from "./modal.js";

// Map legacy action names to canonical handlers
const ACTIONS = {
    "iaw-close": () => IAW.close(),
    "iaw-reopen": () => IAW.reopen?.(),
    "iaw-dispatch-picker": () => IAW.openDispatchPicker?.(),
    "iaw-edit-calltaker": () => IAW.editInCalltaker?.(),
    "iaw-hold": () => IAW.holdIncident?.(),
    "iaw-unhold": () => IAW.unholdIncident?.(),
    "iaw-close-incident": () => IAW.closeIncident?.(),
    "iaw-issue": () => IAW.markIssueFound?.(),

    // ------------------------------------------------------------
    // Daily Log / History actions
    // ------------------------------------------------------------
    "dailylog-open-iaw": (el) => {
        const id = (el?.dataset?.incidentId || "").trim();
        if (!id) return;
        IAW.open?.(id);
    },

    "dailylog-open-history": (el) => {
        const id = (el?.dataset?.incidentId || "").trim();
        if (!id) return;
        CAD_MODAL.open?.(`/history/${encodeURIComponent(id)}`);
    },

    "incident-reopen": async (el) => {
        const id = (el?.dataset?.incidentId || "").trim();
        if (!id) return;

        const ok = confirm(`Reopen incident ${id}? This will move it back to OPEN.`);
        if (!ok) return;

        try {
            await CAD_UTIL.postJSON("/api/incident/reopen", { incident_id: Number(id) });
            try { window.SOUNDS?.success?.(); } catch (_) {}
            CAD_UTIL.refreshPanels?.();
            IAW.open?.(id);
        } catch (err) {
            console.error("[ACTIONS] incident-reopen failed:", err);
            try { window.SOUNDS?.error?.(); } catch (_) {}
            alert(err?.message || "Unable to reopen incident.");
        }
    }
};

// Delegated click handler for data-action attributes
document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-action]");
    if (!el) return;

    // Skip context menu items - they have their own handler
    if (el.closest(".cad-context-menu") || el.closest(".cad-inline-dispo-popup")) {
        return;
    }

    const action = el.dataset.action;
    const fn = ACTIONS[action];
    if (!fn) {
        console.warn("[ACTIONS] Unknown action:", action);
        return;
    }

    e.preventDefault();
    fn(el);
});

console.log("[ACTIONS] Canonical action bindings loaded.");
