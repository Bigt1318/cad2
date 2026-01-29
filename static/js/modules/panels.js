// ============================================================================
// FORD-CAD — PANELS CONTROLLER (CANON)
// Canon: ACTIVE + OPEN only • Held is modal-only
// ============================================================================
// Responsibilities:
//   • Single delegated click binding for incident + unit rows
//   • Panel refresh engine (Units + Open + Active)
//   • Event-driven refresh: listens for CAD_UTIL.REFRESH_EVENT
// ============================================================================

import IAW from "./iaw.js";
import UAW from "./uaw2.js";
import { CAD_UTIL } from "./utils.js";

const GLOBAL_GUARD_KEY = "__FORDCAD_PANELS_BOUND__";

let _initialized = false;
let _lastOpenId = null;
let _lastOpenTs = 0;

function nowMs() {
  return Date.now();
}

const PANELS = {
  init() {
    // Hard global guard (survives module re-import / HTMX script evaluation)
    if (window[GLOBAL_GUARD_KEY]) return;
    window[GLOBAL_GUARD_KEY] = true;

    if (_initialized) return;
    _initialized = true;

    // Expose canonical handle
    window.CAD = window.CAD || {};
    window.CAD.panels = PANELS;

    console.log("[PANELS] init() — delegated click binding + refresh event listener");

    // -------------------------------------------------------------
    // Event-driven refresh (push model)
    // -------------------------------------------------------------
    document.addEventListener(CAD_UTIL.REFRESH_EVENT, function () {
      PANELS.refreshAll();
    });

    // -------------------------------------------------------------
    // Delegated clicks (single-bind)
    // -------------------------------------------------------------
    document.addEventListener("click", function (e) {
      // Ignore clicks that happen inside any modal
      if (e.target && e.target.closest && e.target.closest(".cad-modal")) return;

      // INCIDENT ROW CLICK → IAW
      var incidentRow = e.target && e.target.closest ? e.target.closest(".incident-row") : null;
      if (incidentRow) {
        var incidentId = incidentRow.dataset ? incidentRow.dataset.incidentId : null;
        if (!incidentId) return;

        var t = nowMs();
        if (_lastOpenId === incidentId && (t - _lastOpenTs) < 250) return;
        _lastOpenId = incidentId;
        _lastOpenTs = t;

        try {
          IAW.open(incidentId);
        } catch (err) {
          console.warn("[PANELS] IAW.open failed:", err);
        }
        return;
      }

      // UNIT ROW CLICK → UAW
      var unitRow = e.target && e.target.closest ? e.target.closest(".unit-row") : null;
      if (!unitRow) return;

      var unitId = unitRow.dataset ? unitRow.dataset.unitId : null;
      if (!unitId) return;

      try {
        UAW.open(unitId);
      } catch (err2) {
        console.warn("[PANELS] UAW.open failed:", err2);
      }
    });
  },

  refreshAll() {
    var activeEl = document.querySelector("#panel-active");
    var openEl = document.querySelector("#panel-open");
    var unitsEl = document.querySelector("#panel-units");

    // IMPORTANT:
    // In ES modules, referencing bare `htmx` is NOT reliable.
    // Use window.htmx explicitly.
    var hx = window.htmx;
    if (!hx || typeof hx.ajax !== "function") {
      console.warn("[PANELS] refreshAll() skipped — window.htmx not available");
      return;
    }

    try {
      if (activeEl) {
        hx.ajax("GET", "/panel/active", { target: activeEl, swap: "outerHTML" });
      }
      if (openEl) {
        hx.ajax("GET", "/panel/open", { target: openEl, swap: "outerHTML" });
      }
      if (unitsEl) {
        hx.ajax("GET", "/panel/units", { target: unitsEl, swap: "outerHTML" });
      }
    } catch (err3) {
      console.warn("[PANELS] refreshAll() failed:", err3);
    }
  },

  // -------------------------------------------------------------------------
  // AUTO-REFRESH POLLING
  // Integrates with SETTINGS module for user preferences
  // -------------------------------------------------------------------------
  _autoRefreshTimer: null,

  startAutoRefresh() {
    // Stop any existing timer
    this.stopAutoRefresh();

    // Check if auto-refresh is enabled in settings
    const settings = window.SETTINGS?.getAll?.() || {};
    if (!settings.autoRefresh) {
      console.log("[PANELS] Auto-refresh disabled in settings");
      return;
    }

    const intervalSec = settings.autoRefreshInterval || 30;
    const intervalMs = intervalSec * 1000;

    console.log(`[PANELS] Starting auto-refresh every ${intervalSec}s`);

    this._autoRefreshTimer = setInterval(() => {
      // Re-check settings in case user changed them
      const currentSettings = window.SETTINGS?.getAll?.() || {};
      if (!currentSettings.autoRefresh) {
        this.stopAutoRefresh();
        return;
      }

      // Only refresh if page is visible (save resources)
      if (document.visibilityState === "visible") {
        console.log("[PANELS] Auto-refresh tick");
        this.refreshAll();
      }
    }, intervalMs);
  },

  stopAutoRefresh() {
    if (this._autoRefreshTimer) {
      clearInterval(this._autoRefreshTimer);
      this._autoRefreshTimer = null;
      console.log("[PANELS] Auto-refresh stopped");
    }
  },

  // Called when settings change
  onSettingsChange() {
    const settings = window.SETTINGS?.getAll?.() || {};
    if (settings.autoRefresh) {
      this.startAutoRefresh();
    } else {
      this.stopAutoRefresh();
    }
  }
};

// Start auto-refresh after a short delay (let page load)
setTimeout(() => {
  PANELS.startAutoRefresh();
}, 3000);

// Listen for visibility changes to pause/resume
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && PANELS._autoRefreshTimer) {
    // Page became visible, do an immediate refresh
    PANELS.refreshAll();
  }
});

// Global exposure for templates
window.PANELS = PANELS;

console.log("[PANELS] Loaded (ACTIVE + OPEN only, held modal-only, auto-refresh enabled).");

export default PANELS;
