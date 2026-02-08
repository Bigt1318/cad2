// ============================================================================
// FORD CAD — INCIDENT ACTION WINDOW (IAW)
// Phase-3 Canonical Controller (freeze-safe state via closure)
// NON-MODAL DISPOSITIONS: inline expansion inside IAW (no extra overlays)
// ============================================================================

import CAD_UTIL from "./utils.js";
import { CAD_MODAL } from "./modal.js";

// ---------------------------------------------------------------------------
// Freeze-safe state (DO NOT store mutable state on a frozen object)
// ---------------------------------------------------------------------------
let _currentIncidentId = null;

// ---------------------------------------------------------------------------
// Inline UI state (module scoped, safe with Object.freeze)
// ---------------------------------------------------------------------------
let _openUnitDispoKey = null;      // `${incidentId}::${unitId}`
let _eventDispoOpenFor = null;     // incidentId or null

function _unitKey(incidentId, unitId) {
  return `${String(incidentId)}::${String(unitId)}`;
}

function _idSafe(unitId) {
  // unit ids are already safe, but guard anyway
  return String(unitId).replace(/[^a-zA-Z0-9_-]/g, "_");
}

function _closeAnyInline() {
  // Close any open unit disposition row
  if (_openUnitDispoKey) {
    const [inc, uid] = _openUnitDispoKey.split("::");
    const row = document.getElementById(`iaw-dispo-row-${inc}-${_idSafe(uid)}`);
    if (row) row.style.display = "none";
    _openUnitDispoKey = null;
  }

  // Close event disposition inline
  if (_eventDispoOpenFor) {
    const box = document.getElementById(`iaw-event-dispo-${_eventDispoOpenFor}`);
    if (box) box.style.display = "none";
    _eventDispoOpenFor = null;
  }
}

function _setSelected(btn, groupSelector) {
  document.querySelectorAll(groupSelector).forEach(b => b.classList.remove("selected"));
  btn.classList.add("selected");
}

function _getUnitDispoRow(incidentId, unitId) {
  return document.getElementById(`iaw-dispo-row-${String(incidentId)}-${_idSafe(unitId)}`);
}

function _getUnitSelectedCode(incidentId, unitId) {
  const row = _getUnitDispoRow(incidentId, unitId);
  if (!row) return null;
  return row.dataset.selectedCode || null;
}

function _setUnitSelectedCode(incidentId, unitId, code) {
  const row = _getUnitDispoRow(incidentId, unitId);
  if (!row) return;
  row.dataset.selectedCode = code || "";
  const submitBtn = row.querySelector(`[data-role="submit-unit-clear"]`);
  if (submitBtn) submitBtn.disabled = !code;
}

function _getUnitRemark(incidentId, unitId) {
  const row = _getUnitDispoRow(incidentId, unitId);
  if (!row) return "";
  const el = row.querySelector(`[data-role="unit-dispo-remark"]`);
  return (el?.value || "").trim();
}

function _disableUnitRowControls(incidentId, unitId, disabled) {
  const row = _getUnitDispoRow(incidentId, unitId);
  if (!row) return;
  row.querySelectorAll("button, input, textarea, select").forEach(el => {
    el.disabled = !!disabled;
  });
}

const IAW = {

  // ---------------------------------------------------------------------
  // STATE
  // ---------------------------------------------------------------------
  getCurrentIncidentId() {
    return _currentIncidentId;
  },

  // ---------------------------------------------------------------------
  // OPEN / CLOSE
  // ---------------------------------------------------------------------
  async open(incidentId) {
    if (!incidentId) return;

    _currentIncidentId = String(incidentId);

    await CAD_MODAL.open(
      `/incident_action_window/${_currentIncidentId}`,
      { modalClass: "iaw-modal" }
    );
  },

  close() {
    _currentIncidentId = null;
    _openUnitDispoKey = null;
    _eventDispoOpenFor = null;
    CAD_MODAL.close();
  },

  reopen() {
    if (!_currentIncidentId) return;
    this.open(_currentIncidentId);
  },

  async assignNumber(incident_id) {
    if (!incident_id) return;

    try {
      const res = await CAD_UTIL.postJSON(`/api/incident/assign_number/${encodeURIComponent(incident_id)}`, {});
      if (!res?.ok) {
        alert(res?.error || "Unable to assign incident number.");
        return;
      }

      // Refresh panels + reopen modal so header updates
      CAD_UTIL.emitIncidentUpdated?.();
      this.open(incident_id);

    } catch (err) {
      console.error("[IAW] assignNumber failed:", err);
      alert("Unable to assign incident number.");
    }
  },


  // ---------------------------------------------------------------------
  // DISPATCH / CALLTAKER
  // ---------------------------------------------------------------------
  openDispatchPicker() {
    if (!_currentIncidentId) return;

    CAD_MODAL.open(
      `/api/dispatch_picker/refresh/${_currentIncidentId}`,
      { modalClass: "dispatch-picker-modal" }
    );
  },

  editInCalltaker() {
    if (!_currentIncidentId) return;

    CAD_MODAL.open(
      `/calltaker/edit/${_currentIncidentId}`,
      { modalClass: "calltaker-edit-modal" }
    );
  },

  // ---------------------------------------------------------------------
  // UNIT STATUS (Direct, no UAW dependency)
  // Backend: POST /incident/{incident_id}/unit/{unit_id}/status {status:"..."}
  // ---------------------------------------------------------------------
  async setUnitStatus(incident_id, unit_id, status) {
    if (!incident_id || !unit_id || !status) return;

    _closeAnyInline();

    await CAD_UTIL.postJSON(
      `/incident/${encodeURIComponent(incident_id)}/unit/${encodeURIComponent(unit_id)}/status`,
      { status: String(status).toUpperCase() }
    );

    // Play appropriate sound based on status and show toast
    try {
      const st = String(status).toUpperCase();
      if (st === "ARRIVED") {
        window.SOUNDS?.unitArrived?.();
        window.TOAST?.info?.(`${unit_id} arrived on scene`);
      } else if (st === "DISPATCHED" || st === "ENROUTE") {
        window.SOUNDS?.unitDispatched?.();
        window.TOAST?.info?.(`${unit_id} ${st.toLowerCase()}`);
      } else {
        window.SOUNDS?.notify?.();
        window.TOAST?.info?.(`${unit_id} status: ${st}`);
      }
    } catch (_) {}

    CAD_UTIL.refreshPanels();
    this.reopen();
  },

  enrouteUnit(incident_id, unit_id) {
    return this.setUnitStatus(incident_id, unit_id, "ENROUTE");
  },

  arriveUnit(incident_id, unit_id) {
    // Canonical: ARRIVED == ON SCENE
    return this.setUnitStatus(incident_id, unit_id, "ARRIVED");
  },

  transportUnit(incident_id, unit_id) {
    return this.setUnitStatus(incident_id, unit_id, "TRANSPORTING");
  },

  atMedicalUnit(incident_id, unit_id) {
    return this.setUnitStatus(incident_id, unit_id, "AT_MEDICAL");
  },

  // ---------------------------------------------------------------------
  // INLINE DISPOSITION UI (Option B)
  // Clear -> show inline disposition -> submit -> disposition save -> clear
  // Backend:
  //   POST /incident/{id}/unit/{unit}/disposition {disposition:"R", remark:"..."}
  //   POST /api/uaw/clear_unit                    {incident_id, unit_id, disposition, comment}
  // NOTE: backend currently ignores remark; we still send it for forward-compat.
  // ---------------------------------------------------------------------
  ui: {

    toggleUnitDisposition(incident_id, unit_id) {
      if (!incident_id || !unit_id) return;

      const key = _unitKey(incident_id, unit_id);
      const row = _getUnitDispoRow(incident_id, unit_id);
      if (!row) return;

      // If clicking the same one, toggle closed
      if (_openUnitDispoKey === key) {
        row.style.display = "none";
        _openUnitDispoKey = null;
        return;
      }

      // Close anything else, open this
      _closeAnyInline();
      row.style.display = "block";
      _openUnitDispoKey = key;

      // Reset selection state when opening
      row.dataset.selectedCode = row.dataset.selectedCode || "";
      const submitBtn = row.querySelector(`[data-role="submit-unit-clear"]`);
      if (submitBtn) submitBtn.disabled = !row.dataset.selectedCode;

      // Focus remark
      const remark = row.querySelector(`[data-role="unit-dispo-remark"]`);
      if (remark) remark.focus();
    },

    selectUnitDisposition(incident_id, unit_id, code, btnEl) {
      if (!incident_id || !unit_id || !code) return;

      // Visual highlight within this unit row only
      const row = _getUnitDispoRow(incident_id, unit_id);
      if (!row) return;

      // Clear previous selection styling inside this row
      row.querySelectorAll(".iaw-dispo-code-btn").forEach(b => b.classList.remove("selected"));
      if (btnEl) btnEl.classList.add("selected");

      _setUnitSelectedCode(incident_id, unit_id, String(code).toUpperCase());
    },

    async submitUnitClear(incident_id, unit_id) {
      if (!incident_id || !unit_id) return;

      const row = _getUnitDispoRow(incident_id, unit_id);
      if (!row) return;

      const code = _getUnitSelectedCode(incident_id, unit_id);
      if (!code) return; // Submit disabled anyway (Option 1)

      const remark = _getUnitRemark(incident_id, unit_id);
      const alreadyCleared = (row.dataset.alreadyCleared === "1");

      _disableUnitRowControls(incident_id, unit_id, true);

      try {
        // If already cleared, this is a disposition-only edit.
        // If not cleared yet, clearing is a single canonical operation:
        //   • requires disposition for command unit / last clearing unit
        //   • records UnitAssignments.cleared + disposition + remark
        //   • returns unit to AVAILABLE in UnitStatus
        let res = null;

        if (alreadyCleared) {
          await CAD_UTIL.postJSON(
            `/incident/${encodeURIComponent(incident_id)}/unit/${encodeURIComponent(unit_id)}/disposition`,
            { disposition: code, remark }
          );
        } else {
          res = await CAD_UTIL.postJSON(
            `/api/uaw/clear_unit`,
            {
              incident_id: Number(incident_id),
              unit_id: String(unit_id),
              disposition: String(code),
              comment: String(remark || "")
            }
          );
        }

        // Close inline UI, refresh, reopen IAW
        row.style.display = "none";
        _openUnitDispoKey = null;

        CAD_UTIL.refreshPanels();
        IAW.reopen();

        // If the backend indicates the incident now requires Event Disposition,
        // force the inline Event Dispo box open (do not toggle closed).
        const needsEvent = !!(
          res?.requires_event_disposition ||
          res?.last_unit_cleared ||
          res?.requires_disposition
        );
        if (needsEvent) {
          try {
            if (_eventDispoOpenFor !== String(incident_id)) {
              IAW.ui.toggleEventDisposition(incident_id);
            }
          } catch (_) {}
        }
      } catch (err) {
        console.error("[IAW] submitUnitClear failed:", err);
        alert("Disposition/Clear failed. See console.");
        _disableUnitRowControls(incident_id, unit_id, false);
      }
    },

    cancelUnitDisposition(incident_id, unit_id) {
      const row = _getUnitDispoRow(incident_id, unit_id);
      if (!row) return;
      row.style.display = "none";
      _openUnitDispoKey = null;
    },

    unitRemarkKeydown(ev, incident_id, unit_id) {
      if (ev.key !== "Enter") return;
      // Enter submits only if a code selected
      ev.preventDefault();
      const code = _getUnitSelectedCode(incident_id, unit_id);
      if (!code) return;
      IAW.ui.submitUnitClear(incident_id, unit_id);
    },

    // -----------------------------------------------------------------
    // EVENT DISPOSITION INLINE (no modal)
    // Backend: POST /incident/{id}/disposition {code:"MT", comment:"..."}
    // -----------------------------------------------------------------
    toggleEventDisposition(incident_id) {
      if (!incident_id) return;

      const box = document.getElementById(`iaw-event-dispo-${String(incident_id)}`);
      if (!box) return;

      // If open, close
      if (_eventDispoOpenFor === String(incident_id)) {
        box.style.display = "none";
        _eventDispoOpenFor = null;
        return;
      }

      // Close other inline sections and open this
      _closeAnyInline();
      box.style.display = "block";
      _eventDispoOpenFor = String(incident_id);

      // Disable submit until selection
      const codeSel = box.querySelector(`[data-role="event-dispo-code"]`);
      const submit = box.querySelector(`[data-role="submit-event-dispo"]`);
      if (submit) submit.disabled = !(codeSel?.value);

      // Focus comment
      const comment = box.querySelector(`[data-role="event-dispo-comment"]`);
      if (comment) comment.focus();
    },

    eventCodeChanged(incident_id) {
      const box = document.getElementById(`iaw-event-dispo-${String(incident_id)}`);
      if (!box) return;
      const codeSel = box.querySelector(`[data-role="event-dispo-code"]`);
      const submit = box.querySelector(`[data-role="submit-event-dispo"]`);
      if (submit) submit.disabled = !(codeSel?.value);
    },

    async submitEventDisposition(incident_id) {
      if (!incident_id) return;

      const box = document.getElementById(`iaw-event-dispo-${String(incident_id)}`);
      if (!box) return;

      const code = (box.querySelector(`[data-role="event-dispo-code"]`)?.value || "").trim();
      const comment = (box.querySelector(`[data-role="event-dispo-comment"]`)?.value || "").trim();

      if (!code) return;

      // Lock controls while posting
      box.querySelectorAll("button, input, textarea, select").forEach(el => el.disabled = true);

      try {
        const res = await CAD_UTIL.postJSON(`/incident/${encodeURIComponent(incident_id)}/disposition`, {
          code,
          comment
        });

        box.style.display = "none";
        _eventDispoOpenFor = null;

        CAD_UTIL.refreshPanels();

        // Check the result status
        if (res?.status === "CLOSED" || res?.status === "HELD") {
          // Incident is fully closed/held - close the modal entirely
          IAW.close();
          window.TOAST?.success?.(`Incident closed with disposition: ${code}`);
        } else if (res?.remaining_units > 0) {
          // Units still assigned - show message and close the dispo panel but keep IAW open
          window.TOAST?.warning?.(`Disposition saved. ${res.remaining_units} unit(s) still assigned.`);
          // Don't reopen IAW - keep it open as-is, just hide the dispo panel
        } else {
          // Fallback: reopen IAW
          IAW.reopen();
        }
      } catch (err) {
        console.error("[IAW] submitEventDisposition failed:", err);
        alert("Event disposition failed. See console.");
        box.querySelectorAll("button, input, textarea, select").forEach(el => el.disabled = false);
      }
    },

    cancelEventDisposition(incident_id) {
      const box = document.getElementById(`iaw-event-dispo-${String(incident_id)}`);
      if (!box) return;
      box.style.display = "none";
      _eventDispoOpenFor = null;
    },

    // Button grid selection for event disposition
    selectDispoCode(incident_id, code, btnEl) {
      if (!incident_id || !code) return;

      const box = document.getElementById(`iaw-event-dispo-${String(incident_id)}`);
      if (!box) return;

      // Remove selection from all buttons in this panel
      box.querySelectorAll('.iaw-dispo-code-btn').forEach(b => b.classList.remove('selected'));

      // Add selection to clicked button
      if (btnEl) btnEl.classList.add('selected');

      // Set hidden input value
      const codeInput = box.querySelector('[data-role="event-dispo-code"]');
      if (codeInput) codeInput.value = code;

      // Enable submit button
      const submitBtn = box.querySelector('[data-role="submit-event-dispo"]');
      if (submitBtn) submitBtn.disabled = false;
    }
  },

  // ---------------------------------------------------------------------
  // HOLD / UNHOLD
  // ---------------------------------------------------------------------
  // ---------------------------------------------------------------------
  // HOLD / UNHOLD
  // ---------------------------------------------------------------------
  async holdIncident() {
    if (!_currentIncidentId) return;

    // Canon: held incidents require a free-text reason
    const reason = (prompt("Hold reason (required):", "") || "").trim();
    if (!reason) return;

    if (!CAD_UTIL.confirm(`Place this incident on HOLD?\n\nReason: ${reason}`)) return;

    try {
      await CAD_UTIL.postJSON(`/incident/${_currentIncidentId}/hold`, { reason });
      CAD_UTIL.refreshPanels();
      this.reopen();
    } catch (err) {
      console.error("[IAW] holdIncident failed:", err);
      alert(err?.message || String(err));
    }
  },

  async unholdIncident() {
    if (!_currentIncidentId) return;

    await CAD_UTIL.postJSON(`/incident/${_currentIncidentId}/unhold`, {});
    CAD_UTIL.refreshPanels();
    this.reopen();

    // Hardening: if a modal reopen cancels an in-flight panel swap, run refresh again.
    setTimeout(() => CAD_UTIL.refreshPanels(), 75);
  },



  // ---------------------------------------------------------------------
  // REOPEN / ISSUE FOUND
  // ---------------------------------------------------------------------
  async reopenIncident(incidentId) {
    const id = incidentId || _currentIncidentId;
    if (!id) return;

    const reason = (prompt("Reason for reopening (optional):") || "").trim();
    const location = (prompt("Update location? (leave blank to keep current):") || "").trim();
    const type = (prompt("Update incident type? (leave blank to keep current):") || "").trim();

    try {
      await CAD_UTIL.postJSON("/api/incident/reopen", {
        incident_id: Number(id),
        reason,
        location: location || undefined,
        type: type || undefined,
      });
      CAD_UTIL.refreshPanels();
      window.TOAST?.success?.(`Incident ${id} reopened`);
      this.reopen();
    } catch (err) {
      window.TOAST?.error?.(err?.message || "Reopen failed");
    }
  },

  async markIssueFound() {
    if (!_currentIncidentId) return;

    await CAD_UTIL.postJSON(`/incident/${_currentIncidentId}/issue`, {});
    CAD_UTIL.refreshPanels();
    this.reopen();
  },

  // ---------------------------------------------------------------------
  // ADD NOTE (works for open OR closed incidents)
  // ---------------------------------------------------------------------
  async addNote(incidentId) {
    const id = incidentId || _currentIncidentId;
    if (!id) return;

    const textarea = document.getElementById(`iaw-note-text-${id}`);
    const text = (textarea?.value || "").trim();

    if (!text) {
      textarea?.focus();
      return;
    }

    try {
      await CAD_UTIL.postJSON("/remark", {
        incident_id: Number(id),
        text: text
      });

      // Clear the textarea
      if (textarea) textarea.value = "";

      // Show success feedback
      window.TOAST?.success?.("Note added");

      // Refresh and reopen to show updated narrative
      CAD_UTIL.refreshPanels();
      this.reopen();
    } catch (err) {
      console.error("[IAW] addNote failed:", err);
      window.TOAST?.error?.("Failed to add note");
    }
  },

  /**
   * Open the determinant code picker modal
   */
  async openDeterminantPicker(incidentId) {
    try {
      const html = await CAD_UTIL.safeFetch(`/incident/${incidentId}/determinant_picker`);
      if (html) {
        CAD_MODAL.openRaw(html);
      }
    } catch (err) {
      console.error("[IAW] openDeterminantPicker failed:", err);
      window.TOAST?.error?.("Determinant picker not available");
    }
  }
};

window.IAW = IAW;
Object.freeze(IAW);


export default IAW;
