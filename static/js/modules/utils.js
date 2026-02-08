// ============================================================================
// FORD-CAD — UTILITIES (CANONICAL)
// Phase-3 Core Utility Layer
// ============================================================================
// Purpose:
//   • Centralized fetch wrappers
//   • JSON helpers
//   • User confirmations
//   • SINGLE refresh orchestrator entry point (event-driven)
//
// Canon Contract:
//   • View endpoints return HTML only
//   • Command endpoints return JSON only
//   • After any successful command:
//        1) Refresh panels once (event-driven)
//        2) Reopen IAW once (if needed)
// ============================================================================

// ---------------------------------------------------------------------------
// SAFE FETCH (HTML)
// ---------------------------------------------------------------------------
async function safeFetch(url, options = {}) {
  const resp = await fetch(url, {
    credentials: "same-origin",
    ...options,
  });

  if (!resp.ok) {
    let body = "";
    try { body = await resp.text(); } catch (_) {}
    throw new Error(`Fetch failed (${resp.status})${body ? " - " + body : ""}`);
  }

  return await resp.text();
}

// ---------------------------------------------------------------------------
// GET JSON
// ---------------------------------------------------------------------------
async function getJSON(url) {
  const resp = await fetch(url, { credentials: "same-origin" });

  if (!resp.ok) {
    let body = "";
    try { body = await resp.text(); } catch (_) {}
    throw new Error(`GET ${url} failed (${resp.status})${body ? " - " + body : ""}`);
  }

  return await resp.json();
}

// ---------------------------------------------------------------------------
// POST JSON
// ---------------------------------------------------------------------------
async function postJSON(url, data = {}) {
  const resp = await fetch(url, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });

  if (!resp.ok) {
    let body = "";
    try { body = await resp.text(); } catch (_) {}
    throw new Error(`POST ${url} failed (${resp.status})${body ? " - " + body : ""}`);
  }

  const text = await resp.text();
  if (!text) return {};

  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new Error(`POST ${url} returned non-JSON response`);
  }

  if (parsed && typeof parsed === "object" && ("ok" in parsed) && parsed.ok === false) {
    throw new Error(parsed.error || parsed.message || "Command rejected by backend.");
  }

  return parsed;
}

// ---------------------------------------------------------------------------
// NOTIFY / CONFIRM
// ---------------------------------------------------------------------------
function notify(msg) {
  alert(msg);
}

function confirmAction(msg) {
  return confirm(msg);
}

// ---------------------------------------------------------------------------
// PANEL REFRESH (EVENT-DRIVEN, SINGLE PATH)
// ---------------------------------------------------------------------------
const REFRESH_EVENT = "cad:refresh-panels";

// Prevent overlapping refresh calls
let _refreshInProgress = false;

// Drag guard (prevents HTMX swap errors mid-drag)
if (typeof window !== "undefined" && !window.__CAD_DRAG_GUARD_INSTALLED) {
  window.__CAD_DRAG_GUARD_INSTALLED = true;
  window.__CAD_DRAG_ACTIVE = false;

  document.addEventListener("dragstart", () => { window.__CAD_DRAG_ACTIVE = true; }, true);
  document.addEventListener("dragend",   () => { window.__CAD_DRAG_ACTIVE = false; }, true);
  document.addEventListener("drop",      () => { window.__CAD_DRAG_ACTIVE = false; }, true);
}

function refreshPanels(detail = null, opts = {}) {
  const force = !!opts.force;

  if (_refreshInProgress) return;

  // If a drag is in progress, defer refresh slightly unless forced
  if (!force && window.__CAD_DRAG_ACTIVE) {
    setTimeout(() => refreshPanels(detail, { force: true }), 200);
    return;
  }

  _refreshInProgress = true;

  // Small delay to ensure backend DB commit is fully flushed before we fetch
  setTimeout(() => {
    try {
      _doRefresh();
    } finally {
      // Release lock after htmx requests have been queued
      setTimeout(() => { _refreshInProgress = false; }, 300);
    }
  }, 50);
}

function _doRefresh() {
  // 1) If PANELS module is present, use it (single call — no double-firing)
  const panels = window.CAD?.panels || window.PANELS;
  if (panels && typeof panels.refreshAll === "function") {
    try { panels.refreshAll(); } catch (err) { console.warn("[UTIL] panels.refreshAll failed:", err); }
    return;
  }

  // 2) Direct htmx ajax fallback
  if (typeof window.htmx === "undefined") {
    console.warn("[UTIL] Panels engine not ready — refresh skipped (htmx missing)");
    return;
  }

  const first = (...sels) => {
    for (const s of sels) {
      const el = document.querySelector(s);
      if (el) return el;
    }
    return null;
  };

  const refresh = (el, url) => {
    if (!el) return;
    if (!el.isConnected) return;
    window.htmx.ajax("GET", url, { target: el, swap: "outerHTML" });
  };

  refresh(first("#panel-active"), "/panel/active");
  refresh(first("#panel-open"), "/panel/open");
  refresh(first("#panel-units"), "/panel/units");
}

// Legacy alias
function emitIncidentUpdated(detail = null) {
  refreshPanels(detail);
}

// ---------------------------------------------------------------------------
// REOPEN IAW HELPER
// ---------------------------------------------------------------------------
function reopenIAW(incident_id) {
  if (!incident_id) return;
  if (window.IAW && typeof window.IAW.open === "function") {
    window.IAW.open(incident_id);
  }
}

// ---------------------------------------------------------------------------
// PUBLIC EXPORT
// ---------------------------------------------------------------------------
export const CAD_UTIL = {
  safeFetch,
  getJSON,
  postJSON,
  notify,
  confirm: confirmAction,
  refreshPanels,
  emitIncidentUpdated,
  reopenIAW,
  REFRESH_EVENT,
};

export default CAD_UTIL;

// ---------------------------------------------------------------------------
// LEGACY GLOBAL WRAPPERS (Canon Backward Compatibility)
// ---------------------------------------------------------------------------
// These wrap the consolidated refreshPanels() for code expecting separate functions
window.refreshUnitsPanel = () => refreshPanels({ source: "legacy-units" });
window.refreshActivePanel = () => refreshPanels({ source: "legacy-active" });
window.refreshOpenPanel = () => refreshPanels({ source: "legacy-open" });
window.refreshHeldPanel = () => refreshPanels({ source: "legacy-held" });

