// ============================================================================
// BOSK-CAD — COMMAND LINE ENGINE
// Phase-3 Enterprise Edition
// ============================================================================
// Controls:
//   - Dispatcher Command Line at the bottom of the UI
//   - Command parsing (unit actions, incident actions, shortcuts)
//   - History navigation (↑ / ↓)
//   - Integration with IAW, UAW, PANELS, and backend routes
//
// Examples Supported:
//   • E51 ENRT      -> Set unit E51 enroute
//   • E51 ARR       -> Set unit E51 arrived
//   • E51 CLR       -> Clear unit
//   • OPEN 1234     -> Open Incident 1234 in IAW
//   • I1234         -> Open incident 1234 (shortcut)
//   • U E51         -> Open Unit Window
//
// This is fully expandable for future commands.
// ============================================================================

import { BOSK_MODAL } from "./modal.js";
import { BOSK_UTIL } from "./utils.js";
import IAW from "./iaw.js";
import UAW from "./uaw.js";
import PANELS from "./panels.js";

export const CMD = {

    history: [],
    historyIndex: -1,

    // ---------------------------------------------------------------------
    // INITIALIZE COMMAND BAR
    // ---------------------------------------------------------------------
    init() {
        this.input = document.querySelector("#cmd-input");
        if (!this.input) {
            console.warn("[CMD] Command line input not found.");
            return;
        }

        this.input.addEventListener("keydown", (e) => this.handleKey(e));
        console.log("[CMD] Command Line Engine initialized.");
    },

    // ---------------------------------------------------------------------
    // KEY HANDLER (Enter, Up, Down)
    // ---------------------------------------------------------------------
    handleKey(e) {

        // ENTER -> execute command
        if (e.key === "Enter") {
            const text = this.input.value.trim();
            if (text.length > 0) {
                this.execute(text);
                this.history.push(text);
                this.historyIndex = this.history.length;
                this.input.value = "";
            }
        }

        // UP ARROW -> previous command
        if (e.key === "ArrowUp") {
            if (this.history.length === 0) return;
            this.historyIndex = Math.max(0, this.historyIndex - 1);
            this.input.value = this.history[this.historyIndex];
            e.preventDefault();
        }

        // DOWN ARROW -> next command
        if (e.key === "ArrowDown") {
            if (this.history.length === 0) return;
            this.historyIndex = Math.min(this.history.length, this.historyIndex + 1);
            this.input.value = this.history[this.historyIndex] || "";
            e.preventDefault();
        }
    },

    // ---------------------------------------------------------------------
    // EXECUTE COMMAND
    // ---------------------------------------------------------------------
    async execute(cmd) {

        console.log("[CMD] Executing:", cmd);

        const parts = cmd.toUpperCase().split(" ");
        if (parts.length === 0) return;

        // --------------------------------------------------------------
        // 1. UNIT STATUS SHORTCUTS
        //    Format:  E51 ENRT
        // --------------------------------------------------------------
        if (parts.length === 2 && this.isUnitID(parts[0])) {

            const unit = parts[0];
            const action = parts[1];

            if (["ENRT", "ENROUTE"].includes(action)) {
                return UAW.updateStatus(unit, "ENROUTE");
            }

            if (["ARR", "ARRIVED"].includes(action)) {
                return UAW.updateStatus(unit, "ARRIVED");
            }

            if (["CLR", "CLEAR"].includes(action)) {
                return UAW.updateStatus(unit, "CLEAR");
            }
        }

        // --------------------------------------------------------------
        // 2. OPEN INCIDENT
        //    Format: OPEN 1234
        // --------------------------------------------------------------
        if (parts[0] === "OPEN" && parts[1]) {
            const id = parseInt(parts[1]);
            if (!isNaN(id)) return BOSK_MODAL.open(`/incident/${id}/iaw`);
        }

        // --------------------------------------------------------------
        // 3. SHORTCUT: I1234 or INCIDENT 1234
        // --------------------------------------------------------------
        if (parts[0].startsWith("I") && !isNaN(parts[0].substring(1))) {
            const id = parseInt(parts[0].substring(1));
            return BOSK_MODAL.open(`/incident/${id}/iaw`);
        }

        if (parts[0] === "INCIDENT" && parts[1] && !isNaN(parts[1])) {
            return BOSK_MODAL.open(`/incident/${parts[1]}/iaw`);
        }

        // --------------------------------------------------------------
        // 4. OPEN UNIT WINDOW
        //    U E51
        // --------------------------------------------------------------
        if (parts[0] === "U" && parts[1] && this.isUnitID(parts[1])) {
            return UAW.open(parts[1]);
        }

        // --------------------------------------------------------------
        // 5. REFRESH COMMAND
        // --------------------------------------------------------------
        if (["R", "REFRESH"].includes(parts[0])) {
            PANELS.refreshAll();
            return;
        }

        // --------------------------------------------------------------
        // Unknown / invalid command
        // --------------------------------------------------------------
        alert(`Unknown command: ${cmd}`);
    },

    // ---------------------------------------------------------------------
    // CHECK IF STRING MATCHES UNIT FORMAT (ex: E51, MED1, TRK3)
    // ---------------------------------------------------------------------
    isUnitID(str) {
        return /^[A-Z]+\d+$/.test(str);
    }
};

// Enterprise freeze: no accidental mutations
Object.freeze(CMD);

console.log("[CMD] Module loaded (Phase-3 Enterprise Edition)");

export default CMD;
