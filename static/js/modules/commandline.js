// ============================================================================
// FORD CAD — COMMAND LINE MODULE (Professional Grade)
// Comprehensive CLI with flexible command aliases for all CAD functions
// Based on industry-standard CAD command patterns
// ============================================================================

import IAW from "./iaw.js";
import UAW from "./uaw2.js";
import { CAD_MODAL } from "./modal.js";
import { CAD_UTIL } from "./utils.js";

const CLI = {
    _pending: null,
    _aliasMap: {},      // alias (lowercase) -> canonical unit_id
    _unitIds: new Set(), // Set of known unit_ids for validation

    // ========================================================================
    // COMMAND DEFINITIONS - Professional CAD Command Set
    // ========================================================================
    COMMANDS: [
        // ─────────────────────────────────────────────────────────────────────
        // HELP & SYSTEM
        // ─────────────────────────────────────────────────────────────────────
        { key: "HELP", aliases: ["HELP", "H"], desc: "Show full help" },
        { key: "QUICK_HELP", aliases: ["?"], desc: "Quick cheat sheet" },
        { key: "ALIASES", aliases: ["ALIASES", "AL"], desc: "List all command aliases" },
        { key: "REFRESH", aliases: ["REFRESH", "RF"], desc: "Refresh all panels" },
        { key: "CLOSE_MODAL", aliases: ["CLOSEMODAL", "ESC", "X"], desc: "Close modal/window" },

        // ─────────────────────────────────────────────────────────────────────
        // SEARCH & SHOW
        // ─────────────────────────────────────────────────────────────────────
        { key: "FIND", aliases: ["FIND", "F", "SEARCH", "SRCH"], desc: "Search: F <text>" },
        { key: "SHOW_UNITS", aliases: ["SU", "SHOWUNITS"], desc: "Show units: SU [ALL|A|B|C|D]" },
        { key: "SHOW_INCIDENTS", aliases: ["SI", "SHOWINCIDENTS"], desc: "Show incidents: SI [OPEN|ACTIVE|HELD]" },
        { key: "SHOW", aliases: ["SHOW", "SH"], desc: "Show unit/incident: SHOW <id>" },

        // ─────────────────────────────────────────────────────────────────────
        // SESSION & SHIFT VIEW
        // ─────────────────────────────────────────────────────────────────────
        { key: "VIEW_ALL", aliases: ["VA", "VIEWALL", "ALLUNITS", "ALL"], desc: "View all units (all shifts)" },
        { key: "VIEW_SHIFT", aliases: ["VS", "VIEWSHIFT"], desc: "View shift: VS [A|B|C|D]" },
        { key: "SHIFT", aliases: ["SHIFT"], desc: "Set shift view: SHIFT [AUTO|A|B|C|D]" },

        // ─────────────────────────────────────────────────────────────────────
        // COVERAGE MANAGEMENT
        // ─────────────────────────────────────────────────────────────────────
        { key: "COV_ADD", aliases: ["COV+", "COVADD", "ADDCOV"], desc: "Add coverage: COV+ <unit> [shift]" },
        { key: "COV_REMOVE", aliases: ["COV-", "COVREM", "RMCOV", "UNCOV"], desc: "Remove coverage: COV- <unit>" },
        { key: "COV_LIST", aliases: ["COVL", "COVLIST"], desc: "List coverage overrides" },

        // ─────────────────────────────────────────────────────────────────────
        // INCIDENT LIFECYCLE
        // ─────────────────────────────────────────────────────────────────────
        { key: "NEW_INCIDENT", aliases: ["NEW", "NC", "CREATE", "CALL", "NEWCALL"], desc: "Create incident: NEW [EMS|FIRE|...]" },
        { key: "OPEN_INCIDENT", aliases: ["OP", "OPEN"], desc: "Open incident (draft→open)" },
        { key: "ACTIVATE_INCIDENT", aliases: ["AC", "ACTIVATE", "GO"], desc: "Activate incident" },
        { key: "HOLD_INCIDENT", aliases: ["HOLD", "HD"], desc: "Hold incident: HOLD <id>: reason" },
        { key: "UNHOLD_INCIDENT", aliases: ["UNHOLD", "UHD", "RESUME"], desc: "Resume held incident" },
        { key: "CLOSE_INCIDENT", aliases: ["CLOSE", "CL"], desc: "Close incident (requires ED)" },
        { key: "CANCEL_INCIDENT", aliases: ["CANCEL", "CAN"], desc: "Cancel incident" },
        { key: "REOPEN_INCIDENT", aliases: ["REOPEN", "RO"], desc: "Reopen closed incident" },

        // ─────────────────────────────────────────────────────────────────────
        // INCIDENT FIELDS
        // ─────────────────────────────────────────────────────────────────────
        { key: "SET_FIELD", aliases: ["SET", "UPD"], desc: "Set field: SET I <#> LOC:\"...\"" },
        { key: "SET_LOCATION", aliases: ["LOC", "L"], desc: "Set location: LOC <#> <text>" },
        { key: "SET_TYPE", aliases: ["TYPE", "TY"], desc: "Set type: TYPE <#> <type>" },
        { key: "SET_PRIORITY", aliases: ["PRI", "P"], desc: "Set priority: PRI <#> <1-5>" },

        // ─────────────────────────────────────────────────────────────────────
        // NARRATIVE & TIMELINE
        // ─────────────────────────────────────────────────────────────────────
        { key: "NARRATIVE", aliases: ["NARR", "NAR"], desc: "Add narrative: NARR <#>: text" },
        { key: "TIMELINE_NOTE", aliases: ["NT", "TNOTE"], desc: "Add timeline note: NT <#>: text" },

        // ─────────────────────────────────────────────────────────────────────
        // DISPATCH & ASSIGNMENT
        // ─────────────────────────────────────────────────────────────────────
        { key: "DISPATCH", aliases: ["D", "DSP", "DISP", "DISPATCH", "SEND"], desc: "Dispatch: D <#> <units>" },
        { key: "DISPATCH_ENROUTE", aliases: ["DE", "D/E"], desc: "Dispatch + Enroute" },
        { key: "UNASSIGN", aliases: ["UA", "UNASSIGN", "RM"], desc: "Unassign unit: UA <unit> <#>" },
        { key: "MOVE_UNIT", aliases: ["MOVE", "MV"], desc: "Move unit: MOVE <unit> FROM <#> TO <#>" },
        { key: "ASSIGNED", aliases: ["ASG", "ASSIGNED"], desc: "List assigned: ASG <#>" },

        // ─────────────────────────────────────────────────────────────────────
        // UNIT STATUS (Generic + Specific)
        // ─────────────────────────────────────────────────────────────────────
        { key: "STATUS", aliases: ["ST"], desc: "Set status: ST <unit> <status>" },
        { key: "ENROUTE", aliases: ["E", "ENR", "ENROUTE", "ENRT", "ER", "RESPONDING"], desc: "Set ENROUTE" },
        { key: "ARRIVED", aliases: ["A", "ARR", "ARRIVE", "ARRIVED", "OS", "ONSCENE", "ONS", "10-23", "1023"], desc: "Set ARRIVED" },
        { key: "OPERATING", aliases: ["OPR", "OP", "OPERATING", "WORK"], desc: "Set OPERATING" },
        { key: "TRANSPORTING", aliases: ["T", "TR", "TRN", "TX", "TRANS", "TRANSPORT"], desc: "Set TRANSPORTING" },
        { key: "AT_MEDICAL", aliases: ["M", "MED", "ATMED", "AT_MED", "MEDICAL", "HOSP"], desc: "Set AT MEDICAL" },
        { key: "AVAILABLE", aliases: ["AV", "AVL", "AVAIL", "AVAILABLE", "10-8", "108"], desc: "Set AVAILABLE" },
        { key: "BUSY", aliases: ["BUSY", "ACT", "RED"], desc: "Set BUSY/ACTIVE" },
        { key: "OOS", aliases: ["O", "OOS", "OUT", "OUTOFSERVICE", "10-7", "107"], desc: "Set OUT OF SERVICE" },

        // ─────────────────────────────────────────────────────────────────────
        // CLEARING & DISPOSITIONS
        // ─────────────────────────────────────────────────────────────────────
        { key: "CLEAR", aliases: ["C", "CLR", "CLEAR"], desc: "Clear unit: C <unit>" },
        { key: "CLEAR_ALL", aliases: ["CA", "CLEARALL"], desc: "Clear all units: CA <#>" },
        { key: "UNIT_DISPO", aliases: ["UD", "UNITDISPO"], desc: "Unit disposition: UD <unit> <code>" },
        { key: "EVENT_DISPO", aliases: ["ED", "EVD", "EVENTDISPO"], desc: "Event disposition: ED <#> <code>" },

        // ─────────────────────────────────────────────────────────────────────
        // REMARKS & DAILY LOG
        // ─────────────────────────────────────────────────────────────────────
        { key: "ADD_REMARK", aliases: ["R", "AR", "RMK", "REMARK"], desc: "Add remark: <unit> R: text" },
        { key: "DAILY_LOG", aliases: ["DL", "DLOG", "LOG"], desc: "Daily log: DL: text" },
        { key: "DAILY_LOG_SHOW", aliases: ["DLS", "LOGSHOW"], desc: "Show daily log" },

        // ─────────────────────────────────────────────────────────────────────
        // CREW & ROSTER
        // ─────────────────────────────────────────────────────────────────────
        { key: "CREW_ADD", aliases: ["CA+", "CREWADD", "CREW"], desc: "Add crew: CA+ <person> TO <apparatus>" },
        { key: "CREW_REMOVE", aliases: ["CA-", "CREWREM", "UNCREW"], desc: "Remove crew: CA- <person> FROM <apparatus>" },
        { key: "CREW_SHOW", aliases: ["CS", "CREWSHOW"], desc: "Show crew: CS <apparatus>" },
        { key: "ADD_UNIT", aliases: ["AU", "ADDUNIT", "IS", "INSERVICE", "IN", "SIGNIN"], desc: "Add unit to shift" },
        { key: "DEL_UNIT", aliases: ["DU", "DELUNIT", "SIGNOUT", "OFF"], desc: "Remove unit from shift" },

        // ─────────────────────────────────────────────────────────────────────
        // VIEW SHORTCUTS (legacy compatibility)
        // ─────────────────────────────────────────────────────────────────────
        { key: "VIEW_IAW", aliases: ["IAW", "INC", "INCIDENT"], desc: "Open incident: IAW <id>" },
        { key: "VIEW_UAW", aliases: ["UAW", "UNIT"], desc: "Open unit: UAW <id>" },
        { key: "VIEW_HELD", aliases: ["HELD", "HOLDING"], desc: "View held incidents" },
        { key: "VIEW_ACTIVE", aliases: ["ACTIVE"], desc: "View active incidents" },
        { key: "VIEW_DAILY", aliases: ["DAILY", "DAILYLOG"], desc: "View daily log" },
        { key: "VIEW_HISTORY", aliases: ["HISTORY", "HIST"], desc: "Search history" },
        { key: "SEND_REPORT", aliases: ["REPORT", "RPT", "SENDREPORT"], desc: "Send daily report" },
    ],

    // Unit Disposition codes
    UNIT_DISPO_CODES: {
        "R": "Resolved",
        "NA": "No Action Required",
        "NF": "Not Found",
        "C": "Cancelled",
        "CT": "Cancelled Transport",
        "O": "Other"
    },

    // Event Disposition codes
    EVENT_DISPO_CODES: {
        "R": "Resolved",
        "FA": "False Alarm",
        "NF": "Not Found",
        "T": "Transport",
        "CT": "Cancelled Transport",
        "PRTT": "Patient Refusal",
        "C": "Cancelled",
        "O": "Other"
    },

    async init() {
        const input = document.querySelector("#cmd-input");
        if (!input) return;

        // Load unit aliases for dynamic resolution
        await this._loadAliases();

        input.addEventListener("keydown", (e) => {
            if (e.key !== "Enter") return;
            e.preventDefault();

            const cmd = (input.value || "").trim();
            if (!cmd) return;

            this.execute(cmd).catch((err) => {
                console.error("[CLI] Execute failed:", err);
                this._toast(err?.message || "Command failed.", "error");
            });

            input.value = "";
        });

    },

    async _loadAliases() {
        try {
            const resp = await fetch("/api/unit_aliases");
            if (resp.ok) {
                this._aliasMap = await resp.json();
                this._unitIds = new Set(Object.values(this._aliasMap));
            }
        } catch (err) {
            console.warn("[CLI] Failed to load unit aliases:", err);
        }
    },

    resolveAlias(input) {
        const key = String(input || "").trim().toLowerCase();
        return this._aliasMap[key] || input;
    },

    resolveAliases(inputs) {
        return (inputs || []).map(i => this.resolveAlias(i));
    },

    _toast(msg, type = "info") {
        if (window.TOAST?.[type]) {
            window.TOAST[type](msg);
        } else if (type === "error") {
            alert(msg);
        }
    },

    // ========================================================================
    // TOKENIZER & MATCHERS
    // ========================================================================
    _tokenize(command) {
        // Handle colon-separated remarks: "12 AR: some text" -> ["12", "AR", "some text"]
        const colonIdx = command.indexOf(":");
        if (colonIdx > 0) {
            const before = command.substring(0, colonIdx).trim();
            const after = command.substring(colonIdx + 1).trim();
            const parts = before.split(/\s+/).filter(Boolean);
            if (after) parts.push(after);
            return parts;
        }

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
        // Full incident number: 2026-00001 or #2026-00001
        if (/^#?[0-9]{4}-[0-9]{5}$/.test(tok)) return true;
        // Incident ID: #123 or just digits
        if (/^#?[0-9]+$/.test(tok)) return true;
        // Row number reference: 1, 2, 3 (active) or o1, o2 (open)
        if (/^o?[0-9]+$/i.test(tok)) return true;
        return false;
    },

    _normalizeIncidentRef(tok) {
        return String(tok || "").replace(/^#/, "");
    },

    /**
     * Resolve a row number (1, 2, o1) to an incident_id by looking at the panels
     */
    _resolveRowNumber(ref) {
        const refLower = String(ref || "").toLowerCase();

        // Check if it's a row number reference (1, 2, 3 or o1, o2)
        const openMatch = refLower.match(/^o(\d+)$/);
        const activeMatch = refLower.match(/^(\d+)$/);

        if (openMatch) {
            // Open incidents panel
            const rowNum = parseInt(openMatch[1], 10);
            const row = document.querySelector(`#panel-open tr[data-row-num="o${rowNum}"]`);
            return row?.dataset?.incidentId || null;
        }

        if (activeMatch) {
            const rowNum = parseInt(activeMatch[1], 10);
            // First check active incidents
            const activeRow = document.querySelector(`#panel-active tr[data-row-num="${rowNum}"]`);
            if (activeRow?.dataset?.incidentId) {
                return activeRow.dataset.incidentId;
            }
            // Fall back to any panel with that row number
            const anyRow = document.querySelector(`tr[data-row-num="${rowNum}"]`);
            return anyRow?.dataset?.incidentId || null;
        }

        return null;
    },

    _looksLikeUnit(tok) {
        const t = String(tok || "").trim();
        if (!t) return false;
        if (t.startsWith("#")) return false; // Incident ref
        if (t.includes("-") && /^\d{4}-\d{5}$/.test(t)) return false; // Incident number
        if (/[^A-Za-z0-9]/.test(t)) return false;
        if (t.length > 12) return false;
        if (this._matchCommand(t)) return false;
        const key = t.toLowerCase();
        if (Object.keys(this._aliasMap).length > 0 && this._aliasMap[key]) return true;
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
        return null;
    },

    _asUnitList(units) {
        return (units || []).map((u) => this.resolveAlias(String(u).trim())).filter(Boolean);
    },

    // ========================================================================
    // HELP SYSTEM
    // ========================================================================
    _quickHelp() {
        const text = `
╔═══════════════════════════════════════════════════════════╗
║              FORD CAD — QUICK REFERENCE                   ║
╠═══════════════════════════════════════════════════════════╣
║  ?           Quick help (this)                            ║
║  HELP        Full command reference                       ║
║  AL          List all aliases                             ║
║  RF          Refresh panels                               ║
╠───────────────────────────────────────────────────────────╣
║  F <text>    Search                                       ║
║  SU [ALL]    Show units                                   ║
║  SI [OPEN]   Show incidents                               ║
║  VA          View all units                               ║
║  VS A        View shift A                                 ║
╠───────────────────────────────────────────────────────────╣
║  NEW         Create incident                              ║
║  D <#> E1    Dispatch Engine1 to incident                 ║
║  E1 D        Dispatch Engine1 (pick incident)             ║
║  E1 E        Enroute                                      ║
║  E1 A        Arrived                                      ║
║  E1 C        Clear (prompts disposition)                  ║
╠───────────────────────────────────────────────────────────╣
║  E1 R: text  Add remark                                   ║
║  DL: text    Daily log entry                              ║
║  ED <#> R    Event disposition (R=Resolved)               ║
║  CLOSE <#>   Close incident                               ║
╚═══════════════════════════════════════════════════════════╝
`.trim();
        this._showHelp(text, "Quick Reference");
    },

    _fullHelp() {
        const text = `
═══════════════════════════════════════════════════════════════
                    FORD CAD COMMAND LINE
═══════════════════════════════════════════════════════════════

HELP & SYSTEM
  ?                        Quick cheat sheet
  HELP, H                  Full help (this)
  AL, ALIASES              List all command aliases
  RF, REFRESH              Refresh all panels
  ESC, X                   Close modal

SEARCH & SHOW
  F <text>                 Search all records
  SU                       Show units (current shift)
  SU ALL                   Show all units
  SU A|B|C|D               Show shift units
  SI                       Show incidents
  SI OPEN|ACTIVE|HELD      Filter incidents
  SHOW <unit>              Show unit details
  SHOW <#>                 Show incident details

SESSION & SHIFT VIEW
  VA                       View all units (all shifts)
  VS A|B|C|D               View specific shift
  SHIFT AUTO               Auto-detect shift
  SHIFT A|B|C|D            Force shift view

COVERAGE MANAGEMENT
  COV+ <unit>              Add unit to coverage
  COV- <unit>              Remove from coverage
  COVL                     List coverage overrides

INCIDENT LIFECYCLE
  NEW                      Create new incident
  NEW EMS                  Create EMS incident
  HOLD <#>: reason         Hold incident (reason required)
  UNHOLD <#>               Resume held incident
  ED <#> <code>            Event disposition
  CLOSE <#>                Close incident (requires ED)

DISPATCH & ASSIGNMENT
  D <#> E1 M1              Dispatch units to incident
  E1 D                     Dispatch E1 (opens picker)
  E1 D <#>                 Dispatch E1 to specific incident
  E1,M1 D <#>              Dispatch multiple units
  UA E1 <#>                Unassign unit from incident

UNIT STATUS
  E1 E                     ENROUTE (E, ENR, ER)
  E1 A                     ARRIVED (A, ARR, OS)
  E1 OPR                   OPERATING (OPR, OP)
  E1 T                     TRANSPORTING (T, TR, TRN)
  E1 M                     AT MEDICAL (M, MED)
  E1 AV                    AVAILABLE (AV, AVL, 10-8)
  E1 O                     OUT OF SERVICE (O, OOS, 10-7)
  ST E1 ENR                Generic status set

CLEARING & DISPOSITIONS
  E1 C                     Clear unit (prompts UD)
  CA <#>                   Clear all units on incident
  UD E1 R                  Unit dispo: R|NA|NF|C|CT|O
  ED <#> R                 Event dispo: R|FA|NF|T|CT|PRTT|C|O

REMARKS & DAILY LOG
  E1 R: text               Remark (to incident if assigned)
  E1 AR: text              Same as above
  DL: entry text           Add daily log entry
  DLS                      Show daily log

CREW & ROSTER
  CA+ 17 TO E1             Assign person to apparatus
  CA- 17 FROM E1           Remove from apparatus
  CS E1                    Show crew on apparatus
  AU 17                    Add unit to shift
  DU 17                    Remove unit from shift

UNIT ALIASES
  Units can use aliases: e1, eng1 → Engine1
  Type AL to see all configured aliases

DISPOSITION CODES
  Unit: R (Resolved), NA, NF, C, CT, O (Other)
  Event: R, FA (False Alarm), NF, T, CT, PRTT, C, O

═══════════════════════════════════════════════════════════════
`.trim();
        this._showHelp(text, "Command Reference");
    },

    _showAliases() {
        let text = "═══════════════════════════════════════\n";
        text += "        COMMAND ALIASES\n";
        text += "═══════════════════════════════════════\n\n";

        for (const cmd of this.COMMANDS) {
            text += `${cmd.key}:\n  ${cmd.aliases.join(", ")}\n\n`;
        }

        text += "═══════════════════════════════════════\n";
        text += "        UNIT ALIASES\n";
        text += "═══════════════════════════════════════\n\n";

        // Group aliases by unit
        const byUnit = {};
        for (const [alias, unitId] of Object.entries(this._aliasMap)) {
            if (alias.toLowerCase() !== unitId.toLowerCase()) {
                if (!byUnit[unitId]) byUnit[unitId] = [];
                byUnit[unitId].push(alias);
            }
        }

        for (const [unitId, aliases] of Object.entries(byUnit).sort()) {
            text += `${unitId}: ${aliases.join(", ")}\n`;
        }

        this._showHelp(text, "Aliases");
    },

    _showHelp(text, title) {
        if (window.CAD_MODAL?.openText) {
            window.CAD_MODAL.openText(text, title);
        } else {
            alert(text);
        }
    },

    // ========================================================================
    // ACTION HANDLERS
    // ========================================================================

    // --- Dispatch ---
    async openIncidentPicker(units, mode) {
        // Get incidents from all panels (active, open, held)
        const activeRows = document.querySelectorAll("#panel-active tr[data-row-num]");
        const openRows = document.querySelectorAll("#panel-open tr[data-row-num]");
        const heldRows = document.querySelectorAll("#panel-held tr[data-row-num]");

        const totalIncidents = activeRows.length + openRows.length + heldRows.length;

        if (totalIncidents === 0) {
            this._toast("No incidents. Create one with NEW first.", "error");
            return;
        }

        // If only one incident total, dispatch directly without picker
        if (totalIncidents === 1) {
            const row = activeRows[0] || openRows[0] || heldRows[0];
            const incidentId = row?.dataset?.incidentId;
            if (incidentId) {
                this._pending = {
                    units: this._asUnitList(units),
                    mode: String(mode || "D").toUpperCase(),
                };
                await this.pickIncident(incidentId);
                return;
            }
        }

        // Multiple incidents - show picker modal or tell user to specify
        const unitStr = this._asUnitList(units).join(", ");
        let msg = `Specify incident # for ${unitStr}:\n`;

        if (activeRows.length > 0) {
            msg += `  Active: 1-${activeRows.length}\n`;
        }
        if (openRows.length > 0) {
            msg += `  Open: o1-o${openRows.length}\n`;
        }
        if (heldRows.length > 0) {
            msg += `  Held: h1-h${heldRows.length}\n`;
        }
        msg += `Example: ${units[0] || 'E1'} D 1`;

        this._toast(msg, "info");
    },

    async pickIncident(incidentId) {
        const pending = this._pending;
        if (!pending || !pending.units?.length) {
            this._toast("CLI picker state missing.", "error");
            return;
        }

        try {
            const res = await CAD_UTIL.postJSON("/api/cli/dispatch", {
                incident_id: Number(incidentId),
                units: pending.units,
                mode: pending.mode,
            });

            if (res?.ok === false) {
                this._toast(res?.error || "Dispatch rejected.", "error");
                return;
            }

            CAD_MODAL.close();
            CAD_UTIL.refreshPanels();

            // Don't auto-open IAW after dispatch - user can click incident if needed
            this._clearPending();
            this._toast("Dispatched", "success");
        } catch (err) {
            console.error("[CLI] pickIncident failed:", err);
            this._toast(err?.message || "Dispatch failed.", "error");
        }
    },

    _clearPending() {
        this._pending = null;
        this._incidentChoices = [];
        const input = document.getElementById("cmd-input");
        if (input) input.placeholder = "Command...";
    },

    async _dispatchToIncident(units, incidentRef, mode = "D") {
        try {
            let resolvedRef = this._normalizeIncidentRef(incidentRef);

            // Check if it's a row number reference (1, 2, o1, o2)
            if (/^o?\d+$/i.test(resolvedRef)) {
                const incidentId = this._resolveRowNumber(resolvedRef);
                if (!incidentId) {
                    this._toast(`No incident at row ${incidentRef}. Check the incidents panel.`, "error");
                    return;
                }
                resolvedRef = incidentId;
            }

            const res = await CAD_UTIL.postJSON("/api/cli/dispatch", {
                incident_ref: resolvedRef,
                units: this._asUnitList(units),
                mode,
            });

            if (res?.ok === false) {
                this._toast(res?.error || "Dispatch rejected.", "error");
                return;
            }

            CAD_UTIL.refreshPanels();
            this._toast("Dispatched", "success");
            // Don't auto-open IAW after dispatch
        } catch (err) {
            console.error("[CLI] dispatch failed:", err);
            this._toast(err?.message || "Dispatch failed.", "error");
        }
    },

    // --- Status ---
    async _setStatusForUnits(units, status) {
        const list = this._asUnitList(units);
        for (const u of list) {
            try {
                const ctx = await CAD_UTIL.getJSON(`/api/uaw/context/${encodeURIComponent(u)}`);
                const incId = Number(ctx?.active_incident_id || 0);
                if (!incId) {
                    this._toast(`${u} is not on an active incident.`, "error");
                    continue;
                }
                await CAD_UTIL.postJSON(`/incident/${incId}/unit/${encodeURIComponent(u)}/status`, { status });
                this._toast(`${u} → ${status}`, "success");
            } catch (err) {
                console.error(`[CLI] Status failed for ${u}:`, err);
                this._toast(err?.message || `Status failed for ${u}.`, "error");
            }
        }
        CAD_UTIL.refreshPanels();
    },

    async _setUnitAvailable(units) {
        const list = this._asUnitList(units);
        for (const u of list) {
            try {
                await CAD_UTIL.postJSON(`/api/unit_status/${encodeURIComponent(u)}/AVAILABLE`);
                this._toast(`${u} → AVAILABLE`, "success");
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
                this._toast(`${u} → OOS`, "success");
            } catch (err) {
                console.error(`[CLI] OOS failed for ${u}:`, err);
            }
        }
        CAD_UTIL.refreshPanels();
    },

    // --- Coverage ---
    async _addUnitToCoverage(units) {
        const list = this._asUnitList(units);
        for (const u of list) {
            try {
                const res = await CAD_UTIL.postJSON("/api/shift_override/start", {
                    unit_id: u,
                    reason: "CLI"
                });
                if (res?.ok === false) {
                    this._toast(res?.error || `Add unit failed: ${u}`, "error");
                } else {
                    this._toast(`${u} added to coverage`, "success");
                }
            } catch (err) {
                console.error(`[CLI] Add unit failed: ${u}`, err);
                this._toast(err?.message || `Add unit failed: ${u}`, "error");
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
                    this._toast(res?.error || `Remove unit failed: ${u}`, "error");
                } else {
                    this._toast(`${u} removed from coverage`, "success");
                }
            } catch (err) {
                console.error(`[CLI] Remove unit failed: ${u}`, err);
            }
        }
        CAD_UTIL.refreshPanels();
    },

    // --- Clear ---
    async _clearUnit(units) {
        const list = this._asUnitList(units);
        for (const u of list) {
            try {
                // Use openForClear which works from CLI (no row anchor needed)
                if (window.UAW?.openForClear) {
                    await window.UAW.openForClear(u);
                } else {
                    // Fallback: just show toast if UAW not available
                    this._toast(`Cannot open clear dialog for ${u}`, "error");
                }
            } catch (err) {
                console.error(`[CLI] Clear failed for ${u}:`, err);
            }
        }
    },

    // --- Remarks ---
    async _addRemark(units, text) {
        const list = this._asUnitList(units);
        for (const u of list) {
            try {
                const res = await CAD_UTIL.postJSON("/remark", { unit_id: u, text });
                if (res?.ok === false) {
                    this._toast(res?.error || `Remark failed: ${u}`, "error");
                } else {
                    this._toast("Remark added", "success");
                }
            } catch (err) {
                console.error(`[CLI] Remark failed: ${u}`, err);
                this._toast(err?.message || `Remark failed: ${u}`, "error");
            }
        }
        CAD_UTIL.refreshPanels();
    },

    // --- Daily Log ---
    async _addDailyLog(text, unitId = null) {
        try {
            const body = { details: text, category: "REMARK" };
            if (unitId) body.unit_id = unitId;

            const res = await fetch("/api/dailylog", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body)
            });

            if (res.ok) {
                this._toast("Daily log entry added", "success");
            } else {
                this._toast("Failed to add log entry", "error");
            }
        } catch (err) {
            console.error("[CLI] Daily log failed:", err);
            this._toast("Daily log failed", "error");
        }
    },

    // --- Crew ---
    async _assignCrew(personnelId, apparatusId) {
        try {
            const res = await CAD_UTIL.postJSON("/api/crew/assign", {
                apparatus_id: apparatusId,
                personnel_id: personnelId
            });
            if (res?.ok === false) {
                this._toast(res?.error || "Crew assign failed.", "error");
            } else {
                this._toast(`${personnelId} → ${apparatusId}`, "success");
            }
        } catch (err) {
            console.error("[CLI] Crew assign failed:", err);
            this._toast(err?.message || "Crew assign failed.", "error");
        }
        CAD_UTIL.refreshPanels();
    },

    async _unassignCrew(personnelId, apparatusId = null) {
        try {
            if (!apparatusId) {
                const ctx = await CAD_UTIL.getJSON(`/api/uaw/context/${encodeURIComponent(personnelId)}`);
                apparatusId = ctx?.current_apparatus;
            }
            if (!apparatusId) {
                this._toast(`${personnelId} is not assigned to an apparatus.`, "error");
                return;
            }
            const res = await CAD_UTIL.postJSON("/api/crew/unassign", {
                apparatus_id: apparatusId,
                personnel_id: personnelId
            });
            if (res?.ok === false) {
                this._toast(res?.error || "Crew unassign failed.", "error");
            } else {
                this._toast(`${personnelId} removed from ${apparatusId}`, "success");
            }
        } catch (err) {
            console.error("[CLI] Crew unassign failed:", err);
        }
        CAD_UTIL.refreshPanels();
    },

    // --- Dispositions ---
    async _unitDisposition(unitId, code) {
        const codeUpper = code.toUpperCase();
        if (!this.UNIT_DISPO_CODES[codeUpper]) {
            this._toast(`Invalid unit dispo code: ${code}. Valid: ${Object.keys(this.UNIT_DISPO_CODES).join(", ")}`, "error");
            return;
        }

        try {
            const ctx = await CAD_UTIL.getJSON(`/api/uaw/context/${encodeURIComponent(unitId)}`);
            const incId = Number(ctx?.active_incident_id || 0);
            if (!incId) {
                this._toast(`${unitId} is not on an incident.`, "error");
                return;
            }

            await CAD_UTIL.postJSON(`/incident/${incId}/unit/${encodeURIComponent(unitId)}/disposition`, {
                disposition: codeUpper
            });
            this._toast(`${unitId} disposition: ${codeUpper}`, "success");
            CAD_UTIL.refreshPanels();
        } catch (err) {
            console.error("[CLI] Unit dispo failed:", err);
            this._toast(err?.message || "Unit disposition failed.", "error");
        }
    },

    async _eventDisposition(incidentRef, code) {
        const codeUpper = code.toUpperCase();
        if (!this.EVENT_DISPO_CODES[codeUpper]) {
            this._toast(`Invalid event dispo code: ${code}. Valid: ${Object.keys(this.EVENT_DISPO_CODES).join(", ")}`, "error");
            return;
        }

        const incId = this._normalizeIncidentRef(incidentRef);
        try {
            await CAD_UTIL.postJSON(`/incident/${incId}/event_disposition`, {
                disposition: codeUpper
            });
            this._toast(`Incident ${incId} disposition: ${codeUpper}`, "success");
            CAD_UTIL.refreshPanels();
        } catch (err) {
            console.error("[CLI] Event dispo failed:", err);
            this._toast(err?.message || "Event disposition failed.", "error");
        }
    },

    // --- View Modes ---
    async _setViewMode(mode) {
        try {
            await CAD_UTIL.postJSON("/api/session/roster_view_mode", { mode: mode.toUpperCase() });
            CAD_UTIL.refreshPanels();
            this._toast(`View: ${mode}`, "success");
        } catch (err) {
            console.error("[CLI] Set view mode failed:", err);
        }
    },

    // ========================================================================
    // MAIN EXECUTE
    // ========================================================================
    async execute(command) {
        const tokens = this._tokenize(command);
        if (!tokens.length) return;

        const first = tokens[0] || "";
        const firstCmd = this._matchCommand(first);

        // ────────────────────────────────────────────────────────────────────
        // SYSTEM COMMANDS (no unit prefix)
        // ────────────────────────────────────────────────────────────────────
        if (firstCmd === "QUICK_HELP") {
            this._quickHelp();
            return;
        }

        if (firstCmd === "HELP") {
            this._fullHelp();
            return;
        }

        if (firstCmd === "ALIASES") {
            this._showAliases();
            return;
        }

        if (firstCmd === "REFRESH") {
            CAD_UTIL.refreshPanels();
            this._toast("Refreshed", "success");
            return;
        }

        if (firstCmd === "CLOSE_MODAL") {
            CAD_MODAL.close();
            return;
        }

        // ────────────────────────────────────────────────────────────────────
        // VIEW COMMANDS
        // ────────────────────────────────────────────────────────────────────
        if (firstCmd === "VIEW_ALL") {
            await this._setViewMode("ALL");
            return;
        }

        if (firstCmd === "VIEW_SHIFT") {
            const shift = (tokens[1] || "").toUpperCase();
            if (["A", "B", "C", "D"].includes(shift)) {
                await this._setViewMode(shift);
            } else {
                await this._setViewMode("CURRENT");
            }
            return;
        }

        if (firstCmd === "SHIFT") {
            const shift = (tokens[1] || "AUTO").toUpperCase();
            if (shift === "AUTO") {
                await this._setViewMode("CURRENT");
            } else if (["A", "B", "C", "D"].includes(shift)) {
                await this._setViewMode(shift);
            }
            return;
        }

        if (firstCmd === "SHOW_UNITS") {
            const filter = (tokens[1] || "").toUpperCase();
            if (filter === "ALL") {
                await this._setViewMode("ALL");
            } else if (["A", "B", "C", "D"].includes(filter)) {
                await this._setViewMode(filter);
            }
            document.getElementById("panel-units")?.scrollIntoView({ behavior: "smooth" });
            return;
        }

        if (firstCmd === "SHOW_INCIDENTS") {
            const filter = (tokens[1] || "").toUpperCase();
            if (filter === "HELD") {
                CAD_MODAL.open("/panel/held");
            } else {
                document.getElementById("panel-active")?.scrollIntoView({ behavior: "smooth" });
            }
            return;
        }

        if (firstCmd === "SHOW") {
            const target = tokens[1];
            if (target) {
                if (this._isIncidentRef(target)) {
                    IAW.open(this._normalizeIncidentRef(target));
                } else {
                    UAW.open(this.resolveAlias(target));
                }
            }
            return;
        }

        if (firstCmd === "FIND") {
            const query = tokens.slice(1).join(" ");
            if (query) {
                window.location.href = `/history?q=${encodeURIComponent(query)}`;
            } else {
                CAD_MODAL.open("/history");
            }
            return;
        }

        if (firstCmd === "VIEW_HELD") {
            CAD_MODAL.open("/panel/held");
            return;
        }

        if (firstCmd === "VIEW_ACTIVE") {
            document.getElementById("panel-active")?.scrollIntoView({ behavior: "smooth" });
            return;
        }

        if (firstCmd === "VIEW_DAILY" || firstCmd === "DAILY_LOG_SHOW") {
            CAD_MODAL.open("/modals/dailylog");
            return;
        }

        if (firstCmd === "VIEW_HISTORY") {
            CAD_MODAL.open("/history");
            return;
        }

        if (firstCmd === "SEND_REPORT") {
            // Trigger manual report via ReportConfirm module
            if (window.ReportConfirm && window.ReportConfirm.triggerManualReport) {
                window.ReportConfirm.triggerManualReport();
            } else {
                TOAST.error("Report module not loaded");
            }
            return;
        }

        if (firstCmd === "VIEW_IAW") {
            if (tokens[1]) IAW.open(this._normalizeIncidentRef(tokens[1]));
            return;
        }

        if (firstCmd === "VIEW_UAW") {
            if (tokens[1]) UAW.open(this.resolveAlias(tokens[1]));
            return;
        }

        // ────────────────────────────────────────────────────────────────────
        // INCIDENT LIFECYCLE
        // ────────────────────────────────────────────────────────────────────
        if (firstCmd === "NEW_INCIDENT") {
            if (window.CALLTAKER?.newCall) {
                window.CALLTAKER.newCall();
            } else {
                CAD_MODAL.open("/calltaker");
            }
            return;
        }

        if (firstCmd === "HOLD_INCIDENT") {
            const incId = this._normalizeIncidentRef(tokens[1]);
            const reason = tokens.slice(2).join(" ") || "Held via CLI";
            if (incId) {
                try {
                    await CAD_UTIL.postJSON(`/incident/${incId}/hold`, { reason });
                    CAD_UTIL.refreshPanels();
                    this._toast(`Incident ${incId} held`, "success");
                } catch (err) {
                    this._toast(err?.message || "Hold failed.", "error");
                }
            }
            return;
        }

        if (firstCmd === "UNHOLD_INCIDENT") {
            const incId = this._normalizeIncidentRef(tokens[1]);
            if (incId) {
                try {
                    await CAD_UTIL.postJSON(`/incident/${incId}/unhold`);
                    CAD_UTIL.refreshPanels();
                    this._toast(`Incident ${incId} resumed`, "success");
                } catch (err) {
                    this._toast(err?.message || "Unhold failed.", "error");
                }
            }
            return;
        }

        if (firstCmd === "CLOSE_INCIDENT") {
            const incId = this._normalizeIncidentRef(tokens[1]);
            if (incId) {
                try {
                    await CAD_UTIL.postJSON(`/incident/${incId}/close`);
                    CAD_UTIL.refreshPanels();
                    this._toast(`Incident ${incId} closed`, "success");
                } catch (err) {
                    this._toast(err?.message || "Close failed.", "error");
                }
            }
            return;
        }

        // ────────────────────────────────────────────────────────────────────
        // DISPOSITIONS
        // ────────────────────────────────────────────────────────────────────
        if (firstCmd === "UNIT_DISPO") {
            const unitId = this.resolveAlias(tokens[1]);
            const code = tokens[2];
            if (unitId && code) {
                await this._unitDisposition(unitId, code);
            } else {
                this._toast("Usage: UD <unit> <code>", "error");
            }
            return;
        }

        if (firstCmd === "EVENT_DISPO") {
            const incId = tokens[1];
            const code = tokens[2];
            if (incId && code) {
                await this._eventDisposition(incId, code);
            } else {
                this._toast("Usage: ED <#> <code>", "error");
            }
            return;
        }

        // ────────────────────────────────────────────────────────────────────
        // DAILY LOG
        // ────────────────────────────────────────────────────────────────────
        if (firstCmd === "DAILY_LOG") {
            const text = tokens.slice(1).join(" ");
            if (text) {
                await this._addDailyLog(text);
            } else {
                CAD_MODAL.open("/modals/dailylog");
            }
            return;
        }

        // ────────────────────────────────────────────────────────────────────
        // COVERAGE
        // ────────────────────────────────────────────────────────────────────
        if (firstCmd === "COV_ADD") {
            const unitId = this.resolveAlias(tokens[1]);
            if (unitId) {
                await this._addUnitToCoverage([unitId]);
            }
            return;
        }

        if (firstCmd === "COV_REMOVE") {
            const unitId = this.resolveAlias(tokens[1]);
            if (unitId) {
                await this._removeUnitFromCoverage([unitId]);
            }
            return;
        }

        if (firstCmd === "COV_LIST") {
            // TODO: Show coverage overrides modal
            this._toast("Coverage list not yet implemented", "info");
            return;
        }

        // ────────────────────────────────────────────────────────────────────
        // CREW MANAGEMENT
        // ────────────────────────────────────────────────────────────────────
        if (firstCmd === "CREW_ADD") {
            // CA+ <person> TO <apparatus>
            const personId = this.resolveAlias(tokens[1]);
            const toIdx = tokens.findIndex(t => t.toUpperCase() === "TO");
            const appId = toIdx > 0 ? this.resolveAlias(tokens[toIdx + 1]) : null;
            if (personId && appId) {
                await this._assignCrew(personId, appId);
            } else {
                this._toast("Usage: CA+ <person> TO <apparatus>", "error");
            }
            return;
        }

        if (firstCmd === "CREW_REMOVE") {
            // CA- <person> FROM <apparatus>
            const personId = this.resolveAlias(tokens[1]);
            const fromIdx = tokens.findIndex(t => t.toUpperCase() === "FROM");
            const appId = fromIdx > 0 ? this.resolveAlias(tokens[fromIdx + 1]) : null;
            await this._unassignCrew(personId, appId);
            return;
        }

        if (firstCmd === "CREW_SHOW") {
            const appId = this.resolveAlias(tokens[1]);
            if (appId) {
                UAW.open(appId);
            }
            return;
        }

        // ────────────────────────────────────────────────────────────────────
        // INCIDENT-FIRST DISPATCH: D <#> <units>
        // ────────────────────────────────────────────────────────────────────
        if (firstCmd === "DISPATCH" && tokens[1] && this._isIncidentRef(tokens[1])) {
            const incRef = tokens[1];
            const units = tokens.slice(2);
            if (units.length) {
                await this._dispatchToIncident(units, incRef, "D");
            } else {
                this._toast("Usage: D <#> <unit> [unit...]", "error");
            }
            return;
        }

        // ────────────────────────────────────────────────────────────────────
        // STATUS GENERIC: ST <unit> <status>
        // ────────────────────────────────────────────────────────────────────
        if (firstCmd === "STATUS") {
            const unitId = this.resolveAlias(tokens[1]);
            const status = (tokens[2] || "").toUpperCase();
            if (unitId && status) {
                // Map short codes to full status
                const statusMap = {
                    "AVL": "AVAILABLE", "AV": "AVAILABLE", "A": "AVAILABLE",
                    "ENR": "ENROUTE", "EN": "ENROUTE", "ER": "ENROUTE",
                    "ARR": "ARRIVED", "OS": "ARRIVED", "ONS": "ARRIVED",
                    "OPR": "OPERATING", "OP": "OPERATING",
                    "TRN": "TRANSPORTING", "TX": "TRANSPORTING", "TR": "TRANSPORTING",
                    "BUSY": "BUSY", "ACT": "BUSY",
                    "M": "AT_MEDICAL", "MED": "AT_MEDICAL",
                    "OOS": "OOS", "OUT": "OOS"
                };
                const fullStatus = statusMap[status] || status;
                await this._setStatusForUnits([unitId], fullStatus);
            } else {
                this._toast("Usage: ST <unit> <status>", "error");
            }
            return;
        }

        // ────────────────────────────────────────────────────────────────────
        // UNIT-PREFIXED COMMANDS: <unit(s)> <action> [args...]
        // ────────────────────────────────────────────────────────────────────
        const rawUnits = [];
        let i = 0;

        while (i < tokens.length && this._looksLikeUnit(tokens[i])) {
            rawUnits.push(tokens[i]);
            i++;
        }

        if (!rawUnits.length) {
            console.warn("[CLI] Unknown command:", command);
            this._toast(`Unknown command: ${command}\nType ? for help.`, "error");
            return;
        }

        const units = this.resolveAliases(rawUnits);
        const actionTok = tokens[i] || "";
        const action = this._matchCommand(actionTok);
        const rest = tokens.slice(i + 1);

        if (!action) {
            console.warn("[CLI] Unknown action:", command);
            this._toast(`Unknown action: ${actionTok}\nType ? for help.`, "error");
            return;
        }

        // --- Dispatch ---
        if (action === "DISPATCH" || action === "DISPATCH_ENROUTE") {
            const mode = (action === "DISPATCH_ENROUTE") ? "DE" : "D";
            const ref = (rest[0] && this._isIncidentRef(rest[0])) ? rest[0] : "";

            if (ref) {
                await this._dispatchToIncident(units, ref, mode);
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

        if (action === "OPERATING") {
            await this._setStatusForUnits(units, "OPERATING");
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

        if (action === "BUSY") {
            await this._setStatusForUnits(units, "BUSY");
            return;
        }

        if (action === "OOS") {
            await this._setUnitOOS(units);
            return;
        }

        // --- Clear Unit ---
        if (action === "CLEAR") {
            await this._clearUnit(units);
            return;
        }

        // --- Add/Remove Unit from Shift ---
        if (action === "ADD_UNIT") {
            await this._addUnitToCoverage(units);
            return;
        }

        if (action === "DEL_UNIT") {
            await this._removeUnitFromCoverage(units);
            return;
        }

        // --- Remarks ---
        if (action === "ADD_REMARK") {
            const text = rest.join(" ").trim();
            if (!text) {
                this._toast("Usage: <unit> R: <text>", "error");
                return;
            }
            await this._addRemark(units, text);
            return;
        }

        // --- Crew Assignment ---
        if (action === "CREW_ADD") {
            const toIdx = rest.findIndex(t => t.toUpperCase() === "TO");
            const appId = toIdx >= 0 ? this.resolveAlias(rest[toIdx + 1]) : rest[0];
            if (appId) {
                await this._assignCrew(units[0], appId);
            }
            return;
        }

        if (action === "CREW_REMOVE") {
            await this._unassignCrew(units[0]);
            return;
        }

        // --- Unit Disposition ---
        if (action === "UNIT_DISPO") {
            const code = rest[0];
            if (code) {
                await this._unitDisposition(units[0], code);
            }
            return;
        }

        // --- View unit's incident ---
        if (action === "VIEW_IAW") {
            const u = units[0];
            const ctx = await CAD_UTIL.getJSON(`/api/uaw/context/${encodeURIComponent(u)}`);
            const incId = Number(ctx?.active_incident_id || 0);
            if (!incId) {
                this._toast(`${u} is not on an active incident.`, "error");
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
        this._toast(`Action not yet implemented: ${action}`, "error");
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
window.CAD.cli.refreshAliases = () => CLI._loadAliases();


export default CLI;

// Command hints click handler
document.addEventListener("click", (e) => {
    const hint = e.target.closest(".cmd-hint");
    if (!hint) return;

    const input = document.getElementById("cmd-input");
    if (!input) return;

    const cmd = hint.textContent.trim();
    input.value = cmd;
    input.focus();

    if (!cmd.includes(" ") && ["NEW", "HELD", "DAILY", "HELP", "HISTORY", "REPORT", "?"].includes(cmd.toUpperCase())) {
        const event = new KeyboardEvent("keydown", { key: "Enter" });
        input.dispatchEvent(event);
    }
});
