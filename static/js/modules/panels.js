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


    // -------------------------------------------------------------
    // Event-driven refresh (push model)
    // -------------------------------------------------------------
    document.addEventListener(CAD_UTIL.REFRESH_EVENT, function () {
      PANELS.refreshAll();
    });

    // Semantic events — targeted panel refresh
    var EVT = CAD_UTIL.EVENTS || {};
    if (EVT.UNITS_CHANGED) {
      document.addEventListener(EVT.UNITS_CHANGED, function () {
        PANELS.refreshTargeted(["units", "active"]);
      });
    }
    if (EVT.INCIDENTS_CHANGED) {
      document.addEventListener(EVT.INCIDENTS_CHANGED, function () {
        PANELS.refreshTargeted(["active", "open"]);
      });
    }
    if (EVT.HELD_CHANGED) {
      document.addEventListener(EVT.HELD_CHANGED, function () {
        PANELS.refreshTargeted(["active"]);
      });
    }

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

  _refreshing: false,
  _refreshQueued: false,

  refreshAll() {
    // Prevent overlapping refresh calls (htmx outerHTML swaps are async)
    if (this._refreshing) {
      this._refreshQueued = true;
      return;
    }
    this._refreshing = true;

    this._doSwap(["active", "open", "units"]);

    // Release lock after htmx has time to swap DOM, then run queued refresh
    setTimeout(() => {
      this._refreshing = false;
      if (this._refreshQueued) {
        this._refreshQueued = false;
        this.refreshAll();
      }
    }, 500);
  },

  // Targeted refresh — only update specific panels
  refreshTargeted(panelNames) {
    if (!panelNames || !panelNames.length) {
      this.refreshAll();
      return;
    }
    this._doSwap(panelNames);
  },

  _doSwap(panelNames) {
    var hx = window.htmx;
    if (!hx || typeof hx.ajax !== "function") {
      console.warn("[PANELS] refresh skipped — window.htmx not available");
      this._refreshing = false;
      return;
    }

    var map = {
      active: { sel: "#panel-active", url: "/panel/active" },
      open:   { sel: "#panel-open",   url: "/panel/open" },
      units:  { sel: "#panel-units",  url: "/panel/units" },
    };

    try {
      for (var name of panelNames) {
        var cfg = map[name];
        if (!cfg) continue;
        var el = document.querySelector(cfg.sel);
        if (el) hx.ajax("GET", cfg.url, { target: el, swap: "outerHTML" });
      }
    } catch (err3) {
      console.warn("[PANELS] refresh failed:", err3);
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
      return;
    }

    const intervalSec = settings.autoRefreshInterval || 30;
    const intervalMs = intervalSec * 1000;


    this._autoRefreshTimer = setInterval(() => {
      // Re-check settings in case user changed them
      const currentSettings = window.SETTINGS?.getAll?.() || {};
      if (!currentSettings.autoRefresh) {
        this.stopAutoRefresh();
        return;
      }

      // Only refresh if page is visible (save resources)
      if (document.visibilityState === "visible") {
        this.refreshAll();
      }
    }, intervalMs);
  },

  stopAutoRefresh() {
    if (this._autoRefreshTimer) {
      clearInterval(this._autoRefreshTimer);
      this._autoRefreshTimer = null;
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


export default PANELS;
