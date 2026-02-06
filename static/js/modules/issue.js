// ============================================================================
// FORD-CAD — ISSUE FOUND (DAILY LOG ONLY)
// Phase-3 Canonical
// ============================================================================
// Responsibilities:
//   • Open Issue Found modal for an incident
//   • Submit Issue Found payload to /api/* (JSON only)
//   • Close modal + refresh panels + reopen IAW
//
// Notes:
//   • Issue Found is valid for DAILY/DAILY LOG type incidents only.
//   • Backend enforces rules and sets incident.issue_flag.
// ============================================================================

import { CAD_MODAL } from "./modal.js";
import { CAD_UTIL } from "./utils.js";

export const ISSUE = {
  startDrag(e) {
    if (window.CAD_DRAG?.startDrag) window.CAD_DRAG.startDrag(e);
  },

  open(incidentId) {
    const id = Number(incidentId);
    if (!id) return;
    CAD_MODAL.open(`/incident/${encodeURIComponent(id)}/issue`);
  },

  async submitIssue() {
    const inc = Number((document.getElementById("issue-incident-id")?.value || "").trim());
    if (!inc) {
      alert("Missing incident id.");
      return;
    }

    const title = (document.getElementById("issue-title")?.value || "").trim();
    const description = (document.getElementById("issue-description")?.value || "").trim();
    const action_taken = (document.getElementById("issue-action")?.value || "").trim();
    const followup_required = !!document.getElementById("issue-followup-required")?.checked;
    const followup = (document.getElementById("issue-followup-notes")?.value || "").trim();
    const severity = (document.getElementById("issue-severity")?.value || "MEDIUM").trim();
    const location = (document.getElementById("issue-location")?.value || "").trim();

    if (!title) {
      alert("Issue title is required.");
      return;
    }

    try {
      const payload = {
        title,
        description,
        action_taken,
        followup_required,
        followup,
        severity,
        location,
      };

      const res = await CAD_UTIL.postJSON(`/api/incident/${encodeURIComponent(inc)}/issue_found`, payload);

      if (!res?.ok) {
        alert(res?.error || "Unable to save Issue Found.");
        return;
      }

      CAD_MODAL.close();

      // Refresh panels + reopen IAW for immediate confirmation
      CAD_UTIL.refreshPanels({ incident_id: inc, reason: "issue_found" });
      CAD_UTIL.reopenIAW(inc);

    } catch (err) {
      console.error("[ISSUE] submitIssue failed:", err);
      alert("Unable to save Issue Found.");
    }
  },
};

window.ISSUE = ISSUE;
Object.freeze(ISSUE);


export default ISSUE;
