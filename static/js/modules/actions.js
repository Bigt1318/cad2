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
        // Close current modal first, then open IAW
        CAD_MODAL.close?.();
        setTimeout(() => {
            IAW.open?.(id);
        }, 100);
    },

    "dailylog-open-history": (el) => {
        const id = (el?.dataset?.incidentId || "").trim();
        if (!id) return;
        // Close current modal first, then open history
        CAD_MODAL.close?.();
        setTimeout(() => {
            CAD_MODAL.open?.(`/history/${encodeURIComponent(id)}`);
        }, 100);
    },

    // ------------------------------------------------------------
    // Messaging actions
    // ------------------------------------------------------------
    "chat-toggle-drawer": () => {
        window.MessagingUI?.toggleDrawer?.();
    },

    "chat-open-dm": (el) => {
        const unitId = (el?.dataset?.unitId || "").trim();
        if (unitId && window.MessagingUI?.openDM) {
            window.MessagingUI.openDM(unitId);
        }
    },

    "chat-open-channel": (el) => {
        const channelId = (el?.dataset?.channelId || "").trim();
        if (channelId && window.MessagingUI?.openChannel) {
            window.MessagingUI.openChannel(channelId);
        }
    },

    "chat-open-broadcast": () => {
        window.MessagingUI?.openBroadcast?.();
    },

    "chat-ack-message": (el) => {
        const msgId = (el?.dataset?.messageId || "").trim();
        if (msgId && window.MessagingUI?.ackMessage) {
            window.MessagingUI.ackMessage(msgId);
        }
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

    // Stop propagation to prevent modal close or other handlers interfering
    e.preventDefault();
    e.stopPropagation();

    fn(el);
});

