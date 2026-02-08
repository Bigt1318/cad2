// ============================================================================
// FORD CAD — CALLTAKER MODULE (CANONICAL)
// Phase-3 • Keyboard-Polished • Safe Scoped Handling
// ============================================================================

import { CAD_UTIL } from "./utils.js";

let CURRENT_INCIDENT_ID = null;
let EL = {};
let FORM_UNLOCKED = false;
let _KEYDOWN_BOUND = false;

export const CALLTAKER = {
    // ---------------------------------------------------------------------
    // TYPE CHANGE (INLINE HANDLER SUPPORT)
    // ---------------------------------------------------------------------
    onTypeChange() {
        // Alias to canonical rules engine (supports HTML onchange="CALLTAKER.onTypeChange()")
        this.applyTypeRules();
    },

    // ---------------------------------------------------------------------
    // INIT
    // ---------------------------------------------------------------------
    init() {

        this.cacheFields();
        this.lockForm();

        // Type-driven UI rules (DAILY LOG subtype row)
        if (EL.type) {
            EL.type.addEventListener("change", () => this.applyTypeRules());
        }

        // Apply once on first paint so subtype row state is correct even before editing
        this.applyTypeRules();

        // Bind key handler once (avoids duplicate listeners on HTMX/rehydrate)
        if (!_KEYDOWN_BOUND) {
            _KEYDOWN_BOUND = true;

            document.addEventListener("keydown", (e) => {
                // Only react when Calltaker panel exists AND the focus is inside it
                const panel = document.getElementById("panel-calltaker");
                if (!panel) return;

                const active = document.activeElement;
                if (!active || !panel.contains(active)) return;

                // Ignore if form is locked and no draft exists
                if (!FORM_UNLOCKED && !CURRENT_INCIDENT_ID) return;

                // ESC = Cancel ONLY when editing
                if (e.key === "Escape") {
                    if (!CURRENT_INCIDENT_ID) return;
                    e.preventDefault();
                    CALLTAKER.cancelIncident();
                    return;
                }

                // ENTER behavior
                if (e.key === "Enter") {
                    // Allow multiline typing in textarea unless Ctrl+Enter
                    if (active.tagName === "TEXTAREA" && !e.ctrlKey) return;

                    // Only save if form is unlocked
                    if (!FORM_UNLOCKED) return;

                    e.preventDefault();
                    CALLTAKER.saveIncident();
                }
            });
        }

    },

    // ---------------------------------------------------------------------
    // CACHE DOM REFERENCES (EXACT IDS ONLY)
    // ---------------------------------------------------------------------
    cacheFields() {
        EL = {
            incident: document.getElementById("ctIncidentNumber"),
            date: document.getElementById("ctDate"),
            time: document.getElementById("ctTime"),

            location: document.getElementById("ctLocation"),
            node: document.getElementById("ctNode"),

            poleAlpha: document.getElementById("ctPoleAlpha"),
            poleAlphaDec: document.getElementById("ctPoleAlphaDec"),
            poleNum: document.getElementById("ctPoleNum"),
            poleNumDec: document.getElementById("ctPoleNumDec"),
            crossStreet: document.getElementById("ctCrossStreet"),

            type: document.getElementById("ctType"),

            // DAILY LOG subtype (only visible when Type = DAILY LOG)
            dailySubtypeRow: document.getElementById("ctDailySubtypeRow"),
            dailySubtype: document.getElementById("ctDailySubtype"),

            narrative: document.getElementById("ctNarrative"),

            callerFirst: document.getElementById("ctCallerFirst"),
            callerLast: document.getElementById("ctCallerLast"),
            callerPhone: document.getElementById("ctCallerPhone"),
            callerLocation: document.getElementById("ctCallerLocation"),
        };
    },

    // ---------------------------------------------------------------------
    // TYPE RULES
    // ---------------------------------------------------------------------
    isDailyLogType() {
        return ((EL.type?.value || "").trim().toUpperCase() === "DAILY LOG");
    },

    applyTypeRules() {
        const isDL = this.isDailyLogType();

        // Show/hide subtype row
        if (EL.dailySubtypeRow) {
            EL.dailySubtypeRow.style.display = isDL ? "" : "none";
        }

        // DAILY LOG subtype enable/required behavior (even if HTML uses inline onchange)
        if (EL.dailySubtype) {
            EL.dailySubtype.required = isDL;

            // If form is locked, lockForm() already disabled everything.
            // If unlocked, enforce that subtype is disabled unless DAILY LOG.
            if (FORM_UNLOCKED) {
                EL.dailySubtype.disabled = !isDL;
            } else {
                // keep disabled while locked
                EL.dailySubtype.disabled = true;
            }

            // Reset subtype if not Daily Log
            if (!isDL) EL.dailySubtype.selectedIndex = 0;
        }

        // Toggle location required UI (client-side; backend enforces rules too)
        if (EL.location) {
            EL.location.required = !isDL;
        }
    },

    // ---------------------------------------------------------------------
    // START NEW INCIDENT (DRAFT ONLY)
    // ---------------------------------------------------------------------
    async startNewIncident() {
        try {
            // If you're actively drafting, attempt to HOLD it before starting another.
            // NOTE: HELD may require a reason in some builds; do not block new draft creation
            // if HOLD fails.
            if (CURRENT_INCIDENT_ID) {
                try {
                    await CAD_UTIL.postJSON(`/incident/${CURRENT_INCIDENT_ID}/hold`, { reason: "Draft superseded by new draft" });
                } catch (e) {
                    console.warn("[CALLTAKER] Hold previous draft failed (continuing):", e);
                }
            }

            const res = await CAD_UTIL.postJSON("/incident/new", {});
            if (!res?.incident_id) {
                throw new Error("No incident_id returned");
            }

            CURRENT_INCIDENT_ID = res.incident_id;


            this.enterEditMode();
        } catch (err) {
            console.error("[CALLTAKER] Failed to start incident:", err);
            alert("Unable to start new incident.");
        }
    },

    // ---------------------------------------------------------------------
    // SAVE INCIDENT (VALIDATED)
    // ---------------------------------------------------------------------
    async saveIncident() {
        if (!CURRENT_INCIDENT_ID || !FORM_UNLOCKED) {
            console.warn("[CALLTAKER] Save blocked — invalid state.");
            return;
        }

        const typeVal = (EL.type?.value || "").trim();
        const isDL = this.isDailyLogType();

        // HARD VALIDATION — MINIMUM REQUIRED
        if (!typeVal) {
            alert("Incident Type is required.");
            EL.type?.focus();
            return;
        }

        // Non-DailyLog incidents require Location
        if (!isDL && !(EL.location?.value || "").trim()) {
            alert("Location is required.");
            EL.location?.focus();
            return;
        }

        // Daily Log incidents require subtype only (narrative is OPTIONAL per FORD-CAD canon)
        if (isDL) {
            const subtypeVal = (EL.dailySubtype?.value || "").trim();
            if (!subtypeVal) {
                alert("Daily Subtype is required for DAILY LOG.");
                EL.dailySubtype?.focus();
                return;
            }
            // Note: narrative/details are OPTIONAL for Daily Log entries
        }

        const payload = {
            type: typeVal,

            // For DAILY LOG incidents, location is optional (backend allows blank)
            location: (EL.location?.value || "").trim(),
            node: (EL.node?.value || "").trim(),

            pole_alpha: (EL.poleAlpha?.value || "").trim(),
            pole_alpha_dec: (EL.poleAlphaDec?.value || "").trim(),
            pole_number: (EL.poleNum?.value || "").trim(),
            pole_number_dec: (EL.poleNumDec?.value || "").trim(),

            narrative: (EL.narrative?.value || "").trim(),

            caller_first: (EL.callerFirst?.value || "").trim(),
            caller_last: (EL.callerLast?.value || "").trim(),
            caller_phone: (EL.callerPhone?.value || "").trim(),
            caller_location: (EL.callerLocation?.value || "").trim(),
            cross_street: (EL.crossStreet?.value || "").trim(),

            // DAILY LOG subtype (Phase-3 canon)
            dailylog_subtype: isDL ? (EL.dailySubtype?.value || "").trim() : "",
        };

        const savedId = CURRENT_INCIDENT_ID;

        try {
            await CAD_UTIL.postJSON(`/incident/save/${savedId}`, payload);


            // Play new incident sound alert and show toast
            try { window.SOUNDS?.newIncident?.(); } catch (_) {}
            try { window.TOAST?.success?.(`Incident created successfully`); } catch (_) {}

            CURRENT_INCIDENT_ID = null;
            FORM_UNLOCKED = false;

            this.clearForm();
            this.lockForm();

            // Refresh panels (preferred orchestrator). Keep legacy event for older listeners.
            try { CAD_UTIL.refreshPanels?.({ source: "calltaker-save", incident_id: savedId }); } catch (_) {}
            try { CAD_UTIL.emitIncidentUpdated?.({ source: "calltaker-save", incident_id: savedId }); } catch (_) {}

            // If HTMX swaps are mid-flight, a second refresh on next tick is harmless and
            // solves “appears only after a second manual refresh” without loops.
            setTimeout(() => {
                try { CAD_UTIL.refreshPanels?.({ source: "calltaker-save-tick", incident_id: savedId }); } catch (_) {}
            }, 50);

            document.getElementById("btn-new-incident")?.focus();
        } catch (err) {
            console.error("[CALLTAKER] Save failed:", err);
            alert("Failed to save incident.");
        }
    },

    // ---------------------------------------------------------------------
    // CANCEL INCIDENT
    // ---------------------------------------------------------------------
    async cancelIncident() {
        if (!CURRENT_INCIDENT_ID) {
            this.clearForm();
            this.lockForm();
            document.getElementById("btn-new-incident")?.focus();
            return;
        }

        const cancelId = CURRENT_INCIDENT_ID;

        try {
            await CAD_UTIL.postJSON(`/incident/cancel/${cancelId}`);
        } catch (e) {
            console.warn("[CALLTAKER] Cancel failed, continuing cleanup.");
        }

        CURRENT_INCIDENT_ID = null;
        FORM_UNLOCKED = false;

        this.clearForm();
        this.lockForm();

        // Update panels after cancel
        try { CAD_UTIL.refreshPanels?.({ source: "calltaker-cancel", incident_id: cancelId }); } catch (_) {}
        try { CAD_UTIL.emitIncidentUpdated?.({ source: "calltaker-cancel", incident_id: cancelId }); } catch (_) {}

        document.getElementById("btn-new-incident")?.focus();
    },

    // ---------------------------------------------------------------------
    // LOAD EXISTING INCIDENT FOR EDITING (CANON REQUIREMENT)
    // ---------------------------------------------------------------------
    async loadIncident(incident_id) {
        if (!incident_id) {
            console.warn("[CALLTAKER] loadIncident called without incident_id");
            return;
        }

        try {
            // Fetch incident data from backend
            const data = await CAD_UTIL.getJSON(`/incident/${incident_id}/edit_data`);

            if (!data || data.ok === false) {
                throw new Error(data?.error || "Failed to load incident data");
            }

            CURRENT_INCIDENT_ID = incident_id;

            // Cache DOM references if not already done
            this.cacheFields();

            // Populate form fields
            if (EL.incident) EL.incident.value = data.incident_number || "";
            if (EL.date) EL.date.value = data.date || "";
            if (EL.time) EL.time.value = data.time || "";

            if (EL.location) EL.location.value = data.location || "";
            if (EL.node) EL.node.value = data.node || "";

            if (EL.poleAlpha) EL.poleAlpha.value = data.pole_alpha || "";
            if (EL.poleAlphaDec) EL.poleAlphaDec.value = data.pole_alpha_dec || "";
            if (EL.poleNum) EL.poleNum.value = data.pole_number || "";
            if (EL.poleNumDec) EL.poleNumDec.value = data.pole_number_dec || "";

            if (EL.type) EL.type.value = data.type || "";

            if (EL.dailySubtype) EL.dailySubtype.value = data.dailylog_subtype || "";

            if (EL.narrative) EL.narrative.value = data.narrative || "";

            if (EL.callerFirst) EL.callerFirst.value = data.caller_first || "";
            if (EL.callerLast) EL.callerLast.value = data.caller_last || "";
            if (EL.callerPhone) EL.callerPhone.value = data.caller_phone || "";
            if (EL.callerLocation) EL.callerLocation.value = data.caller_location || "";

            // Unlock form for editing
            this.unlockForm();
            FORM_UNLOCKED = true;

            // Apply type rules (show/hide daily log subtype row)
            this.applyTypeRules();

            // Focus location field
            EL.location?.focus();


        } catch (err) {
            console.error("[CALLTAKER] loadIncident failed:", err);
            alert("Failed to load incident for editing: " + (err.message || err));
        }
    },

    // ---------------------------------------------------------------------
    // UI HELPERS
    // ---------------------------------------------------------------------
    enterEditMode() {
        const now = new Date();

        if (EL.incident) EL.incident.value = "";
        if (EL.date) EL.date.value = now.toISOString().slice(0, 10);
        if (EL.time) EL.time.value = now.toTimeString().slice(0, 5);

        this.unlockForm();
        FORM_UNLOCKED = true;

        // Ensure subtype row visibility + enable/required matches current type
        this.applyTypeRules();

        // Focus rules: Daily Log -> subtype (if visible), otherwise Location
        if (this.isDailyLogType()) {
            (EL.dailySubtype || EL.narrative || EL.type)?.focus?.();
        } else {
            EL.location?.focus();
        }
    },

    clearForm() {
        Object.values(EL).forEach((el) => {
            if (!el) return;

            // Only clear form controls
            if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
                el.value = "";
            } else if (el.tagName === "SELECT") {
                el.selectedIndex = 0;
            }
        });

        // Hide subtype row by default after clearing
        if (EL.dailySubtypeRow) EL.dailySubtypeRow.style.display = "none";
    },

    lockForm() {
        Object.values(EL).forEach((el) => {
            if (!el) return;
            if ("disabled" in el) el.disabled = true;
        });
        FORM_UNLOCKED = false;

        // Subtype row should be hidden when locked
        if (EL.dailySubtypeRow) EL.dailySubtypeRow.style.display = "none";
    },

    unlockForm() {
        Object.values(EL).forEach((el) => {
            if (!el) return;
            if ("disabled" in el) el.disabled = false;
        });

        // After unlocking, enforce type rules (subtype disabled unless DAILY LOG)
        this.applyTypeRules();
    },
};

window.CALLTAKER = CALLTAKER;

// Legacy global alias for backward compatibility (canon requirement)
window.__BOSK_CALLTAKER = CALLTAKER;

Object.freeze(CALLTAKER);

export default CALLTAKER;
