// ============================================================================
// FORD-CAD — TIMERS MODULE
// Real-time age displays for incidents and response benchmarks
// ============================================================================

const TIMERS = {
    _interval: null,
    _updateFrequency: 10000, // 10 seconds

    init() {
        this.startUpdates();
        console.log("[TIMERS] Initialized - updating age displays every 10s");
    },

    startUpdates() {
        if (this._interval) return;
        
        // Initial update
        this.updateAllAges();
        
        // Periodic updates
        this._interval = setInterval(() => {
            this.updateAllAges();
        }, this._updateFrequency);
    },

    stopUpdates() {
        if (this._interval) {
            clearInterval(this._interval);
            this._interval = null;
        }
    },

    /**
     * Update all age displays in the DOM
     */
    updateAllAges() {
        // Update incident ages in panels
        document.querySelectorAll("[data-created]").forEach(el => {
            const created = el.dataset.created;
            if (!created) return;
            
            const age = this.formatAge(created);
            if (age && el.textContent !== age) {
                el.textContent = age;
            }
        });

        // Update incident row ages
        document.querySelectorAll(".incident-age[data-timestamp]").forEach(el => {
            const ts = el.dataset.timestamp;
            if (!ts) return;
            
            const age = this.formatAge(ts);
            if (age && el.textContent !== age) {
                el.textContent = age;
                
                // Add urgency class based on age
                this.applyUrgencyClass(el, ts);
            }
        });
    },

    /**
     * Format a timestamp into a human-readable age
     */
    formatAge(timestamp) {
        if (!timestamp) return "";
        
        try {
            // Parse timestamp (handle ISO format and "YYYY-MM-DD HH:MM:SS")
            let date;
            if (timestamp.includes("T")) {
                date = new Date(timestamp);
            } else {
                // "2024-01-29 12:34:56" format
                date = new Date(timestamp.replace(" ", "T"));
            }
            
            if (isNaN(date.getTime())) return "";
            
            const now = new Date();
            const diffMs = now - date;
            const diffSec = Math.floor(diffMs / 1000);
            const diffMin = Math.floor(diffSec / 60);
            const diffHr = Math.floor(diffMin / 60);
            const diffDay = Math.floor(diffHr / 24);
            
            if (diffSec < 0) return "0s";
            if (diffSec < 60) return `${diffSec}s`;
            if (diffMin < 60) return `${diffMin}m`;
            if (diffHr < 24) return `${diffHr}h ${diffMin % 60}m`;
            return `${diffDay}d ${diffHr % 24}h`;
        } catch (e) {
            return "";
        }
    },

    /**
     * Apply urgency styling based on age
     */
    applyUrgencyClass(el, timestamp) {
        try {
            const date = new Date(timestamp.replace(" ", "T"));
            const diffMin = Math.floor((Date.now() - date.getTime()) / 60000);
            
            el.classList.remove("age-normal", "age-warning", "age-critical");
            
            if (diffMin >= 30) {
                el.classList.add("age-critical");
            } else if (diffMin >= 15) {
                el.classList.add("age-warning");
            } else {
                el.classList.add("age-normal");
            }
        } catch (e) {
            // Ignore
        }
    },

    /**
     * Calculate response time (dispatch to arrival)
     */
    calculateResponseTime(dispatchedAt, arrivedAt) {
        if (!dispatchedAt || !arrivedAt) return null;
        
        try {
            const dispatched = new Date(dispatchedAt.replace(" ", "T"));
            const arrived = new Date(arrivedAt.replace(" ", "T"));
            
            const diffMs = arrived - dispatched;
            if (diffMs < 0) return null;
            
            const diffSec = Math.floor(diffMs / 1000);
            const min = Math.floor(diffSec / 60);
            const sec = diffSec % 60;
            
            return `${min}:${sec.toString().padStart(2, "0")}`;
        } catch (e) {
            return null;
        }
    }
};

// Auto-initialize
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => TIMERS.init());
} else {
    TIMERS.init();
}

// Pause when tab hidden, resume when visible
document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
        TIMERS.startUpdates();
    } else {
        TIMERS.stopUpdates();
    }
});

// Global exposure
window.TIMERS = TIMERS;
window.CAD = window.CAD || {};
window.CAD.timers = TIMERS;

export default TIMERS;
