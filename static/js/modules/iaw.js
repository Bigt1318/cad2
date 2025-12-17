// ============================================================================
// FORD CAD — INCIDENT ACTION WINDOW (IAW) ENGINE
// Phase-3 Canonical Edition
// ============================================================================
// ROLE:
//   • Translate dispatcher intent into ONE backend action
//   • Never manage state
//   • Never decide narrative vs daily log
//   • Never partially refresh fragments
//
// CONTRACT:
//   ONE action → ONE backend call → ONE IAW reopen → ONE panel refresh
// ============================================================================

import { BOSK_MODAL } from "./modal.js";
import { BOSK_UTIL } from "./utils.js";

// ---------------------------------------------------------------------------
// IAW ROOT OBJECT
// ---------------------------------------------------------------------------
export const IAW = {};


// ============================================================================
// SECTION 1 — IAW OPEN / NAVIGATION
// ============================================================================

// Open IAW for an incident
IAW.open = async function (incident_id) {
    await BOSK_MODAL.open(`/incident/${incident_id}/iaw`);
};

// Edit incident in Calltaker (read-only handoff)
IAW.editInCalltaker = function (incident_id) {
    window.location.href = `/calltaker/edit/${incident_id}`;
};


// ============================================================================
// SECTION 2 — UNIT LIFECYCLE ACTIONS (PHASE-3 CANONICAL)
// ============================================================================

// ------------------------------------------------------------
// ARRIVE UNIT
// ------------------------------------------------------------
IAW.arriveUnit = async function (incident_id, unit_id) {
    await BOSK_UTIL.postJSON(
        `/incident/${incident_id}/unit/${unit_id}/arrive`
    );
    BOSK_UTIL.refreshPanels();
    await BOSK_UTIL.reopenIAW(incident_id);
};

// ------------------------------------------------------------
// OPERATE UNIT
// ------------------------------------------------------------
IAW.operateUnit = async function (incident_id, unit_id) {
    await BOSK_UTIL.postJSON(
        `/incident/${incident_id}/unit/${unit_id}/operate`
    );
    BOSK_UTIL.refreshPanels();
    await BOSK_UTIL.reopenIAW(incident_id);
};

// ------------------------------------------------------------
// CLEAR UNIT (ACTION — NOT STATUS)
// ------------------------------------------------------------
IAW.clearUnit = async function (incident_id, unit_id) {
    await BOSK_UTIL.postJSON(
        `/incident/${incident_id}/unit/${unit_id}/clear`
    );
    BOSK_UTIL.refreshPanels();
    await BOSK_UTIL.reopenIAW(incident_id);
};

// ------------------------------------------------------------
// UNIT DISPOSITION (POST-CLEAR)
// ------------------------------------------------------------
IAW.dispositionUnit = async function (incident_id, unit_id, disposition) {
    const form = new FormData();
    form.append("disposition", disposition);

    await fetch(
        `/incident/${incident_id}/unit/${unit_id}/disposition`,
        { method: "POST", body: form }
    );

    BOSK_UTIL.refreshPanels();
    await BOSK_UTIL.reopenIAW(incident_id);
};


// ============================================================================
// SECTION 3 — INCIDENT LIFECYCLE ACTIONS
// ============================================================================

// ------------------------------------------------------------
// INCIDENT DISPOSITION (FINAL CLOSE)
// ------------------------------------------------------------
IAW.dispositionIncident = async function (incident_id, disposition) {
    const form = new FormData();
    form.append("disposition", disposition);

    await fetch(
        `/incident/${incident_id}/disposition`,
        { method: "POST", body: form }
    );

    BOSK_UTIL.refreshPanels();
    await BOSK_UTIL.reopenIAW(incident_id);
};

// ------------------------------------------------------------
// HOLD INCIDENT
// ------------------------------------------------------------
IAW.holdIncident = async function (incident_id) {
    await BOSK_UTIL.postJSON(`/incident/${incident_id}/hold`);
    BOSK_UTIL.refreshPanels();
    await BOSK_UTIL.reopenIAW(incident_id);
};

// ------------------------------------------------------------
// UNHOLD INCIDENT
// ------------------------------------------------------------
IAW.unholdIncident = async function (incident_id) {
    await BOSK_UTIL.postJSON(`/incident/${incident_id}/unhold`);
    BOSK_UTIL.refreshPanels();
    await BOSK_UTIL.reopenIAW(incident_id);
};

// ------------------------------------------------------------
// REOPEN INCIDENT
// ------------------------------------------------------------
IAW.reopenIncident = async function (incident_id) {
    await BOSK_UTIL.postJSON(`/incident/${incident_id}/reopen`);
    BOSK_UTIL.refreshPanels();
    await BOSK_UTIL.reopenIAW(incident_id);
};


// ============================================================================
// SECTION 4 — REMARKS (IAW CONTEXT)
// ============================================================================

// Add remark tied to this incident (optional unit association)
IAW.addRemark = async function (incident_id, text, unit_id = null) {
    const form = new FormData();
    form.append("text", text);
    if (unit_id) form.append("unit_id", unit_id);

    await fetch(
        `/incident/${incident_id}/remark`,
        { method: "POST", body: form }
    );

    BOSK_UTIL.refreshPanels();
    await BOSK_UTIL.reopenIAW(incident_id);
};


// ============================================================================
// SECTION 5 — ISSUE FOUND
// ============================================================================

IAW.addIssue = async function (incident_id, issue_text, followup_required = 0) {
    const form = new FormData();
    form.append("issue_text", issue_text);
    form.append("followup_required", followup_required);

    await fetch(
        `/incident/${incident_id}/issue`,
        { method: "POST", body: form }
    );

    BOSK_UTIL.refreshPanels();
    await BOSK_UTIL.reopenIAW(incident_id);
};


// ============================================================================
// SECTION 6 — DISPATCH (OUTSIDE IAW AUTHORITY)
// ============================================================================

// Dispatch picker entry point (does NOT dispatch directly)
IAW.openDispatchPicker = function (incident_id) {
    BOSK_MODAL.open(`/incident/${incident_id}/dispatch_picker`);
};


// ============================================================================
// SECTION 7 — SAFETY & EXPORT
// ============================================================================

// Prevent accidental mutation
Object.freeze(IAW);

// Expose globally for templates
window.IAW = IAW;

console.log("[IAW] Phase-3 canonical IAW module loaded.");

export default IAW;
