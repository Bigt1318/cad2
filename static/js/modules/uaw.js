// ============================================================================
// FORD CAD — UNIT ACTION WINDOW (UAW)
// Phase-3 Canonical Edition
// ============================================================================
// ROLE:
//   • Provide unit-scoped entry points
//   • Forward operational intent to canonical IAW endpoints
//   • Never manage incident state directly
//   • Never perform partial refreshes
//
// CONTRACT:
//   ONE action → ONE backend call → ONE IAW reopen → ONE panel refresh
// ============================================================================

import { CAD_MODAL } from "./modal.js";
import { CAD_UTIL } from "./utils.js";

export const UAW = {};


// ============================================================================
// SECTION 1 — OPEN / NAVIGATION
// ============================================================================

// Open UAW for a unit
UAW.open = function (unit_id) {
    CAD_MODAL.open(`/unit/${unit_id}/uaw`);
};


// ============================================================================
// SECTION 2 — INCIDENT CONTEXT HANDOFF
// ============================================================================

// View the incident this unit is currently assigned to
UAW.viewIncident = async function (incident_id) {
    await CAD_MODAL.open(`/incident/${incident_id}/iaw`);
};


// ============================================================================
// SECTION 3 — UNIT LIFECYCLE (FORWARDED TO IAW ENDPOINTS)
// ============================================================================

// ARRIVE
UAW.arriveUnit = async function (incident_id, unit_id) {
    await CAD_UTIL.postJSON(
        `/incident/${incident_id}/unit/${unit_id}/arrive`
    );
    CAD_UTIL.refreshPanels();
    await CAD_UTIL.reopenIAW(incident_id);
};

// OPERATE
UAW.operateUnit = async function (incident_id, unit_id) {
    await CAD_UTIL.postJSON(
        `/incident/${incident_id}/unit/${unit_id}/operate`
    );
    CAD_UTIL.refreshPanels();
    await CAD_UTIL.reopenIAW(incident_id);
};

// CLEAR (ACTION — NOT STATUS)
UAW.clearUnit = async function (incident_id, unit_id) {
    await CAD_UTIL.postJSON(
        `/incident/${incident_id}/unit/${unit_id}/clear`
    );
    CAD_UTIL.refreshPanels();
    await CAD_UTIL.reopenIAW(incident_id);
};


// ============================================================================
// SECTION 4 — UNIT DISPOSITION (POST-CLEAR)
// ============================================================================

UAW.dispositionUnit = async function (incident_id, unit_id, disposition) {
    const form = new FormData();
    form.append("disposition", disposition);

    await fetch(
        `/incident/${incident_id}/unit/${unit_id}/disposition`,
        { method: "POST", body: form }
    );

    CAD_UTIL.refreshPanels();
    await CAD_UTIL.reopenIAW(incident_id);
};


// ============================================================================
// SECTION 5 — REMARKS (UNIT CONTEXT)
// ============================================================================

// Open remark modal with unit preselected
UAW.addRemark = function (incident_id, unit_id) {
    CAD_MODAL.open(
        `/incident/${incident_id}/remark?unit_id=${unit_id}`
    );
};


// ============================================================================
// SECTION 6 — SAFETY & EXPORT
// ============================================================================

// Freeze to prevent mutation
Object.freeze(UAW);

// Expose globally for templates
window.UAW = UAW;


export default UAW;
