// ============================================================================
// FORD CAD — CLOCK MODULE (CANONICAL)
// Phase-3 Enterprise Edition
// ============================================================================
// Responsibilities:
//   • Update header clock every second
//   • Zero external dependencies
//   • Safe to start multiple times (guarded)
// ============================================================================

let _interval = null;

export const CLOCK = {

    start() {
        if (_interval) return;

        const clockEl = document.getElementById("clock");
        if (!clockEl) {
            console.warn("[CLOCK] Clock element not found.");
            return;
        }

        const tick = () => {
            const now = new Date();
            clockEl.textContent = now.toLocaleTimeString("en-US", {
                hour12: false
            });
        };

        tick();
        _interval = setInterval(tick, 1000);

    },

    stop() {
        if (_interval) {
            clearInterval(_interval);
            _interval = null;
        }
    }
};

// Expose globally for bootloader
window.CLOCK = CLOCK;

Object.freeze(CLOCK);
export default CLOCK;

