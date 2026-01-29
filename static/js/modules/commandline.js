// ============================================================================
// FORD CAD — COMMAND LINE MODULE (Professional Grade)
// Comprehensive CLI with flexible command aliases for all CAD functions
// Designed for both power users and operators who prefer varied terminology
// ============================================================================

import IAW from "./iaw.js";
import UAW from "./uaw2.js";
import { CAD_MODAL } from "./modal.js";
import { CAD_UTIL } from "./utils.js";

const CLI = {
    _pending: null,

    // ========================================================================
    // COMMAND DEFINITIONS
    // Each command has: key (internal), aliases (user input), description
    // ========================================================================
    COMMANDS: [
        // --- View Commands (no unit prefix) ---
        { key: "VIEW_IAW", aliases: ["IAW", "INC", "INCIDENT"], desc: "Open incident: IAW <id>" },
        { key: "VIEW_UAW", aliases: ["UAW", "UNIT"], desc: "Open unit: UAW <id>" },
        { key: "VIEW_HELD", aliases: ["HELD", "HOLDING", "ONHOLD"], desc: "View held incidents" },
        { key: "VIEW_ACTIVE", aliases: ["ACTIVE", "ACT"], desc: "View active incidents" },
        { key: "VIEW_OPEN", aliases: ["OPEN", "PENDING"], desc: "View open incidents" },
        { key: "VIEW_DAILY", aliases: ["DAILY", "DAILYLOG", "LOG"], desc: "View daily log" },
        { key: "VIEW_HISTORY", aliases: ["HISTORY", "HIST", "SEARCH"], desc: "Search history" },
        { key: "VIEW_UNITS", aliases: ["UNITS", "ROSTER"], desc: "View units panel" },
        { key: "VIEW_ALL_UNITS", aliases: ["ALLUNITS", "ALL", "ALLU", "VIEWALL"], desc: "View all department units" },
        { key: "VIEW_SHIFT_UNITS", aliases: ["SHIFT", "CURRENT", "MYSHIFT"], desc: "View current shift units only" },

        // --- Modal Commands ---
        { key: "CLOSE_MODAL", aliases: ["CLOSE", "X", "EXIT", "CANCEL", "ESC"], desc: "Close modal/window" },
        { key: "HELP", aliases: ["HELP", "?", "H", "COMMANDS", "CMD"], desc: "Show help" },

        // --- Incident Creation ---
        { key: "NEW_INCIDENT", aliases: ["NEW", "CREATE", "CALL", "NEWCALL", "NEWINC"], desc: "Create new incident" },

        // --- Unit-Prefixed Commands ---
        // Dispatch
        { key: "DISPATCH", aliases: ["D", "DISP", "DISPATCH", "SEND"], desc: "Dispatch unit(s)" },
        { key: "DISPATCH_ENROUTE", aliases: ["DE", "D/E", "DISPENR", "DISPATCHENROUTE", "SENDE"], desc: "Dispatch + Enroute" },

        // Status progression
        { key: "ENROUTE", aliases: ["E", "ENR", "ENROUTE", "ENRT", "RESPONDING"], desc: "Set ENROUTE" },
        { key: "ARRIVED", aliases: ["A", "ARR", "ARRIVE", "ARRIVED", "OS", "ONSCENE", "10-23", "1023"], desc: "Set ARRIVED/ON SCENE" },
        { key: "TRANSPORTING", aliases: ["T", "TR", "TRANS", "TRANSPORT", "TRANSPORTING"], desc: "Set TRANSPORTING" },
        { key: "AT_MEDICAL", aliases: ["M", "MED", "ATMED", "AT_MED", "MEDICAL", "HOSP", "HOSPITAL", "ER"], desc: "Set AT MEDICAL" },
        { key: "AVAILABLE", aliases: ["AV", "AVAIL", "AVAILABLE", "CLR", "CLEAR", "10-8", "108", "IC"], desc: "Set AVAILABLE/CLEAR" },
        { key: "OOS", aliases: ["OOS", "OUTOFSERVICE", "10-7", "107", "OUT"], desc: "Set OUT OF SERVICE" },

        // Clear from incident
        { key: "CLEAR_UNIT", aliases: ["CU", "CLEARUNIT", "RELEASE", "REL", "DONE"], desc: "Clear unit from incident" },

        // Coverage / Shift Management - ADD UNIT
        { key: "ADD_UNIT", aliases: [
            "AU", "ADDUNIT", "ADDU", "ADD",
            "10-8", "108", "1008",
            "INSERVICE", "IS",
            "COV", "COVER", "COVERAGE", "ADDCOV",
            "SIGNIN", "SIGNON", "ON"
        ], desc: "Add unit to shift coverage" },

        // Coverage / Shift Management - DELETE/REMOVE UNIT
        { key: "DEL_UNIT", aliases: [
            "DU", "DELUNIT", "DELU", "DEL",
            "10-7", "107", "1007",
            "REMOVE", "REM", "RM",
            "UNCOV", "UNCOVER", "RMCOV", "ENDCOV",
            "SIGNOUT", "SIGNOFF", "OFF"
        ], desc: "Remove unit from shift coverage" },

        // Remarks
        { key: "ADD_REMARK", aliases: ["AR", "RMK", "REMARK", "NOTE", "COMMENT", "MSG"], desc: "Add remark: 18 AR <text>" },

        // Crew Management
        { key: "ASSIGN_CREW", aliases: ["CREW", "ASSIGN", "ADDCREW", "AC"], desc: "Assign to apparatus: 18 CREW E1" },
        { key: "UNASSIGN_CREW", aliases: ["UNCREW", "UNASSIGN", "RMCREW", "UC"], desc: "Unassign from apparatus" },

        // Incident Actions (with incident ID)
        { key: "HOLD_INCIDENT", aliases: ["HOLD", "HOLDINC", "PUTHOLD"], desc: "Hold incident: HOLD <id>" },
        { key: "UNHOLD_INCIDENT", aliases: ["UNHOLD", "RESUME", "ACTIVATE"], desc: "Unhold incident: UNHOLD <id>" },
        { key: "CLOSE_INCIDENT", aliases: ["CLOSEINC", "DISPOSE", "DISPO", "COMPLETE"], desc: "Close incident: CLOSEINC <id>" },

        // Misc status
        { key: "SET_MISC", aliases: ["MISC", "STATUS", "STAT", "SET"], desc: "Set misc status: 18 MISC <text>" },
    ],

    init() {
        const input = document.querySelector("#cmd-input");
        if (!input) return;

        input.addEventListener("keydown", (e) => {
            if (e.key !== "Enter") return;
            e.preventDefault();

            const cmd = (input.value || "").trim();
            if (!cmd) return;

            this.execute(cmd).catch((err) => {
                console.error("[CLI] Execute failed:", err);
                alert(err?.message || "Command failed.");
            });

            input.value = "";
        });

        console.log("[CLI] Professional CLI ready.");
    },

    // ========================================================================
    // TOKENIZER & MATCHERS
    // ========================================================================
    _tokenize(command) {
        const raw = String(command || "").trim();
        if (!raw) return [];
        const parts = raw.split(/\s+/).filter(Boolean);
        const out = [];
        for (const p of parts) {
            const split = String(p).split(",").map((x) => x.trim()).filter(Boolean);
            out.push(...split);
        }
        return out;
    },

    _isIncidentRef(tok) {
        return /^[0-9]{4}-[0-9]{5}$/.test(tok) || /^[0-9]+$/.test(tok);
    },

    _looksLikeUnit(tok) {
        const t = String(tok || "").trim();
        if (!t) return false;
        if (t.includes("-")) return false;
        if (/[^A-Za-z0-9]/.test(t)) return false;
        if (t.length > 12) return false;
        // Don't match pure command words
        if (this._matchCommand(t)) return false;
        return true;
    },

    _matchCommand(tok) {
        const t = String(tok || "").trim().toUpperCase().replace(/-/g, "");
        if (!t) return null;

        for (const cmd of this.COMMANDS) {
            for (const alias of cmd.aliases) {
                if (alias.toUpperCase().replace(/-/g, "") === t) {
                    return cmd.key;
                }
            }
        }

        // Fuzzy prefix matching for longer commands
        for (const cmd of this.COMMANDS) {
            for (const alias of cmd.aliases) {
                const a = alias.toUpperCase();
                if (a.length > 3 && a.startsWith(t) && t.length >= 3) {
                    return cmd.key;
                }
            }
        }

        return null;
    },

    _asUnitList(units) {
        return (units || []).map((u) => String(u).trim()).filter(Boolean);
    },

    // ========================================================================
    // HELP SYSTEM
    // ========================================================================
    _help() {
        const helpText = `
═══════════════════════════════════════════════════════════
                    FORD CAD COMMAND LINE
═══════════════════════════════════════════════════════════

VIEWS & NAVIGATION
  held, active, open       View incident panels
  daily, history           View logs
  allunits, viewall        View ALL department units
  shift, current           View current shift units only
  iaw <id>                 Open incident window
  uaw <id>                 Open unit window
  close, x, esc            Close modal/window

NEW INCIDENT
  new, create, call        Create new incident

DISPATCH (opens picker if no incident specified)
  18 D                     Dispatch unit 18
  18 DE                    Dispatch + set Enroute
  18 D 2026-00001          Dispatch to specific incident
  18,19,E1 D               Dispatch multiple units

UNIT STATUS (unit must be on incident)
  18 E                     ENROUTE (E, ENR, RESPONDING)
  18 A                     ARRIVED (A, ARR, OS, ONSCENE, 10-23)
  18 T                     TRANSPORTING (T, TR, TRANS)
  18 M                     AT MEDICAL (M, MED, HOSP, ER)
  18 AV                    AVAILABLE (AV, CLR, CLEAR, 10-8, IC)
  18 OOS                   OUT OF SERVICE (OOS, 10-7, OUT)

ADD UNIT TO SHIFT (many aliases accepted)
  32 AU                    Add unit (AU, ADD, ADDU)
  32 10-8                  Add unit (10-8, 108)
  32 COV                   Add coverage (COV, COVER)
  32 ON                    Sign on (ON, SIGNIN, SIGNON)

REMOVE UNIT FROM SHIFT
  32 DU                    Delete unit (DU, DEL, REM)
  32 10-7                  Remove (10-7, 107)
  32 UNCOV                 End coverage (UNCOV, RMCOV)
  32 OFF                   Sign off (OFF, SIGNOUT)

CLEAR UNIT FROM INCIDENT
  18 CU                    Clear unit (CU, RELEASE, REL, DONE)

REMARKS
  18 AR Patient stable     Add remark to unit's incident
  18 NOTE Delayed 5min     (AR, RMK, REMARK, NOTE, MSG)

CREW MANAGEMENT
  18 CREW E1               Assign personnel 18 to Engine 1
  18 UNCREW                Unassign from apparatus

INCIDENT ACTIONS
  hold <id>                Put incident on hold
  unhold <id>              Resume held incident
  closeinc <id>            Open disposition for incident

MISC STATUS
  18 MISC Lunch            Set custom status text
  18 STATUS Training       (MISC, STATUS, STAT, SET)

═══════════════════════════════════════════════════════════
  Type HELP or ? anytime to see this reference
═══════════════════════════════════════════════════════════
`.trim();

        // Use a modal or alert for help
        if (window.CAD_MODAL?.openText) {
            window.CAD_MODAL.openText(helpText, "CLI Help");
        } else {
            alert(helpText);
        }
    },

    // ========================================================================
    // ACTION HANDLERS
    // ========================================================================
    openIncidentPicker(units, mode) {
        this._pending = {
            units: this._asUnitList(units),
            mode: String(mode || "D").toUpperCase(),
        };
        const unitsCsv = this._pending.units.join(",");
        const url = `/api/cli/incident_picker?units=${encodeURIComponent(unitsCsv)}&mode=${encodeURIComponent(this._pending.mode)}`;
        CAD_MODAL.open(url, { modalClass: "cli-incident-picker-modal" });
    },

    async pickIncident(incidentId) {
        const pending = this._pending;
        if (!pending || !pending.units?.length) {
            alert("CLI picker state missing.");
            return;
        }

        try {
            const res = await CAD_UTIL.postJSON("/api/cli/dispatch", {
                incident_id: Number(incidentId),
                units: pending.units,
                mode: pending.mode,
            });

            if (res?.ok === false) {
                alert(res?.error || "Dispatch rejected.");
                return;
            }

            CAD_MODAL.close();
            CAD_UTIL.refreshPanels();

            const id = Number(res?.incident_id || incidentId || 0);
            if (id) IAW.open(id);

            this._pending = null;
        } catch (err) {
            console.error("[CLI] pickIncident failed:", err);
            alert(err?.message || "Dispatch failed.");
        }
    },

    async _dispatchToIncidentRef(units, ref, mode) {
        try {
            const res = await CAD_UTIL.postJSON("/api/cli/dispatch", {
                incident_ref: String(ref),
                units: this._asUnitList(units),
                mode,
            });

            if (res?.ok === false) {
                alert(res?.error || "Dispatch rejected.");
                return;
            }

            CAD_UTIL.refreshPanels();
            if (res?.incident_id) IAW.open(res.incident_id);
        } catch (err) {
            console.error("[CLI] dispatch failed:", err);
            alert(err?.message || "Dispatch failed.");
        }
    },

    async _setStatusForUnits(units, status) {
        const list = this._asUnitList(units);
        for (const u of list) {
            try {
                const ctx = await CAD_UTIL.getJSON(`/api/uaw/context/${encodeURIComponent(u)}`);
                const incId = Number(ctx?.active_incident_id || 0);
                if (!incId) {
                    alert(`Unit ${u} is not on an active incident.`);
                    continue;
                }
                await CAD_UTIL.postJSON(`/incident/${incId}/unit/${encodeURIComponent(u)}/status`, { status });
            } catch (err) {
                console.error(`[CLI] Status failed for ${u}:`, err);
                alert(err?.message || `Status failed for ${u}.`);
            }
        }
        CAD_UTIL.refreshPanels();
    },

    async _setUnitAvailable(units) {
        const list = this._asUnitList(units);
        for (const u of list) {
            try {
                await CAD_UTIL.postJSON(`/api/unit_status/${encodeURIComponent(u)}/AVAILABLE`);
            } catch (err) {
                console.error(`[CLI] Available failed for ${u}:`, err);
            }
        }
        CAD_UTIL.refreshPanels();
    },

    async _setUnitOOS(units) {
        const list = this._asUnitList(units);
        for (const u of list) {
            try {
                await CAD_UTIL.postJSON(`/api/unit_status/${encodeURIComponent(u)}/OOS`);
            } catch (err) {
                console.error(`[CLI] OOS failed for ${u}:`, err);
            }
        }
        CAD_UTIL.refreshPanels();
    },

    async _addUnitToCoverage(units) {
        const list = this._asUnitList(units);
        for (const u of list) {
            try {
                const res = await CAD_UTIL.postJSON("/api/shift_override/start", {
                    unit_id: u,
                    reason: "CLI"
                });
                if (res?.ok === false) {
                    alert(res?.error || `Add unit failed: ${u}`);
                }
            } catch (err) {
                console.error(`[CLI] Add unit failed: ${u}`, err);
                alert(err?.message || `Add unit failed: ${u}`);
            }
        }
        CAD_UTIL.refreshPanels();
    },

    async _removeUnitFromCoverage(units) {
        const list = this._asUnitList(units);
        for (const u of list) {
            try {
                const res = await CAD_UTIL.postJSON("/api/shift_override/end", {
                    unit_id: u
                });
                if (res?.ok === false) {
                    alert(res?.error || `Remove unit failed: ${u}`);
                }
            } catch (err) {
                console.error(`[CLI] Remove unit failed: ${u}`, err);
                alert(err?.message || `Remove unit failed: ${u}`);
            }
        }
        CAD_UTIL.refreshPanels();
    },

    async _clearUnitsFromIncident(units) {
        const list = this._asUnitList(units);
        for (const u of list) {
            try {
                const ctx = await CAD_UTIL.getJSON(`/api/uaw/context/${encodeURIComponent(u)}`);
                const incId = Number(ctx?.active_incident_id || 0);
                if (!incId) {
                    alert(`Unit ${u} is not on an active incident.`);
                    continue;
                }
                // Clear requires disposition - open UAW for now
                if (window.UAW?.openIncidentUnit) {
                    window.UAW.openIncidentUnit(incId, u);
                } else {
                    window.UAW?.open(u);
                }
            } catch (err) {
                console.error(`[CLI] Clear failed for ${u}:`, err);
            }
        }
    },

    async _addRemark(units, text) {
        const list = this._asUnitList(units);
        for (const u of list) {
            try {
                const res = await CAD_UTIL.postJSON("/remark", { unit_id: u, text });
                if (res?.ok === false) {
                    alert(res?.error || `Remark failed: ${u}`);
                }
            } catch (err) {
                console.error(`[CLI] Remark failed: ${u}`, err);
                alert(err?.message || `Remark failed: ${u}`);
            }
        }
        CAD_UTIL.refreshPanels();
    },

    async _setMiscStatus(units, text) {
        const list = this._asUnitList(units);
        for (const u of list) {
            try {
                await CAD_UTIL.postJSON(`/api/uaw/misc/${encodeURIComponent(u)}`, { misc: text });
            } catch (err) {
                console.error(`[CLI] Misc status failed: ${u}`, err);
            }
        }
        CAD_UTIL.refreshPanels();
    },

    async _assignCrew(personnelId, apparatusId) {
        try {
            const res = await CAD_UTIL.postJSON("/api/crew/assign", {
                apparatus_id: apparatusId,
                personnel_id: personnelId
            });
            if (res?.ok === false) {
                alert(res?.error || "Crew assign failed.");
            }
        } catch (err) {
            console.error("[CLI] Crew assign failed:", err);
            alert(err?.message || "Crew assign failed.");
        }
        CAD_UTIL.refreshPanels();
    },

    async _unassignCrew(personnelId) {
        try {
            // Get current apparatus assignment
            const ctx = await CAD_UTIL.getJSON(`/api/uaw/context/${encodeURIComponent(personnelId)}`);
            const appId = ctx?.current_apparatus;
            if (!appId) {
                alert(`${personnelId} is not assigned to an apparatus.`);
                return;
            }
            const res = await CAD_UTIL.postJSON("/api/crew/unassign", {
                apparatus_id: appId,
                personnel_id: personnelId
            });
            if (res?.ok === false) {
                alert(res?.error || "Crew unassign failed.");
            }
        } catch (err) {
            console.error("[CLI] Crew unassign failed:", err);
            alert(err?.message || "Crew unassign failed.");
        }
        CAD_UTIL.refreshPanels();
    },

    // ========================================================================
    // MAIN EXECUTE
    // ========================================================================
    async execute(command) {
        const tokens = this._tokenize(command);
        if (!tokens.length) return;

        const first = tokens[0] || "";
        const firstCmd = this._matchCommand(first);

        // ----------------------------------------------------------------
        // SINGLE-WORD / VIEW COMMANDS (no unit prefix)
        // ----------------------------------------------------------------
        if (firstCmd === "HELP") {
            this._help();
            return;
        }

        if (firstCmd === "CLOSE_MODAL") {
            CAD_MODAL.close();
            return;
        }

        if (firstCmd === "VIEW_HELD") {
            CAD_MODAL.open("/panel/held");
            return;
        }

        if (firstCmd === "VIEW_ACTIVE") {
            // Scroll to or highlight active panel
            document.getElementById("panel-active")?.scrollIntoView({ behavior: "smooth" });
            return;
        }

        if (firstCmd === "VIEW_OPEN") {
            document.getElementById("panel-open")?.scrollIntoView({ behavior: "smooth" });
            return;
        }

        if (firstCmd === "VIEW_DAILY") {
            window.location.href = "/daily";
            return;
        }

        if (firstCmd === "VIEW_HISTORY") {
            window.location.href = "/history";
            return;
        }

        if (firstCmd === "VIEW_UNITS") {
            document.getElementById("panel-units")?.scrollIntoView({ behavior: "smooth" });
            return;
        }

        if (firstCmd === "VIEW_ALL_UNITS") {
            try {
                await CAD_UTIL.postJSON("/api/session/roster_view_mode", { mode: "ALL" });
                CAD_UTIL.refreshPanels();
            } catch (err) {
                console.error("[CLI] View all units failed:", err);
            }
            return;
        }

        if (firstCmd === "VIEW_SHIFT_UNITS") {
            try {
                await CAD_UTIL.postJSON("/api/session/roster_view_mode", { mode: "CURRENT" });
                CAD_UTIL.refreshPanels();
            } catch (err) {
                console.error("[CLI] View shift units failed:", err);
            }
            return;
        }

        if (firstCmd === "VIEW_IAW") {
            if (tokens[1]) IAW.open(tokens[1]);
            return;
        }

        if (firstCmd === "VIEW_UAW") {
            if (tokens[1]) UAW.open(tokens[1]);
            return;
        }

        if (firstCmd === "NEW_INCIDENT") {
            if (window.CALLTAKER?.newCall) {
                window.CALLTAKER.newCall();
            } else {
                CAD_MODAL.open("/calltaker");
            }
            return;
        }

        if (firstCmd === "HOLD_INCIDENT") {
            const incId = tokens[1];
            if (incId) {
                try {
                    await CAD_UTIL.postJSON(`/incident/${incId}/hold`);
                    CAD_UTIL.refreshPanels();
                } catch (err) {
                    alert(err?.message || "Hold failed.");
                }
            }
            return;
        }

        if (firstCmd === "UNHOLD_INCIDENT") {
            const incId = tokens[1];
            if (incId) {
                try {
                    await CAD_UTIL.postJSON(`/incident/${incId}/unhold`);
                    CAD_UTIL.refreshPanels();
                } catch (err) {
                    alert(err?.message || "Unhold failed.");
                }
            }
            return;
        }

        if (firstCmd === "CLOSE_INCIDENT") {
            const incId = tokens[1];
            if (incId && window.IAW?.dispositionIncident) {
                window.IAW.dispositionIncident(incId);
            }
            return;
        }

        // ----------------------------------------------------------------
        // UNIT-PREFIXED COMMANDS: <unit(s)> <action> [args...]
        // ----------------------------------------------------------------
        const units = [];
        let i = 0;

        while (i < tokens.length && this._looksLikeUnit(tokens[i])) {
            units.push(tokens[i]);
            i++;
        }

        if (!units.length) {
            console.warn("[CLI] Unknown command:", command);
            alert(`Unknown command: ${command}\nType HELP for available commands.`);
            return;
        }

        const actionTok = tokens[i] || "";
        const action = this._matchCommand(actionTok);
        const rest = tokens.slice(i + 1);

        if (!action) {
            console.warn("[CLI] Unknown action:", command);
            alert(`Unknown action: ${actionTok}\nType HELP for available commands.`);
            return;
        }

        // --- Dispatch ---
        if (action === "DISPATCH" || action === "DISPATCH_ENROUTE") {
            const mode = (action === "DISPATCH_ENROUTE") ? "DE" : "D";
            const ref = (rest[0] && this._isIncidentRef(rest[0])) ? rest[0] : "";

            if (ref) {
                await this._dispatchToIncidentRef(units, ref, mode);
            } else {
                this.openIncidentPicker(units, mode);
            }
            return;
        }

        // --- Status Progression ---
        if (action === "ENROUTE") {
            await this._setStatusForUnits(units, "ENROUTE");
            return;
        }

        if (action === "ARRIVED") {
            await this._setStatusForUnits(units, "ARRIVED");
            return;
        }

        if (action === "TRANSPORTING") {
            await this._setStatusForUnits(units, "TRANSPORTING");
            return;
        }

        if (action === "AT_MEDICAL") {
            await this._setStatusForUnits(units, "AT_MEDICAL");
            return;
        }

        if (action === "AVAILABLE") {
            await this._setUnitAvailable(units);
            return;
        }

        if (action === "OOS") {
            await this._setUnitOOS(units);
            return;
        }

        // --- Clear Unit from Incident ---
        if (action === "CLEAR_UNIT") {
            await this._clearUnitsFromIncident(units);
            return;
        }

        // --- Coverage / Add Unit to Shift ---
        if (action === "ADD_UNIT") {
            await this._addUnitToCoverage(units);
            return;
        }

        // --- Coverage / Remove Unit from Shift ---
        if (action === "DEL_UNIT") {
            await this._removeUnitFromCoverage(units);
            return;
        }

        // --- Remarks ---
        if (action === "ADD_REMARK") {
            const text = rest.join(" ").trim();
            if (!text) {
                alert("Usage: 18 AR <remark text>");
                return;
            }
            await this._addRemark(units, text);
            return;
        }

        // --- Misc Status ---
        if (action === "SET_MISC") {
            const text = rest.join(" ").trim();
            if (!text) {
                alert("Usage: 18 MISC <status text>");
                return;
            }
            await this._setMiscStatus(units, text);
            return;
        }

        // --- Crew Assignment ---
        if (action === "ASSIGN_CREW") {
            const appId = rest[0];
            if (!appId) {
                alert("Usage: 18 CREW E1");
                return;
            }
            await this._assignCrew(units[0], appId);
            return;
        }

        if (action === "UNASSIGN_CREW") {
            await this._unassignCrew(units[0]);
            return;
        }

        // --- View commands with unit context ---
        if (action === "VIEW_IAW") {
            const u = units[0];
            const ctx = await CAD_UTIL.getJSON(`/api/uaw/context/${encodeURIComponent(u)}`);
            const incId = Number(ctx?.active_incident_id || 0);
            if (!incId) {
                alert(`${u} is not on an active incident.`);
                return;
            }
            IAW.open(incId);
            return;
        }

        if (action === "VIEW_UAW") {
            UAW.open(units[0]);
            return;
        }

        console.warn("[CLI] Action not implemented:", action);
        alert(`Action not yet implemented: ${action}`);
    },
};

// Initialize
if (document.readyState !== "loading") {
    CLI.init();
} else {
    document.addEventListener("DOMContentLoaded", () => CLI.init());
}

// Global exports
window.CAD = window.CAD || {};
window.CAD.cli = CLI;
window.CAD.cli.pickIncident = (incidentId) => CLI.pickIncident(incidentId);

console.log("[CLI] Professional command line loaded.");

export default CLI;
