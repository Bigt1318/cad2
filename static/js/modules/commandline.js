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
    _cmdHistory: [],     // Command history ring buffer
    _historyIdx: -1,     // Current position in history (-1 = new input)
    _historyDraft: "",   // Saved draft when browsing history

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
        { key: "SHOW_INCIDENTS", aliases: ["SHI", "SHOWINCIDENTS"], desc: "Show incidents: SHI [OPEN|ACTIVE|HELD]" },
        { key: "SELF_INITIATE", aliases: ["SI", "SELFINIT"], desc: "Self-initiate: <unit> SI [type]" },
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

        // ─────────────────────────────────────────────────────────────────────
        // DISPATCH & ASSIGNMENT
        // ─────────────────────────────────────────────────────────────────────
        { key: "DISPATCH", aliases: ["D", "DSP", "DISP", "DISPATCH", "SEND"], desc: "Dispatch: D <#> <units>" },
        { key: "DISPATCH_ENROUTE", aliases: ["DE", "D/E"], desc: "Dispatch + Enroute" },
        { key: "UNASSIGN", aliases: ["UA", "UNASSIGN", "RM"], desc: "Unassign unit: UA <unit> <#>" },
        { key: "MOVE_UNIT", aliases: ["MOVE", "MV"], desc: "Move unit: MOVE <unit> TO <#>" },
        { key: "SWAP_UNITS", aliases: ["SWAP", "SW"], desc: "Swap assignments: SWAP <unit1> <unit2>" },
        { key: "NOTE", aliases: ["NOTE", "NT"], desc: "Add note to incident: NOTE <#> <text>" },
        { key: "TRANSFER_CMD", aliases: ["TC", "TRANSFERCMD", "XFERCMD"], desc: "Transfer command: TC <unit>" },
        { key: "SCHEDULE", aliases: ["SCHED", "SCHEDULE", "DELAY"], desc: "Schedule incident: SCHED <#> <HH:MM>" },
        { key: "ASSIGNED", aliases: ["ASG", "ASSIGNED"], desc: "List assigned: ASG <#>" },

        // ─────────────────────────────────────────────────────────────────────
        // UNIT STATUS (Generic + Specific)
        // ─────────────────────────────────────────────────────────────────────
        { key: "STATUS", aliases: ["ST"], desc: "Set status: ST <unit> <status>" },
        { key: "ENROUTE", aliases: ["E", "ENR", "ENROUTE", "ENRT", "ER", "RESPONDING"], desc: "Set ENROUTE" },
        { key: "ARRIVED", aliases: ["A", "ARR", "ARRIVE", "ARRIVED", "OS", "ONSCENE", "ONS", "10-23", "1023"], desc: "Set ARRIVED" },
        { key: "AT_APPARATUS", aliases: ["AA", "ATAPP", "AT_APP", "STATION", "STA", "QTR", "QUARTERS"], desc: "Set AT APPARATUS (station)" },
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

        // ─────────────────────────────────────────────────────────────────────
        // MESSAGING
        // ─────────────────────────────────────────────────────────────────────
        { key: "MESSAGE", aliases: ["MSG", "MESSAGE", "DM"], desc: "Message unit: MSG <unit>" },
        { key: "CHAT", aliases: ["CHAT"], desc: "Toggle messaging drawer" },
        { key: "BROADCAST_MSG", aliases: ["BCAST", "BROADCAST"], desc: "Open broadcast console" },
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
            // Command history: Up/Down arrows
            if (e.key === "ArrowUp") {
                e.preventDefault();
                if (this._cmdHistory.length === 0) return;
                if (this._historyIdx === -1) {
                    this._historyDraft = input.value;
                    this._historyIdx = this._cmdHistory.length - 1;
                } else if (this._historyIdx > 0) {
                    this._historyIdx--;
                }
                input.value = this._cmdHistory[this._historyIdx] || "";
                return;
            }
            if (e.key === "ArrowDown") {
                e.preventDefault();
                if (this._historyIdx === -1) return;
                if (this._historyIdx < this._cmdHistory.length - 1) {
                    this._historyIdx++;
                    input.value = this._cmdHistory[this._historyIdx] || "";
                } else {
                    this._historyIdx = -1;
                    input.value = this._historyDraft;
                }
                return;
            }

            // Tab = accept autocomplete
            if (e.key === "Tab" && this._acDropdown?.style.display !== "none") {
                e.preventDefault();
                const active = this._acDropdown.querySelector(".cli-ac-item.active") || this._acDropdown.querySelector(".cli-ac-item");
                if (active) {
                    const tokens = input.value.split(/[\s,]+/);
                    tokens[0] = active.dataset.key;
                    input.value = tokens.join(" ") + " ";
                    this._acDropdown.style.display = "none";
                }
                return;
            }

            // Escape = dismiss autocomplete
            if (e.key === "Escape" && this._acDropdown?.style.display !== "none") {
                e.preventDefault();
                this._acDropdown.style.display = "none";
                return;
            }

            if (e.key !== "Enter") return;
            e.preventDefault();

            // Hide autocomplete on execute
            if (this._acDropdown) this._acDropdown.style.display = "none";

            const cmd = (input.value || "").trim();
            if (!cmd) return;

            // Save to history (avoid consecutive duplicates)
            if (this._cmdHistory.length === 0 || this._cmdHistory[this._cmdHistory.length - 1] !== cmd) {
                this._cmdHistory.push(cmd);
                if (this._cmdHistory.length > 50) this._cmdHistory.shift();
            }
            this._historyIdx = -1;
            this._historyDraft = "";

            this.execute(cmd).catch((err) => {
                console.error("[CLI] Execute failed:", err);
                this._toast(err?.message || "Command failed.", "error");
            });

            input.value = "";
        });

        // Initialize autocomplete dropdown
        this._initAutocomplete();

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

    _levenshtein(a, b) {
        const m = a.length, n = b.length;
        const dp = Array.from({length: m + 1}, (_, i) => Array(n + 1).fill(0));
        for (let i = 0; i <= m; i++) dp[i][0] = i;
        for (let j = 0; j <= n; j++) dp[0][j] = j;
        for (let i = 1; i <= m; i++)
            for (let j = 1; j <= n; j++)
                dp[i][j] = a[i - 1] === b[j - 1] ? dp[i - 1][j - 1] : 1 + Math.min(dp[i - 1][j - 1], dp[i - 1][j], dp[i][j - 1]);
        return dp[m][n];
    },

    _matchCommand(tok) {
        const t = String(tok || "").trim().toUpperCase().replace(/-/g, "");
        if (!t) return null;

        // Exact match first
        for (const cmd of this.COMMANDS) {
            for (const alias of cmd.aliases) {
                if (alias.toUpperCase().replace(/-/g, "") === t) return cmd.key;
            }
        }

        // Fuzzy match: find best match with edit distance <= 2 (for tokens >= 3 chars)
        if (t.length >= 3) {
            let bestKey = null, bestDist = Infinity;
            for (const cmd of this.COMMANDS) {
                for (const alias of cmd.aliases) {
                    const a = alias.toUpperCase().replace(/-/g, "");
                    const d = this._levenshtein(t, a);
                    if (d < bestDist && d <= 2) {
                        bestDist = d;
                        bestKey = cmd.key;
                    }
                }
            }
            if (bestKey) return bestKey;
        }

        // Prefix match: if token is a prefix of any alias (3+ chars)
        if (t.length >= 3) {
            for (const cmd of this.COMMANDS) {
                for (const alias of cmd.aliases) {
                    if (alias.toUpperCase().startsWith(t)) return cmd.key;
                }
            }
        }

        return null;
    },

    _asUnitList(units) {
        return (units || []).map((u) => this.resolveAlias(String(u).trim())).filter(Boolean);
    },

    // ========================================================================
    // AUTOCOMPLETE SYSTEM
    // ========================================================================
    _initAutocomplete() {
        const input = document.getElementById("cmd-input");
        if (!input) return;

        // Create dropdown element
        const dropdown = document.createElement("div");
        dropdown.id = "cli-autocomplete";
        dropdown.className = "cli-autocomplete-dropdown";
        dropdown.style.display = "none";
        input.parentElement.style.position = "relative";
        input.parentElement.appendChild(dropdown);

        // Inject styles
        if (!document.getElementById("cli-ac-styles")) {
            const style = document.createElement("style");
            style.id = "cli-ac-styles";
            style.textContent = `
                .cli-autocomplete-dropdown {
                    position: absolute; bottom: 100%; left: 0; right: 0;
                    background: #0d1926; border: 1px solid #2a3a52; border-radius: 4px;
                    max-height: 200px; overflow-y: auto; z-index: 9999;
                    font-size: 13px;
                }
                .cli-ac-item {
                    padding: 4px 8px; cursor: pointer; display: flex; justify-content: space-between;
                }
                .cli-ac-item:hover, .cli-ac-item.active { background: #1a2d42; }
                .cli-ac-cmd { font-weight: 600; color: #4da3ff; }
                .cli-ac-desc { opacity: 0.6; font-size: 12px; margin-left: 8px; }
            `;
            document.head.appendChild(style);
        }

        this._acDropdown = dropdown;
        this._acIndex = -1;

        input.addEventListener("input", () => this._updateAutocomplete(input.value));
    },

    _updateAutocomplete(value) {
        const dd = this._acDropdown;
        if (!dd) return;

        const raw = value.trim().toUpperCase();
        if (raw.length < 2) { dd.style.display = "none"; return; }

        // Get first token (the command part)
        const firstToken = raw.split(/[\s,]+/)[0];
        if (!firstToken) { dd.style.display = "none"; return; }

        // Find matching commands (prefix + fuzzy)
        const matches = [];
        const seen = new Set();
        for (const cmd of this.COMMANDS) {
            for (const alias of cmd.aliases) {
                const a = alias.toUpperCase();
                if (a.startsWith(firstToken) && !seen.has(cmd.key)) {
                    seen.add(cmd.key);
                    matches.push(cmd);
                    break;
                }
            }
        }

        if (matches.length === 0 || matches.length > 8) { dd.style.display = "none"; return; }
        // Don't show if exact match
        if (matches.length === 1 && matches[0].aliases.some(a => a.toUpperCase() === firstToken)) {
            dd.style.display = "none"; return;
        }

        dd.innerHTML = matches.slice(0, 6).map((cmd, i) =>
            `<div class="cli-ac-item${i === this._acIndex ? ' active' : ''}" data-key="${cmd.aliases[0]}">
                <span class="cli-ac-cmd">${cmd.aliases[0]}</span>
                <span class="cli-ac-desc">${cmd.desc}</span>
            </div>`
        ).join("");

        dd.style.display = "block";

        // Click handler
        dd.querySelectorAll(".cli-ac-item").forEach(item => {
            item.addEventListener("mousedown", (e) => {
                e.preventDefault();
                const inp = document.getElementById("cmd-input");
                const tokens = inp.value.split(/[\s,]+/);
                tokens[0] = item.dataset.key;
                inp.value = tokens.join(" ");
                dd.style.display = "none";
                inp.focus();
            });
        });
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
║  SHI [OPEN]  Show incidents                               ║
║  E1 SI       Self-initiate (creates incident)             ║
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
╠───────────────────────────────────────────────────────────╣
║  SWAP E1 E2  Swap incident assignments                    ║
║  MOVE E1 TO 5  Move unit to incident                      ║
║  NOTE 3 text Add note to incident                         ║
║  TC E1       Transfer command to unit                     ║
╠───────────────────────────────────────────────────────────╣
║  MSG E1      Message unit E1                              ║
║  CHAT        Toggle messaging drawer                      ║
║  BCAST       Open broadcast console                       ║
║  ↑/↓         Browse command history                       ║
║  HELP <cmd>  Help for specific command                    ║
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
  SHI                      Show incidents
  SHI OPEN|ACTIVE|HELD     Filter incidents
  E1 SI                    Self-initiate (clears current, creates new)
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
  SWAP E1 E2               Swap incident assignments
  MOVE E1 TO 5             Move unit to incident #5
  NOTE 3 text              Add note to incident #3
  TC E1                    Transfer command to E1
  E1 TC                    Transfer command to E1 (unit-first)

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

MESSAGING
  MSG <unit>               Open DM with unit
  MSG                      Open messaging drawer
  CHAT                     Toggle messaging drawer
  BCAST                    Open broadcast console

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

    _commandHelp(target) {
        const USAGE = {
            "SWAP": "SWAP <unit1> <unit2>\n  Swap incident assignments between two units.\n  Example: SWAP E1 E2",
            "SW": "SWAP <unit1> <unit2>\n  Swap incident assignments between two units.",
            "MOVE": "MOVE <unit> TO <#>\n  Move a unit to a different incident.\n  Example: MOVE E1 TO 5",
            "MV": "MOVE <unit> TO <#>\n  Move a unit to a different incident.",
            "NOTE": "NOTE <#> <text>\n  Add a remark/note to an incident.\n  Example: NOTE 3 Patient transported",
            "NT": "NOTE <#> <text>\n  Add a remark/note to an incident.",
            "TC": "TC <unit>\n  Transfer incident command to a unit.\n  The unit must be assigned to the active incident.\n  Example: TC E1",
            "TRANSFERCMD": "TC <unit>\n  Transfer incident command to a unit.",
            "D": "D <#> <unit> [unit...]\n  Dispatch units to incident.\n  Example: D 3 E1 M1",
            "DISPATCH": "D <#> <unit> [unit...]\n  Dispatch units to incident.\n  Or: <unit> D [#]  (unit-first mode)",
            "E": "<unit> E\n  Set unit status to ENROUTE.\n  Example: E1 E",
            "A": "<unit> A\n  Set unit status to ARRIVED.\n  Example: E1 A",
            "C": "<unit> C\n  Clear unit (prompts for disposition).\n  Example: E1 C",
            "R": "<unit> R: <text>\n  Add remark to unit's incident.\n  Example: E1 R: All clear",
            "NEW": "NEW [type]\n  Create a new incident.\n  Example: NEW EMS",
            "HOLD": "HOLD <#>: <reason>\n  Place incident on hold.\n  Example: HOLD 3: Awaiting callback",
            "SI": "<unit> SI [type]\n  Self-initiate an incident.\n  Example: E1 SI EMS",
            "ED": "ED <#> <code>\n  Set event disposition.\n  Codes: R, FA, NF, T, CT, PRTT, C, O",
            "CLOSE": "CLOSE <#>\n  Close an incident (requires event disposition).",
            "SCHED": "SCHED <#> <HH:MM>\n  Schedule incident for delayed activation.\n  Example: SCHED 5 14:30",
            "SCHEDULE": "SCHED <#> <HH:MM>\n  Schedule incident for delayed activation.",
            "DELAY": "SCHED <#> <HH:MM>\n  Schedule incident for delayed activation.",
        };
        const help = USAGE[target];
        if (help) {
            this._showHelp(help, `Help: ${target}`);
        } else {
            // Try finding in COMMANDS
            const cmd = this.COMMANDS.find(c => c.aliases.some(a => a.toUpperCase() === target));
            if (cmd) {
                this._showHelp(`${cmd.key}\n  ${cmd.desc}\n  Aliases: ${cmd.aliases.join(", ")}`, `Help: ${cmd.key}`);
            } else {
                this._toast(`Unknown command: ${target}. Type HELP for full reference.`, "error");
            }
        }
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

    // --- Append remark after status command ---
    // Posts remaining CLI text as a remark on each unit's active incident.
    async _appendRemarkAfterStatus(units, text) {
        if (!text) return;
        const list = this._asUnitList(units);
        for (const u of list) {
            try {
                await CAD_UTIL.postJSON("/remark", { unit_id: u, text });
            } catch (_) {
                // Best-effort; status already set
            }
        }
    },

    // --- Self-Initiate ---
    // Opens the UAW mini calltaker form so the user can fill in incident details,
    // instead of auto-creating a blank incident.
    async _selfInitiate(unitId, incidentType = null) {
        try {
            // If unit is currently on an incident, auto-clear first
            const ctx = await CAD_UTIL.getJSON(`/api/uaw/context/${encodeURIComponent(unitId)}`);
            const currentIncidentId = Number(ctx?.active_incident_id || 0);

            if (currentIncidentId) {
                this._toast(`${unitId} clearing from incident ${currentIncidentId}...`, "info");
                try {
                    await CAD_UTIL.postJSON(`/api/uaw/clear_unit`, {
                        unit_id: unitId,
                        incident_id: currentIncidentId,
                        disposition: "R"
                    });
                } catch (clearErr) {
                    console.warn(`[CLI] Auto-clear failed for ${unitId}:`, clearErr);
                }
            }

            // Open the UAW mini calltaker form instead of auto-creating
            if (window.UAW?.openForSelfInitiate) {
                await window.UAW.openForSelfInitiate(unitId);
            } else {
                // Fallback: auto-create if UAW mini calltaker not available
                const newRes = await fetch("/incident/new", { method: "POST" });
                if (!newRes.ok) {
                    this._toast("Failed to create incident", "error");
                    return;
                }
                const newInc = await newRes.json();
                const newIncidentId = newInc.incident_id;

                const saveData = {
                    type: incidentType || "SELF-INITIATED",
                    nature: "Self-initiated by " + unitId,
                    status: "OPEN"
                };
                await CAD_UTIL.postJSON(`/incident/save/${newIncidentId}`, saveData);
                await CAD_UTIL.postJSON("/api/cli/dispatch", {
                    incident_id: newIncidentId,
                    units: [unitId],
                    mode: "DE"
                });

                CAD_UTIL.refreshPanels();
                this._toast(`${unitId} self-initiated → Incident ${newIncidentId}`, "success");
                if (window.IAW?.open) window.IAW.open(newIncidentId);
            }
        } catch (err) {
            console.error("[CLI] Self-initiate failed:", err);
            this._toast(err?.message || "Self-initiate failed", "error");
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
    // NLP-LIKE PARSING
    // ========================================================================
    _tryNLP(raw) {
        const lower = raw.toLowerCase().trim();

        // Pattern: "send <unit(s)> to <incident>"
        let m = lower.match(/^send\s+(.+?)\s+to\s+(?:incident\s+)?(\d+)$/i);
        if (m) return { action: "DISPATCH", incident: m[2], units: m[1].split(/[\s,]+/) };

        // Pattern: "move <unit> to <incident>"
        m = lower.match(/^move\s+(.+?)\s+to\s+(?:incident\s+)?(\d+)$/i);
        if (m) return { action: "MOVE_UNIT", unit: m[1].trim(), incident: m[2] };

        // Pattern: "mark <unit> arrived" or "<unit> has arrived"
        m = lower.match(/^(?:mark\s+)?(.+?)\s+(?:has\s+)?arrived$/i);
        if (m) return { action: "ARRIVED", units: [m[1].trim()] };

        // Pattern: "clear <unit>"
        m = lower.match(/^clear\s+(.+)$/i);
        if (m) return { action: "CLEAR", units: m[1].split(/[\s,]+/) };

        // Pattern: "note <incident> <text>" or "add note to <incident>: <text>"
        m = lower.match(/^(?:add\s+)?note\s+(?:to\s+)?(\d+)[:\s]+(.+)$/i);
        if (m) return { action: "NOTE", incident: m[1], text: m[2] };

        // Pattern: "<unit> is enroute" or "<unit> responding to <incident>"
        m = lower.match(/^(.+?)\s+(?:is\s+)?(?:enroute|responding)(?:\s+to\s+(?:incident\s+)?(\d+))?$/i);
        if (m) {
            const units = m[1].split(/[\s,]+/);
            if (m[2]) return { action: "DISPATCH_ENROUTE", incident: m[2], units };
            return { action: "ENROUTE", units };
        }

        // Pattern: "<unit> is operating" or "<unit> working"
        m = lower.match(/^(.+?)\s+(?:is\s+)?(?:operating|working)$/i);
        if (m) return { action: "OPERATING", units: [m[1].trim()] };

        // Pattern: "<unit> transporting" or "<unit> in transit"
        m = lower.match(/^(.+?)\s+(?:is\s+)?(?:transporting|in\s+transit)$/i);
        if (m) return { action: "TRANSPORTING", units: [m[1].trim()] };

        // Pattern: "<unit> at hospital" or "<unit> at medical"
        m = lower.match(/^(.+?)\s+(?:is\s+)?(?:at\s+(?:hospital|medical|hosp|med))$/i);
        if (m) return { action: "AT_MEDICAL", units: [m[1].trim()] };

        // Pattern: "<unit> at station" or "<unit> in quarters"
        m = lower.match(/^(.+?)\s+(?:is\s+)?(?:at\s+(?:station|quarters|apparatus)|in\s+quarters)$/i);
        if (m) return { action: "AT_APPARATUS", units: [m[1].trim()] };

        // Pattern: "hold <incident> <reason>" or "hold incident <#> <reason>"
        m = lower.match(/^hold\s+(?:incident\s+)?(\d+)[:\s]+(.+)$/i);
        if (m) return { action: "HOLD", incident: m[1], text: m[2] };

        // Pattern: "<unit> 10-7" or "<unit> out of service"
        m = lower.match(/^(.+?)\s+(?:10-7|out\s+of\s+service|oos)$/i);
        if (m) return { action: "OOS", units: m[1].split(/[\s,]+/) };

        // Pattern: "<unit> 10-8" or "<unit> back in service"
        m = lower.match(/^(.+?)\s+(?:10-8|back\s+in\s+service|available)$/i);
        if (m) return { action: "AVAILABLE", units: m[1].split(/[\s,]+/) };

        // Pattern: "<unit> self initiate" or "<unit> self-initiate"
        m = lower.match(/^(.+?)\s+(?:self[\s-]?initiate[ds]?)$/i);
        if (m) return { action: "SELF_INITIATE", units: [m[1].trim()] };

        // Pattern: "dispatch <units> to <address>" (dispatch to location, not incident #)
        m = lower.match(/^dispatch\s+(.+?)\s+to\s+(.+)$/i);
        if (m && !/^\d+$/.test(m[2].trim())) return { action: "DISPATCH_LOCATION", units: m[1].split(/[\s,]+/), location: m[2].trim() };

        return null; // No NLP match
    },

    // ========================================================================
    // MAIN EXECUTE
    // ========================================================================
    async execute(command) {
        // Try NLP-like parsing first
        const nlp = this._tryNLP(command);
        if (nlp) {
            switch (nlp.action) {
                case "DISPATCH":
                    await this._dispatchToIncident(nlp.units, nlp.incident, "D");
                    return;
                case "MOVE_UNIT": {
                    const unitId = this.resolveAlias(nlp.unit);
                    const incId = nlp.incident;
                    try {
                        const res = await CAD_UTIL.postJSON("/api/cli/move", {
                            unit_id: unitId,
                            to_incident: Number(incId)
                        });
                        if (res?.ok) {
                            CAD_UTIL.refreshPanels();
                            this._toast(`${unitId} moved to incident ${incId}`, "success");
                        } else {
                            this._toast(res?.error || "Move failed", "error");
                        }
                    } catch (err) {
                        this._toast(err?.message || "Move failed", "error");
                    }
                    return;
                }
                case "ARRIVED":
                    await this._setStatusForUnits(this.resolveAliases(nlp.units), "ARRIVED");
                    return;
                case "ENROUTE":
                    await this._setStatusForUnits(this.resolveAliases(nlp.units), "ENROUTE");
                    return;
                case "DISPATCH_ENROUTE":
                    await this._dispatchToIncident(this.resolveAliases(nlp.units), nlp.incident, "DE");
                    return;
                case "OPERATING":
                    await this._setStatusForUnits(this.resolveAliases(nlp.units), "OPERATING");
                    return;
                case "TRANSPORTING":
                    await this._setStatusForUnits(this.resolveAliases(nlp.units), "TRANSPORTING");
                    return;
                case "AT_MEDICAL":
                    await this._setStatusForUnits(this.resolveAliases(nlp.units), "AT_MEDICAL");
                    return;
                case "AT_APPARATUS":
                    await this._setStatusForUnits(this.resolveAliases(nlp.units), "AT_APPARATUS");
                    return;
                case "OOS":
                    await this._setUnitOOS(this.resolveAliases(nlp.units));
                    return;
                case "AVAILABLE":
                    await this._setUnitAvailable(this.resolveAliases(nlp.units));
                    return;
                case "SELF_INITIATE":
                    for (const u of this.resolveAliases(nlp.units)) {
                        await this._selfInitiate(u);
                    }
                    return;
                case "CLEAR":
                    await this._clearUnit(this.resolveAliases(nlp.units));
                    return;
                case "HOLD": {
                    const hIncId = this._normalizeIncidentRef(nlp.incident);
                    try {
                        await CAD_UTIL.postJSON(`/incident/${encodeURIComponent(hIncId)}/hold`, {
                            reason: nlp.text
                        });
                        CAD_UTIL.refreshPanels();
                        this._toast(`Incident ${hIncId} placed on HOLD`, "success");
                    } catch (err) {
                        this._toast(err?.message || "Hold failed", "error");
                    }
                    return;
                }
                case "NOTE": {
                    const incId = nlp.incident;
                    try {
                        await CAD_UTIL.postJSON("/remark", {
                            incident_id: Number(incId),
                            text: nlp.text
                        });
                        this._toast(`Note added to incident ${incId}`, "success");
                    } catch (err) {
                        this._toast(err?.message || "Failed to add note", "error");
                    }
                    return;
                }
            }
        }

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
            const helpTarget = (tokens[1] || "").toUpperCase();
            if (helpTarget) {
                this._commandHelp(helpTarget);
            } else {
                this._fullHelp();
            }
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

        // ────────────────────────────────────────────────────────────────────
        // MESSAGING COMMANDS
        // ────────────────────────────────────────────────────────────────────
        if (firstCmd === "MESSAGE") {
            const target = tokens[1];
            if (target) {
                const unitId = this.resolveAlias(target);
                if (window.MessagingUI?.openDM) {
                    window.MessagingUI.openDM(unitId);
                } else {
                    this._toast("Messaging module not loaded", "error");
                }
            } else {
                // No target — just open the drawer
                if (window.MessagingUI?.toggleDrawer) {
                    window.MessagingUI.toggleDrawer();
                }
            }
            return;
        }

        if (firstCmd === "CHAT") {
            if (window.MessagingUI?.toggleDrawer) {
                window.MessagingUI.toggleDrawer();
            } else {
                this._toast("Messaging module not loaded", "error");
            }
            return;
        }

        if (firstCmd === "BROADCAST_MSG") {
            if (window.MessagingUI?.openBroadcast) {
                window.MessagingUI.openBroadcast();
            } else {
                this._toast("Messaging module not loaded", "error");
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
        // SWAP UNITS: SWAP <unit1> <unit2>
        // ────────────────────────────────────────────────────────────────────
        if (firstCmd === "SWAP_UNITS") {
            const u1 = this.resolveAlias(tokens[1]);
            const u2 = this.resolveAlias(tokens[2]);
            if (!u1 || !u2) {
                this._toast("Usage: SWAP <unit1> <unit2>", "error");
                return;
            }
            try {
                const res = await CAD_UTIL.postJSON("/api/cli/swap", { unit1: u1, unit2: u2 });
                if (res?.ok) {
                    CAD_UTIL.refreshPanels();
                    this._toast(`Swapped ${u1} ↔ ${u2}`, "success");
                } else {
                    this._toast(res?.error || "Swap failed", "error");
                }
            } catch (err) {
                this._toast(err?.message || "Swap failed", "error");
            }
            return;
        }

        // ────────────────────────────────────────────────────────────────────
        // NOTE: NOTE <#> <text>
        // ────────────────────────────────────────────────────────────────────
        if (firstCmd === "NOTE") {
            const incRef = tokens[1];
            const text = tokens.slice(2).join(" ").trim();
            if (!incRef || !text) {
                this._toast("Usage: NOTE <incident#> <text>", "error");
                return;
            }
            const incId = this._normalizeIncidentRef(incRef);
            try {
                await CAD_UTIL.postJSON("/remark", {
                    incident_id: Number(incId),
                    text: text
                });
                this._toast(`Note added to incident ${incId}`, "success");
            } catch (err) {
                this._toast(err?.message || "Failed to add note", "error");
            }
            return;
        }

        // ────────────────────────────────────────────────────────────────────
        // TRANSFER COMMAND: TC <unit>
        // ────────────────────────────────────────────────────────────────────
        if (firstCmd === "TRANSFER_CMD") {
            const targetUnit = this.resolveAlias(tokens[1]);
            if (!targetUnit) {
                this._toast("Usage: TC <unit>", "error");
                return;
            }
            // Find the unit's active incident
            try {
                const ctx = await CAD_UTIL.getJSON(`/api/uaw/context/${encodeURIComponent(targetUnit)}`);
                const incId = Number(ctx?.active_incident_id || 0);
                if (!incId) {
                    this._toast(`${targetUnit} is not assigned to an active incident`, "error");
                    return;
                }
                const res = await CAD_UTIL.postJSON("/api/uaw/transfer_command", {
                    incident_id: incId,
                    unit_id: targetUnit
                });
                if (res?.ok) {
                    CAD_UTIL.refreshPanels();
                    this._toast(`Command transferred to ${targetUnit}`, "success");
                } else {
                    this._toast(res?.error || "Transfer failed", "error");
                }
            } catch (err) {
                this._toast(err?.message || "Transfer command failed", "error");
            }
            return;
        }

        // ────────────────────────────────────────────────────────────────────
        // SCHEDULE INCIDENT: SCHED <#> <HH:MM or YYYY-MM-DD HH:MM>
        // ────────────────────────────────────────────────────────────────────
        if (firstCmd === "SCHEDULE") {
            const incRef = tokens[1];
            const timeStr = tokens.slice(2).join(" ").trim();
            if (!incRef || !timeStr) {
                this._toast("Usage: SCHED <incident#> <HH:MM>", "error");
                return;
            }
            const incId = this._normalizeIncidentRef(incRef);
            // If only HH:MM given, prepend today's date
            let scheduledFor = timeStr;
            if (/^\d{1,2}:\d{2}$/.test(timeStr)) {
                const today = new Date().toISOString().slice(0, 10);
                scheduledFor = `${today} ${timeStr}`;
            }
            try {
                const res = await CAD_UTIL.postJSON(`/api/incident/${incId}/schedule`, {
                    scheduled_for: scheduledFor
                });
                if (res?.ok) {
                    CAD_UTIL.refreshPanels();
                    this._toast(`Incident ${incId} scheduled for ${scheduledFor}`, "success");
                } else {
                    this._toast(res?.error || "Schedule failed", "error");
                }
            } catch (err) {
                this._toast(err?.message || "Schedule failed", "error");
            }
            return;
        }

        // ────────────────────────────────────────────────────────────────────
        // MOVE UNIT: MOVE <unit> TO <#>
        // ────────────────────────────────────────────────────────────────────
        if (firstCmd === "MOVE_UNIT") {
            const unitId = this.resolveAlias(tokens[1]);
            const toIdx = tokens.findIndex(t => t.toUpperCase() === "TO");
            const incRef = toIdx > 0 ? tokens[toIdx + 1] : tokens[2];
            if (!unitId || !incRef) {
                this._toast("Usage: MOVE <unit> TO <incident#>", "error");
                return;
            }
            const incId = this._normalizeIncidentRef(incRef);
            try {
                const res = await CAD_UTIL.postJSON("/api/cli/move", {
                    unit_id: unitId,
                    to_incident: Number(incId)
                });
                if (res?.ok) {
                    CAD_UTIL.refreshPanels();
                    this._toast(`${unitId} moved to incident ${incId}`, "success");
                } else {
                    this._toast(res?.error || "Move failed", "error");
                }
            } catch (err) {
                this._toast(err?.message || "Move failed", "error");
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
        // Any text after the status command is appended as a remark on the unit's active incident.
        // Example: "14 A HEAVY SMOKE SHOWING" → set ARRIVED + remark "HEAVY SMOKE SHOWING"
        if (action === "ENROUTE") {
            await this._setStatusForUnits(units, "ENROUTE");
            if (rest.length) await this._appendRemarkAfterStatus(units, rest.join(" "));
            return;
        }

        if (action === "ARRIVED") {
            await this._setStatusForUnits(units, "ARRIVED");
            if (rest.length) await this._appendRemarkAfterStatus(units, rest.join(" "));
            return;
        }

        if (action === "AT_APPARATUS") {
            await this._setStatusForUnits(units, "AT_APPARATUS");
            if (rest.length) await this._appendRemarkAfterStatus(units, rest.join(" "));
            return;
        }

        if (action === "OPERATING") {
            await this._setStatusForUnits(units, "OPERATING");
            if (rest.length) await this._appendRemarkAfterStatus(units, rest.join(" "));
            return;
        }

        if (action === "TRANSPORTING") {
            await this._setStatusForUnits(units, "TRANSPORTING");
            if (rest.length) await this._appendRemarkAfterStatus(units, rest.join(" "));
            return;
        }

        if (action === "AT_MEDICAL") {
            await this._setStatusForUnits(units, "AT_MEDICAL");
            if (rest.length) await this._appendRemarkAfterStatus(units, rest.join(" "));
            return;
        }

        if (action === "AVAILABLE") {
            await this._setUnitAvailable(units);
            if (rest.length) await this._appendRemarkAfterStatus(units, rest.join(" "));
            return;
        }

        if (action === "BUSY") {
            await this._setStatusForUnits(units, "BUSY");
            if (rest.length) await this._appendRemarkAfterStatus(units, rest.join(" "));
            return;
        }

        if (action === "OOS") {
            await this._setUnitOOS(units);
            if (rest.length) await this._appendRemarkAfterStatus(units, rest.join(" "));
            return;
        }

        // --- Clear Unit ---
        if (action === "CLEAR") {
            await this._clearUnit(units);
            return;
        }

        // --- Self-Initiate ---
        if (action === "SELF_INITIATE") {
            const incidentType = rest[0] || null; // Optional type like EMS, FIRE
            for (const u of units) {
                await this._selfInitiate(u, incidentType);
            }
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

        // --- Transfer Command ---
        if (action === "TRANSFER_CMD") {
            const u = units[0];
            try {
                const ctx = await CAD_UTIL.getJSON(`/api/uaw/context/${encodeURIComponent(u)}`);
                const incId = Number(ctx?.active_incident_id || 0);
                if (!incId) {
                    this._toast(`${u} is not assigned to an active incident`, "error");
                    return;
                }
                const res = await CAD_UTIL.postJSON("/api/uaw/transfer_command", {
                    incident_id: incId,
                    unit_id: u
                });
                if (res?.ok) {
                    CAD_UTIL.refreshPanels();
                    this._toast(`Command transferred to ${u}`, "success");
                } else {
                    this._toast(res?.error || "Transfer failed", "error");
                }
            } catch (err) {
                this._toast(err?.message || "Transfer command failed", "error");
            }
            return;
        }

        // --- Messaging ---
        if (action === "MESSAGE") {
            if (window.MessagingUI?.openDM) {
                window.MessagingUI.openDM(units[0]);
            } else {
                this._toast("Messaging module not loaded", "error");
            }
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
