// FILE: static/js/modules/uaw.js

// ============================================================================
// FORD CAD — UNIT ACTION WINDOW (UAW)
// Phase-3 Canonical (INLINE POPUP — no modal, no blur)
// ============================================================================
//
// Backend routes (aligned to your current build):
//   • Dispatch:        POST /api/cli/dispatch                { units:[...], incident_id, mode:"D" }
//   • Unit status:     POST /api/unit_status/{unit_id}/{status}
//   • Misc status:     POST /api/uaw/misc/{unit_id}          { text: "..." }
//   • Clear unit:      POST /api/uaw/clear_unit              { incident_id, unit_id, disposition, comment }
//   • Transfer cmd:    POST /api/transfer_command/{unit_id}/{new_command_unit}
//   • Units on scene:  GET  /api/units_on_scene/{unit_id}
//   • Known unit IDs:  GET  /api/unit_ids                    -> ["1578","Car1",...]
//
// Apparatus crew assignment routes (Phase-3):
//   • Apparatus list:  GET  /api/apparatus/list              -> { ok, apparatus:[{unit_id,name}] }
//   • Crew for unit:   GET  /api/uaw/context/{unit_id}        -> { is_apparatus, parent_apparatus_id, crew:[] }
//   • Crew assign:     POST /api/crew/assign                  { apparatus_id, personnel_id, role?, shift? }
//   • Crew unassign:   POST /api/crew/unassign                { personnel_id, apparatus_id? }
//
// UX rules enforced here:
//   • Autofocus first input/select/button in each view
//   • Enter submits in input views (TEXTAREA excluded unless Ctrl+Enter)
//   • Escape cancels (back if available, else close)
//   • Popup always stays ON-SCREEN (clamped). Mini-Calltaker is CENTERED.
//   • Popup is draggable by its header
// ============================================================================

import { CAD_UTIL } from "./utils.js";
import DISP from "./disposition.js";

// ---------------------------------------------------------------------------
// Module-scoped state
// ---------------------------------------------------------------------------
let _popup = null;
let _unitId = null;
let _incidentId = null;

let _isApparatus = false;
let _parentApparatusId = null; // for personnel
let _crew = []; // for apparatus

let _outsideHandler = null;
let _keyHandler = null;

let _onEscape = null;
let _onEnter = null;

let _anchorRect = null;

// Drag state
let _dragMoveHandler = null;
let _dragUpHandler = null;
let _dragging = false;
let _dragStartX = 0;
let _dragStartY = 0;
let _dragStartLeft = 0;
let _dragStartTop = 0;

const STYLE_ID = "uaw-inline-style-v2";

// Known unit registry cache
let _knownUnits = null; // Set<string> | null

function _ensureStyles() {
  // Remove old style if exists
  const old = document.getElementById("uaw-inline-style");
  if (old) old.remove();

  // Check if current version exists
  if (document.getElementById(STYLE_ID)) return;

  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
    /* UAW Popup — Matches context menu dark glass style */
    .uaw-popup{
      position:fixed;
      min-width:200px;
      max-width:280px;
      z-index:9999;
      background:rgba(15, 23, 34, 0.98);
      border:1px solid rgba(255, 255, 255, 0.12);
      border-radius:8px;
      box-shadow:0 8px 32px rgba(0,0,0,.5), 0 0 1px rgba(255,255,255,0.1);
      overflow:hidden;
      color:#e8f0f8;
      font-family:"Segoe UI", system-ui, sans-serif;
      font-size:13px;
      backdrop-filter:blur(12px);
      -webkit-backdrop-filter:blur(12px);
    }
    .uaw-head{
      padding:10px 14px;
      border-bottom:1px solid rgba(255,255,255,0.1);
      cursor:move;
      user-select:none;
    }
    .uaw-title{ font-weight:700; font-size:14px; line-height:1.2; color:#fff; }
    .uaw-sub{ margin-top:2px; font-size:12px; opacity:.6; }

    /* Menu items (matching context menu) */
    .uaw-grid{
      display:flex;
      flex-direction:column;
      padding:6px 0;
    }
    .uaw-grid button{
      display:flex;
      align-items:center;
      gap:10px;
      padding:8px 14px;
      cursor:pointer;
      color:#e8f0f8;
      background:transparent;
      border:none;
      text-align:left;
      font-size:13px;
      font-weight:500;
      transition:background 0.1s ease;
      width:100%;
    }
    .uaw-grid button:disabled{
      opacity:.4;
      cursor:not-allowed;
    }
    .uaw-grid button:hover:not(:disabled){
      background:rgba(59, 130, 246, 0.2);
    }

    /* Separator */
    .uaw-separator{
      height:1px;
      background:rgba(255,255,255,0.1);
      margin:6px 10px;
    }

    /* List view */
    .uaw-list{
      max-height:250px;
      overflow:auto;
      padding:6px 0;
      display:flex;
      flex-direction:column;
    }
    .uaw-list-item{
      display:flex;
      align-items:center;
      padding:8px 14px;
      cursor:pointer;
      color:#e8f0f8;
      background:transparent;
      border:none;
      text-align:left;
      font-size:13px;
      transition:background 0.1s ease;
    }
    .uaw-list-item:hover:not(:disabled){
      background:rgba(59, 130, 246, 0.2);
    }
    .uaw-empty{
      padding:12px 14px;
      text-align:center;
      opacity:.5;
      font-size:12px;
    }

    /* Footer */
    .uaw-foot{
      display:flex;
      gap:6px;
      padding:8px 10px;
      border-top:1px solid rgba(255,255,255,0.1);
    }
    .uaw-foot button{
      flex:1;
      padding:8px 12px;
      border:1px solid rgba(255,255,255,0.2);
      border-radius:6px;
      background:transparent;
      color:#e8f0f8;
      font-size:12px;
      font-weight:600;
      cursor:pointer;
      transition:all 0.1s;
    }
    .uaw-foot button:hover{
      background:rgba(59, 130, 246, 0.2);
      border-color:rgba(59, 130, 246, 0.4);
    }
    .uaw-foot .uaw-primary{
      background:rgba(59, 130, 246, 0.3);
      border-color:rgba(59, 130, 246, 0.5);
    }
    .uaw-foot .uaw-primary:hover{
      background:rgba(59, 130, 246, 0.5);
    }

    /* Inline input row */
    .uaw-inline{
      padding:8px 10px;
      display:flex;
      gap:6px;
      align-items:center;
    }
    .uaw-inline input,
    .uaw-inline select{
      flex:1;
      border:1px solid rgba(255,255,255,0.2);
      border-radius:6px;
      padding:8px 10px;
      font-size:13px;
      outline:none;
      color:#e8f0f8;
      background:rgba(0,0,0,0.3);
    }
    .uaw-inline input::placeholder{ color:rgba(255,255,255,0.4); }
    .uaw-inline input:focus,
    .uaw-inline select:focus{
      border-color:rgba(59, 130, 246, 0.5);
      background:rgba(0,0,0,0.4);
    }
    .uaw-inline button{
      padding:8px 14px;
      border:1px solid rgba(59, 130, 246, 0.5);
      border-radius:6px;
      background:rgba(59, 130, 246, 0.3);
      color:#fff;
      font-size:12px;
      font-weight:600;
      cursor:pointer;
      transition:all 0.1s;
    }
    .uaw-inline button:hover{
      background:rgba(59, 130, 246, 0.5);
    }

    /* Wider popup mode (used by mini-calltaker) */
    .uaw-popup.uaw-wide{ min-width:420px; max-width:500px; }

    /* Mini Calltaker form */
    .uaw-scroll{ max-height:500px; overflow:auto; }
    .uaw-form{
      padding:12px;
      display:flex;
      flex-direction:column;
      gap:10px;
      user-select:text;
    }
    .uaw-form label{
      display:block;
      font-size:10px;
      font-weight:700;
      opacity:.6;
      margin:0 0 4px 0;
      text-transform:uppercase;
      letter-spacing:.5px;
    }
    .uaw-form input,
    .uaw-form textarea,
    .uaw-form select{
      width:100%;
      border:1px solid rgba(255,255,255,0.2);
      border-radius:6px;
      padding:8px 10px;
      font-size:13px;
      outline:none;
      color:#e8f0f8;
      background:rgba(0,0,0,0.3);
      box-sizing:border-box;
      user-select:text;
    }
    .uaw-form input::placeholder,
    .uaw-form textarea::placeholder{ color:rgba(255,255,255,0.4); }
    .uaw-form input:focus,
    .uaw-form textarea:focus,
    .uaw-form select:focus{
      border-color:rgba(59, 130, 246, 0.5);
      background:rgba(0,0,0,0.4);
    }
    .uaw-form input:disabled{
      opacity:.5;
      cursor:not-allowed;
    }
    .uaw-form textarea{ min-height:70px; resize:vertical; }
    .uaw-form select option{ background:#1a2535; color:#e8f0f8; }

    .uaw-form .uaw-row-3{
      display:grid;
      grid-template-columns:1fr 1fr 1fr;
      gap:8px;
    }
    .uaw-form .uaw-row-2{
      display:grid;
      grid-template-columns:1fr 1fr;
      gap:8px;
    }

    .uaw-form .uaw-actions{
      display:flex;
      gap:8px;
      margin-top:4px;
    }
    .uaw-form .uaw-actions button{
      flex:1;
      padding:10px 14px;
      border:1px solid rgba(255,255,255,0.2);
      border-radius:6px;
      background:transparent;
      color:#e8f0f8;
      font-size:13px;
      font-weight:600;
      cursor:pointer;
      transition:all 0.1s;
    }
    .uaw-form .uaw-actions button:hover{
      background:rgba(59, 130, 246, 0.2);
      border-color:rgba(59, 130, 246, 0.4);
    }
    .uaw-form .uaw-actions button:first-child{
      background:rgba(59, 130, 246, 0.3);
      border-color:rgba(59, 130, 246, 0.5);
    }
    .uaw-form .uaw-actions button:first-child:hover{
      background:rgba(59, 130, 246, 0.5);
    }

    /* Crew/Assign helper UI */
    .uaw-subtitle{
      padding:8px 14px 4px;
      font-weight:700;
      font-size:10px;
      opacity:.5;
      text-transform:uppercase;
      letter-spacing:.5px;
    }
    .uaw-field{
      padding:8px 14px;
    }
    .uaw-field label{
      display:block;
      font-size:10px;
      font-weight:700;
      opacity:.5;
      margin:0 0 4px 0;
      text-transform:uppercase;
    }
    .uaw-input{
      width:100%;
      border:1px solid rgba(255,255,255,0.2);
      border-radius:6px;
      padding:8px 10px;
      font-size:13px;
      outline:none;
      color:#e8f0f8;
      background:rgba(0,0,0,0.3);
      box-sizing:border-box;
    }
    .uaw-input:focus{
      border-color:rgba(59, 130, 246, 0.5);
      background:rgba(0,0,0,0.4);
    }
    .uaw-btn-small{
      padding:6px 10px;
      font-size:11px;
      border-radius:6px;
      border:1px solid rgba(255,255,255,0.2);
      background:transparent;
      color:#e8f0f8;
      cursor:pointer;
      transition:all 0.1s;
    }
    .uaw-btn-small:hover{
      background:rgba(59, 130, 246, 0.2);
      border-color:rgba(59, 130, 246, 0.4);
    }
    .uaw-pill{
      display:inline-block;
      padding:3px 8px;
      border-radius:999px;
      border:1px solid rgba(255,255,255,0.2);
      font-size:11px;
      opacity:.8;
      background:rgba(0,0,0,0.2);
    }
    .uaw-row{
      display:flex;
      align-items:center;
      justify-content:space-between;
      padding:8px 14px;
      border-bottom:1px solid rgba(255,255,255,0.05);
    }
    .uaw-row:last-child{ border-bottom:none; }
    .uaw-row-main{ display:flex; align-items:center; gap:8px; }
    .uaw-muted{ padding:12px 14px; opacity:.5; font-size:12px; text-align:center; }
  `;
  document.head.appendChild(style);
}

function _safeAlert(msg) {
  try { CAD_UTIL.notify?.(msg); } catch (_) {}
  try { alert(msg); } catch (_) {}
}

function _refreshPanels() {
  try { CAD_UTIL.refreshPanels?.(); } catch (_) {}
  try { window.CAD?.panels?.refreshAll?.(); } catch (_) {}
}

function _focusFirst(selector = null) {
  if (!_popup) return;

  const el =
    (selector ? _popup.querySelector(selector) : null) ||
    _popup.querySelector("[data-autofocus='1']") ||
    _popup.querySelector("input:not([type='hidden']):not([disabled])") ||
    _popup.querySelector("select:not([disabled])") ||
    _popup.querySelector("textarea:not([disabled])") ||
    _popup.querySelector("button:not([disabled])");

  if (!el) return;

  setTimeout(() => {
    try {
      el.focus?.();
      el.select?.();
    } catch (_) {}
  }, 0);
}

// ---------------------------------------------------------------------------
// Known unit registry
// ---------------------------------------------------------------------------
async function _loadKnownUnits() {
  if (_knownUnits instanceof Set) return _knownUnits;

  try {
    const rows = await CAD_UTIL.getJSON("/api/unit_ids");
    if (Array.isArray(rows) && rows.length) {
      _knownUnits = new Set(rows.map((x) => String(x).trim()).filter(Boolean));
      return _knownUnits;
    }
  } catch (_) {}

  // If endpoint is missing, do not hard-fail operations.
  _knownUnits = null;
  return null;
}

function _validateKnownUnitOrWarn(unitId) {
  if (!_knownUnits) return true;
  const ok = _knownUnits.has(String(unitId).trim());
  if (!ok) _safeAlert(`Unknown unit ID: ${unitId}`);
  return ok;
}

function _validateUnitListOrWarn(units) {
  if (!_knownUnits) return true;
  const invalid = (units || []).filter((u) => !_knownUnits.has(String(u).trim()));
  if (invalid.length) {
    _safeAlert(`Unknown unit(s): ${invalid.join(", ")}`);
    return false;
  }
  return true;
}

// ---------------------------------------------------------------------------
// Popup positioning (always on-screen)
// ---------------------------------------------------------------------------
function _clampPopup() {
  if (!_popup) return;

  const margin = 8;
  const w = _popup.offsetWidth || 280;
  const h = _popup.offsetHeight || 320;

  let left = parseInt(_popup.style.left || "0", 10);
  let top = parseInt(_popup.style.top || "0", 10);

  const maxLeft = Math.max(margin, window.innerWidth - w - margin);
  const maxTop = Math.max(margin, window.innerHeight - h - margin);

  if (Number.isNaN(left)) left = margin;
  if (Number.isNaN(top)) top = margin;

  left = Math.min(Math.max(margin, left), maxLeft);
  top = Math.min(Math.max(margin, top), maxTop);

  _popup.style.left = `${left}px`;
  _popup.style.top = `${top}px`;
}

function _positionNearAnchor() {
  if (!_popup) return;

  const margin = 8;
  const rect = _anchorRect;

  if (!rect) {
    _centerPopup();
    return;
  }

  const w = _popup.offsetWidth || 280;
  const h = _popup.offsetHeight || 320;

  const desiredLeft = rect.right + 8;
  const desiredTop = rect.top;

  const maxLeft = Math.max(margin, window.innerWidth - w - margin);
  const maxTop = Math.max(margin, window.innerHeight - h - margin);

  const left = Math.min(Math.max(margin, desiredLeft), maxLeft);
  const top = Math.min(Math.max(margin, desiredTop), maxTop);

  _popup.style.left = `${left}px`;
  _popup.style.top = `${top}px`;
}

function _centerPopup() {
  if (!_popup) return;

  const margin = 8;
  const w = _popup.offsetWidth || 280;
  const h = _popup.offsetHeight || 320;

  const left = Math.max(margin, Math.floor((window.innerWidth - w) / 2));
  const top = Math.max(margin, Math.floor((window.innerHeight - h) / 2));

  _popup.style.left = `${left}px`;
  _popup.style.top = `${top}px`;

  _clampPopup();
}

function _placePopup(mode = "anchor", showAfter = false) {
  setTimeout(() => {
    if (!_popup) return;

    if (mode === "center") _centerPopup();
    else _positionNearAnchor();

    _clampPopup();

    // Set visible AFTER positioning to prevent flash
    if (showAfter) {
      _popup.style.visibility = "visible";
    }
  }, 0);
}

// ---------------------------------------------------------------------------
// Drag support (header drag)
// ---------------------------------------------------------------------------
function _bindDragHandle() {
  if (!_popup) return;

  const head = _popup.querySelector(".uaw-head");
  if (!head) return;

  head.onmousedown = (e) => {
    if (e.button !== 0) return;

    const tag = (e.target?.tagName || "").toUpperCase();
    if (["INPUT", "TEXTAREA", "SELECT", "BUTTON"].includes(tag)) return;

    e.preventDefault();
    e.stopPropagation();

    _dragging = true;
    _dragStartX = e.clientX;
    _dragStartY = e.clientY;

    const left = parseInt(_popup.style.left || "0", 10);
    const top = parseInt(_popup.style.top || "0", 10);

    _dragStartLeft = Number.isNaN(left) ? 0 : left;
    _dragStartTop = Number.isNaN(top) ? 0 : top;

    _dragMoveHandler = (ev) => {
      if (!_dragging || !_popup) return;

      const dx = ev.clientX - _dragStartX;
      const dy = ev.clientY - _dragStartY;

      _popup.style.left = `${_dragStartLeft + dx}px`;
      _popup.style.top = `${_dragStartTop + dy}px`;

      _clampPopup();
    };

    _dragUpHandler = () => {
      _dragging = false;

      if (_dragMoveHandler) {
        document.removeEventListener("mousemove", _dragMoveHandler);
        _dragMoveHandler = null;
      }
      if (_dragUpHandler) {
        document.removeEventListener("mouseup", _dragUpHandler);
        _dragUpHandler = null;
      }
    };

    document.addEventListener("mousemove", _dragMoveHandler);
    document.addEventListener("mouseup", _dragUpHandler);
  };
}

function _unbindDrag() {
  _dragging = false;

  if (_dragMoveHandler) {
    document.removeEventListener("mousemove", _dragMoveHandler);
    _dragMoveHandler = null;
  }
  if (_dragUpHandler) {
    document.removeEventListener("mouseup", _dragUpHandler);
    _dragUpHandler = null;
  }
}

// ---------------------------------------------------------------------------
// Render + bind
// ---------------------------------------------------------------------------
function _render(html) {
  if (!_popup) return;
  _popup.innerHTML = html;
  _bindDragHandle();
  // Only clamp if popup is already visible (skip during initial setup to prevent flash)
  if (_popup.style.visibility !== "hidden") {
    _clampPopup();
  }
}

function _bindActions() {
  if (!_popup) return;

  _popup.querySelectorAll("[data-action]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      UAW._handle(btn.dataset.action);
    });
  });
}

function _setOutsideAndKeyHandlers() {
  if (!_popup) return;

  _outsideHandler = (ev) => {
    if (_popup && !_popup.contains(ev.target)) UAW.close();
  };
  document.addEventListener("mousedown", _outsideHandler);

  _keyHandler = (ev) => {
    if (!_popup) return;

    if (ev.key === "Escape") {
      ev.preventDefault();
      if (typeof _onEscape === "function") {
        _onEscape();
        return;
      }
      UAW.close();
      return;
    }

    if (ev.key === "Enter") {
      if (typeof _onEnter !== "function") return;

      const tag = (ev.target?.tagName || "").toUpperCase();
      if (tag === "TEXTAREA" && !ev.ctrlKey) return;

      ev.preventDefault();
      _onEnter();
    }
  };
  document.addEventListener("keydown", _keyHandler);

  window.addEventListener("resize", _clampPopup, { passive: true });
}

function _removeHandlers() {
  if (_outsideHandler) {
    document.removeEventListener("mousedown", _outsideHandler);
    _outsideHandler = null;
  }
  if (_keyHandler) {
    document.removeEventListener("keydown", _keyHandler);
    _keyHandler = null;
  }
  window.removeEventListener("resize", _clampPopup);

  _onEscape = null;
  _onEnter = null;
  _anchorRect = null;

  _unbindDrag();
}

// ---------------------------------------------------------------------------
// Backend calls
// ---------------------------------------------------------------------------
async function _postUnitStatus(unitId, status) {
  return CAD_UTIL.postJSON(
    `/api/unit_status/${encodeURIComponent(unitId)}/${encodeURIComponent(status)}`,
    {}
  );
}

async function _postUnitMisc(unitId, text) {
  return CAD_UTIL.postJSON(
    `/api/uaw/misc/${encodeURIComponent(unitId)}`,
    { text: text ?? "" }
  );
}

async function _postUnitDispatch(unitId, incidentId) {
  return CAD_UTIL.postJSON("/api/cli/dispatch", {
    units: [String(unitId)],
    incident_id: Number(incidentId),
    mode: "D"
  });
}

async function _postUnitClear(unitId, incidentId, disposition, comment) {
  const inc = Number(incidentId);
  const uid = String(unitId);
  const dispo = (disposition || "").trim().toUpperCase();
  const remark = (comment || "").trim();

  if (dispo) {
    await CAD_UTIL.postJSON(
      `/incident/${encodeURIComponent(inc)}/unit/${encodeURIComponent(uid)}/disposition`,
      { disposition: dispo, remark }
    );
  }

  return CAD_UTIL.postJSON(
    `/api/uaw/clear_unit`,
    { incident_id: inc, unit_id: uid, disposition: dispo, comment: remark }
  );
}

async function _postTransferCommand(fromUnitId, newCommandUnitId) {
  return CAD_UTIL.postJSON(
    `/api/transfer_command/${encodeURIComponent(fromUnitId)}/${encodeURIComponent(newCommandUnitId)}`,
    {}
  );
}

async function _getUnitsOnScene(unitId) {
  return CAD_UTIL.getJSON(`/api/units_on_scene/${encodeURIComponent(unitId)}`);
}

// Crew assignment APIs
async function _getApparatusList() {
  return CAD_UTIL.getJSON("/api/apparatus/list");
}

async function _postCrewAssign(apparatusId, personnelId, role = "", shift = "") {
  return CAD_UTIL.postJSON("/api/crew/assign", {
    apparatus_id: String(apparatusId),
    personnel_id: String(personnelId),
    role: String(role || ""),
    shift: String(shift || "")
  });
}

async function _postCrewUnassign(personnelId, apparatusId = null) {
  return CAD_UTIL.postJSON("/api/crew/unassign", {
    personnel_id: String(personnelId),
    apparatus_id: apparatusId ? String(apparatusId) : null
  });
}

// ---------------------------------------------------------------------------
// Optional endpoints (best-effort)
// ---------------------------------------------------------------------------
async function _tryGetDispatchTargets() {
  try {
    const rows = await CAD_UTIL.getJSON("/api/uaw/dispatch_targets");
    if (Array.isArray(rows)) return rows;
  } catch (_) {}
  return null;
}

async function _tryGetUnitContext(unitId) {
  try {
    const ctx = await CAD_UTIL.getJSON(`/api/uaw/context/${encodeURIComponent(unitId)}`);
    return ctx || null;
  } catch (_) {}
  return null;
}

function _nowStrings() {
  const d = new Date();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const yyyy = String(d.getFullYear());
  const dateStr = `${mm}/${dd}/${yyyy}`;
  const timeStr = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return { dateStr, timeStr };
}

function _parseUnits(raw) {
  const s = String(raw || "").trim();
  if (!s) return [];
  return s
    .replace(/,+/g, " ")
    .split(/\s+/)
    .map((t) => t.trim())
    .filter(Boolean);
}

function _findCalltakerTypeSelect() {
  const selects = Array.from(document.querySelectorAll("select"));
  for (const s of selects) {
    const texts = Array.from(s.options || []).map((o) => (o.textContent || "").trim().toUpperCase());
    if (texts.includes("THERMAL EVENT") && texts.includes("PERSONAL MEDICAL")) return s;
  }
  return null;
}

function _applyTypeOptions(targetSelect) {
  if (!targetSelect) return;

  const src = _findCalltakerTypeSelect();
  if (src) {
    targetSelect.innerHTML = src.innerHTML;
    return;
  }

  targetSelect.innerHTML = `
    <option value="" selected disabled>Select type…</option>
    <optgroup label="FIRE">
      <option value="THERMAL EVENT">THERMAL EVENT</option>
      <option value="VEGETATION FIRE">VEGETATION FIRE</option>
    </optgroup>
    <optgroup label="EMS">
      <option value="PERSONAL MEDICAL">PERSONAL MEDICAL</option>
      <option value="INJURY">INJURY</option>
      <option value="FALL">FALL</option>
    </optgroup>
    <optgroup label="RESCUE">
      <option value="RESCUE">RESCUE</option>
    </optgroup>
    <optgroup label="OPS">
      <option value="MVA">MVA</option>
      <option value="TRANSPORT">TRANSPORT</option>
      <option value="TEST">TEST</option>
      <option value="DAILY LOG">DAILY LOG</option>
    </optgroup>
  `;
}

export const UAW = {
  // ------------------------------------------------------------
  // OPEN / CLOSE
  // ------------------------------------------------------------
  async open(unitId, rowElem) {
    if (!unitId || !rowElem) return;

    await this.close();

    _ensureStyles();
    await _loadKnownUnits();

    _unitId = unitId;
    _incidentId = null;

    _isApparatus = false;
    _parentApparatusId = null;
    _crew = [];

    if (!_validateKnownUnitOrWarn(_unitId)) return;

    _anchorRect = rowElem.getBoundingClientRect();

    const ctx = await _tryGetUnitContext(unitId);
    if (ctx && (ctx.active_incident_id || ctx.incident_id)) {
      _incidentId = Number(ctx.active_incident_id || ctx.incident_id);
    }

    _isApparatus = !!ctx?.is_apparatus;
    _parentApparatusId = ctx?.parent_apparatus_id || null;
    _crew = Array.isArray(ctx?.crew) ? ctx.crew : [];

    _popup = document.createElement("div");
    _popup.className = "uaw-popup";
    _popup.dataset.mode = "menu";
    _popup.style.visibility = "hidden";
    _popup.style.left = "-9999px";
    _popup.style.top = "-9999px";
    document.body.appendChild(_popup);

    _render(this._menuHTML(false));
    _placePopup("anchor", true);  // showAfter=true sets visibility after positioning

    _bindActions();
    _setOutsideAndKeyHandlers();
    _focusFirst();
  },

  async openIncidentUnit(incidentId, unitId, rowElem) {
    if (!incidentId || !unitId || !rowElem) return;

    await this.close();

    _ensureStyles();
    await _loadKnownUnits();

    _unitId = unitId;
    _incidentId = Number(incidentId);

    _isApparatus = false;
    _parentApparatusId = null;
    _crew = [];

    if (!_validateKnownUnitOrWarn(_unitId)) return;

    _anchorRect = rowElem.getBoundingClientRect();

    const ctx = await _tryGetUnitContext(unitId);
    _isApparatus = !!ctx?.is_apparatus;
    _parentApparatusId = ctx?.parent_apparatus_id || null;
    _crew = Array.isArray(ctx?.crew) ? ctx.crew : [];

    _popup = document.createElement("div");
    _popup.className = "uaw-popup";
    _popup.dataset.mode = "menu";
    _popup.style.visibility = "hidden";
    _popup.style.left = "-9999px";
    _popup.style.top = "-9999px";
    document.body.appendChild(_popup);

    _render(this._menuHTML(true));
    _placePopup("anchor", true);  // showAfter=true sets visibility after positioning

    _bindActions();
    _setOutsideAndKeyHandlers();
    _focusFirst();
  },

  // Drag helper: open incident-scoped UAW and jump directly to Clear/Disposition
  async openIncidentUnitAndClear(incidentId, unitId, rowElem) {
    await this.openIncidentUnit(incidentId, unitId, rowElem);
    this._showClearOptions();
  },

  async close() {
    if (_popup) _popup.remove();
    _popup = null;

    _unitId = null;
    _incidentId = null;

    _isApparatus = false;
    _parentApparatusId = null;
    _crew = [];

    _removeHandlers();
  },

  // ------------------------------------------------------------
  // MENU TEMPLATE
  // ------------------------------------------------------------
  _menuHTML(incidentScoped = false) {
    const hasInc = !!_incidentId;
    const dispatchDisabled = incidentScoped || hasInc;

    const crewLine = _isApparatus
      ? (_crew?.length ? `Crew: ${_crew.length}` : "No crew")
      : (_parentApparatusId ? `On: ${_parentApparatusId}` : "Unassigned");

    const sub = hasInc ? `Inc #${_incidentId}` : crewLine;

    const assignLabel = _isApparatus ? "Manage Crew" : "Assign to Apparatus";
    const assignAction = _isApparatus ? "crew" : "assign";

    return `
      <div class="uaw-head">
        <div class="uaw-title">${_unitId || ""}</div>
        <div class="uaw-sub">${sub}</div>
      </div>

      <div class="uaw-grid">
        <button data-action="dispatch" ${dispatchDisabled ? "disabled" : ""}>Dispatch to Incident</button>
        <button data-action="create_incident">New Self-Initiated</button>
        <div class="uaw-separator"></div>
        <button data-action="enroute" ${hasInc ? "" : "disabled"}>Enroute</button>
        <button data-action="arrive" ${hasInc ? "" : "disabled"}>Arrived</button>
        <button data-action="transport" ${hasInc ? "" : "disabled"}>Transporting</button>
        <button data-action="at_medical" ${hasInc ? "" : "disabled"}>At Medical</button>
        <button data-action="clear">Clear / Available</button>
        <div class="uaw-separator"></div>
        <button data-action="add_remark">Add Remark</button>
        <button data-action="misc">Set Misc Status</button>
        <button data-action="ten7">10-7 (Out of Service)</button>
        <button data-action="transfer-command" ${hasInc ? "" : "disabled"}>Transfer Command</button>
        <div class="uaw-separator"></div>
        <button data-action="${assignAction}">${assignLabel}</button>
      </div>
    `;
  },

  // ------------------------------------------------------------
  // MINI CALLTAKER
  // ------------------------------------------------------------
  _exitMiniCalltaker() {
    if (!_popup) return;

    _popup.classList.remove("uaw-wide");
    _popup.dataset.mode = "menu";

    _render(this._menuHTML(false));
    _bindActions();

    _onEscape = null;
    _onEnter = null;

    _placePopup("anchor");
    _focusFirst();
  },

  _showMiniCalltaker() {
    if (!_popup) return;

    _popup.classList.add("uaw-wide");
    _popup.dataset.mode = "mini-calltaker";

    const uid = _unitId || "";
    const { dateStr, timeStr } = _nowStrings();

    _render(`
      <div class="uaw-head">
        <div class="uaw-title">New Self-Initiated</div>
        <div class="uaw-sub">${uid} - Enter to Save, Esc to Cancel</div>
      </div>

      <div class="uaw-scroll">
        <div class="uaw-form">

          <div class="uaw-row-3">
            <div>
              <label>Incident #</label>
              <input id="uaw-ct-incident" type="text" placeholder="(auto on save)" value="" disabled />
            </div>
            <div>
              <label>Date</label>
              <input id="uaw-ct-date" type="text" value="${dateStr}" disabled />
            </div>
            <div>
              <label>Time</label>
              <input id="uaw-ct-time" type="text" value="${timeStr}" disabled />
            </div>
          </div>

          <div class="uaw-row-2">
            <div>
              <label>Location *</label>
              <input id="uaw-ct-location" type="text" placeholder="Required" data-autofocus="1" />
            </div>
            <div>
              <label>Node</label>
              <input id="uaw-ct-node" type="text" placeholder="Optional" />
            </div>
          </div>

          <div class="uaw-row-2">
            <div>
              <label>Pole Alpha</label>
              <input id="uaw-ct-pole-alpha" type="text" placeholder="Optional" />
            </div>
            <div>
              <label>Pole Alpha Dec</label>
              <input id="uaw-ct-pole-alpha-dec" type="text" placeholder="Optional" />
            </div>
          </div>

          <div class="uaw-row-2">
            <div>
              <label>Pole Number</label>
              <input id="uaw-ct-pole-number" type="text" placeholder="Optional" />
            </div>
            <div>
              <label>Pole Number Dec</label>
              <input id="uaw-ct-pole-number-dec" type="text" placeholder="Optional" />
            </div>
          </div>

          <div>
            <label>Type *</label>
            <select id="uaw-ct-type" required></select>
          </div>

          <div id="uaw-ct-subtype-row" style="display:none;">
            <label>Daily Log Category *</label>
            <select id="uaw-ct-subtype">
              <option value="">Select category...</option>
              <option value="BUILDING/RISER CHECKS">BUILDING/RISER CHECKS</option>
              <option value="TRAINING">TRAINING</option>
              <option value="MAINTENANCE">MAINTENANCE</option>
              <option value="SAFETY WALK">SAFETY WALK</option>
              <option value="VEHICLE INSPECTION">VEHICLE INSPECTION</option>
              <option value="BUMP TEST">BUMP TEST</option>
              <option value="STANDBY">STANDBY</option>
              <option value="AED CHECK">AED CHECK</option>
              <option value="EXTINGUISHER CHECK">EXTINGUISHER CHECK</option>
              <option value="OTHER">OTHER</option>
            </select>
          </div>

          <div>
            <label>Narrative</label>
            <textarea id="uaw-ct-narrative" placeholder="What happened?"></textarea>
          </div>

          <div class="uaw-row-2">
            <div>
              <label>Caller (Unit)</label>
              <input id="uaw-ct-caller" type="text" value="${uid}" disabled />
            </div>
            <div>
              <label>Additional Units</label>
              <input id="uaw-ct-units" type="text" placeholder="Optional (e.g., Engine1 Medic1)" />
            </div>
          </div>

          <div class="uaw-actions">
            <button id="uaw-ct-save">Save</button>
            <button id="uaw-ct-cancel" type="button">Cancel</button>
          </div>

        </div>
      </div>
    `);

    try { _applyTypeOptions(_popup.querySelector("#uaw-ct-type")); } catch (_) {}

    // Show/hide subtype dropdown based on type selection
    const typeSelect = _popup.querySelector("#uaw-ct-type");
    const subtypeRow = _popup.querySelector("#uaw-ct-subtype-row");
    if (typeSelect && subtypeRow) {
      typeSelect.addEventListener("change", () => {
        const val = (typeSelect.value || "").toUpperCase();
        subtypeRow.style.display = (val === "DAILY LOG") ? "block" : "none";
      });
    }

    _placePopup("center");

    const cancel = () => this._exitMiniCalltaker();

    const submit = async () => {
      if (!_popup) return;

      const saveBtn = _popup.querySelector("#uaw-ct-save");
      if (saveBtn) saveBtn.disabled = true;

      const location = (_popup.querySelector("#uaw-ct-location")?.value || "").trim();
      const node = (_popup.querySelector("#uaw-ct-node")?.value || "").trim();

      const pole_alpha = (_popup.querySelector("#uaw-ct-pole-alpha")?.value || "").trim();
      const pole_alpha_dec = (_popup.querySelector("#uaw-ct-pole-alpha-dec")?.value || "").trim();
      const pole_number = (_popup.querySelector("#uaw-ct-pole-number")?.value || "").trim();
      const pole_number_dec = (_popup.querySelector("#uaw-ct-pole-number-dec")?.value || "").trim();

      const type = (_popup.querySelector("#uaw-ct-type")?.value || "").trim();
      const subtype = (_popup.querySelector("#uaw-ct-subtype")?.value || "").trim();
      const narrative = (_popup.querySelector("#uaw-ct-narrative")?.value || "").trim();

      let unitsRaw = (_popup.querySelector("#uaw-ct-units")?.value || "").trim();
      let units = _parseUnits(unitsRaw);
      if (!units.includes(String(uid))) units.unshift(String(uid));
      units = units.filter(Boolean);

      if (!location) {
        _safeAlert("Location is required.");
        try { _popup.querySelector("#uaw-ct-location")?.focus(); } catch (_) {}
        if (saveBtn) saveBtn.disabled = false;
        return;
      }
      if (!type) {
        _safeAlert("Type is required.");
        try { _popup.querySelector("#uaw-ct-type")?.focus(); } catch (_) {}
        if (saveBtn) saveBtn.disabled = false;
        return;
      }
      if (type.toUpperCase() === "DAILY LOG" && !subtype) {
        _safeAlert("Daily Log category is required.");
        try { _popup.querySelector("#uaw-ct-subtype")?.focus(); } catch (_) {}
        if (saveBtn) saveBtn.disabled = false;
        return;
      }
      if (!_validateUnitListOrWarn(units)) {
        if (saveBtn) saveBtn.disabled = false;
        return;
      }

      try {
        const created = await CAD_UTIL.postJSON("/incident/new", {});
        if (!created?.ok || !created?.incident_id) {
          _safeAlert(created?.error || "Unable to create incident.");
          if (saveBtn) saveBtn.disabled = false;
          return;
        }

        const newId = created.incident_id;

        try {
          const incEl = _popup.querySelector("#uaw-ct-incident");
          if (incEl) incEl.value = String(newId);
        } catch (_) {}

        const payload = {
          location,
          node,
          pole_alpha,
          pole_alpha_dec,
          pole_number,
          pole_number_dec,
          type,
          subtype: (type.toUpperCase() === "DAILY LOG") ? subtype : null,
          narrative,
          caller_name: uid,
        };

        const saved = await CAD_UTIL.postJSON(`/incident/save/${encodeURIComponent(newId)}`, payload);
        if (!saved?.ok) {
          _safeAlert(saved?.error || "Unable to save incident.");
          if (saveBtn) saveBtn.disabled = false;
          return;
        }

        await CAD_UTIL.postJSON("/api/cli/dispatch", {
          units,
          incident_id: Number(newId),
          mode: "D"
        });

        try {
          await CAD_UTIL.postJSON("/remark", {
            incident_id: Number(newId),
            unit_id: String(uid),
            text: `SELF INITIATED by ${uid}`
          });
        } catch (_) {}

        _refreshPanels();
        await this.close();
      } catch (e) {
        console.error("[UAW] mini calltaker save failed", e);
        _safeAlert("Create/Save failed.");
        if (saveBtn) saveBtn.disabled = false;
      }
    };

    _popup.querySelector("#uaw-ct-cancel")?.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      cancel();
    });

    _popup.querySelector("#uaw-ct-save")?.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      submit();
    });

    _onEscape = cancel;
    _onEnter = submit;

    _focusFirst("#uaw-ct-location");
  },

  // ------------------------------------------------------------
  // APPARATUS CREW (Assignments)
  // ------------------------------------------------------------
  async _showAssignToApparatus() {
    if (!_popup || !_unitId) return;
    if (_isApparatus) return;

    const uid = _unitId;

    let list = null;
    try {
      list = await _getApparatusList();
    } catch (_) {}

    const apparatus = Array.isArray(list?.apparatus) ? list.apparatus : [];
    const current = _parentApparatusId || "";

    const options = apparatus.map((a) => {
      const val = String(a.unit_id || "").trim();
      const label = String(a.name || val || "").trim();
      const sel = (val && val === current) ? "selected" : "";
      return `<option value="${val}" ${sel}>${label}</option>`;
    }).join("");

    _render(`
      <div class="uaw-head">
        <div class="uaw-title">Assign to Apparatus</div>
        <div class="uaw-sub">${uid} - Current: ${current || "None"}</div>
      </div>

      <div class="uaw-field">
        <label>Select Apparatus</label>
        <select id="uaw-assign-apparatus" class="uaw-input" data-autofocus="1">
          <option value="">(Unassigned)</option>
          ${options}
        </select>
      </div>

      <div class="uaw-foot">
        <button data-back>Back</button>
        <button class="uaw-primary" id="uaw-assign-save">Save</button>
      </div>
    `);

    const back = () => {
      _render(this._menuHTML(!!_incidentId));
      _bindActions();
      _onEscape = null;
      _onEnter = null;
      _focusFirst();
    };

    _popup.querySelector("[data-back]")?.addEventListener("click", (e) => {
      e.stopPropagation();
      back();
    });

    _popup.querySelector("#uaw-assign-save")?.addEventListener("click", async (e) => {
      e.stopPropagation();
      const sel = (_popup.querySelector("#uaw-assign-apparatus")?.value || "").trim();
      try {
        if (!sel) await _postCrewUnassign(uid);
        else await _postCrewAssign(sel, uid);

        _refreshPanels();
        await this.close();
      } catch (ex) {
        console.error("[UAW] assign save failed:", ex);
        _safeAlert("Assignment save failed.");
      }
    });

    _onEscape = back;
    _onEnter = () => _popup.querySelector("#uaw-assign-save")?.click();

    _focusFirst("#uaw-assign-apparatus");
  },

  async _showCrewAssignments() {
    if (!_popup || !_unitId) return;
    if (!_isApparatus) return;

    const aid = _unitId;

    let ctx = null;
    try {
      ctx = await _tryGetUnitContext(aid);
    } catch (_) {}

    const crew = Array.isArray(ctx?.crew) ? ctx.crew : [];

    const rows = crew.map((p) => {
      const pid = String(p.personnel_id || "").trim();
      const role = String(p.role || "").trim();
      return `
        <div class="uaw-row">
          <div class="uaw-row-main">
            <strong>${pid}</strong>
            ${role ? `<span class="uaw-pill">${role}</span>` : ""}
          </div>
          <button class="uaw-btn-small" data-pid="${pid}" data-remove="1">Remove</button>
        </div>
      `;
    }).join("");

    _render(`
      <div class="uaw-head">
        <div class="uaw-title">Crew - ${aid}</div>
        <div class="uaw-sub">${crew.length} assigned</div>
      </div>

      <div class="uaw-field">
        <label>Add Personnel</label>
        <div class="uaw-inline" style="padding:0;">
          <input id="uaw-crew-pid" class="uaw-input" placeholder="Unit ID" data-autofocus="1" style="flex:1;" />
          <input id="uaw-crew-role" class="uaw-input" placeholder="Role" style="flex:1;" />
          <button id="uaw-crew-add">Add</button>
        </div>
      </div>

      ${rows ? rows : `<div class="uaw-muted">No crew assigned</div>`}

      <div class="uaw-foot">
        <button data-back>Back</button>
        <button class="uaw-primary" id="uaw-crew-refresh">Refresh</button>
      </div>
    `);

    const back = () => {
      _render(this._menuHTML(!!_incidentId));
      _bindActions();
      _onEscape = null;
      _onEnter = null;
      _focusFirst();
    };

    const refresh = async () => {
      await this._showCrewAssignments();
    };

    _popup.querySelector("[data-back]")?.addEventListener("click", (e) => {
      e.stopPropagation();
      back();
    });

    _popup.querySelector("#uaw-crew-refresh")?.addEventListener("click", (e) => {
      e.stopPropagation();
      refresh();
    });

    _popup.querySelector("#uaw-crew-add")?.addEventListener("click", async (e) => {
      e.stopPropagation();
      const pid = (_popup.querySelector("#uaw-crew-pid")?.value || "").trim();
      const role = (_popup.querySelector("#uaw-crew-role")?.value || "").trim();
      if (!pid) return;

      if (!_validateKnownUnitOrWarn(pid)) return;

      try {
        const res = await _postCrewAssign(aid, pid, role);
        if (res?.ok === false) {
          _safeAlert(res?.error || "Crew assign rejected.");
          return;
        }
        _refreshPanels();
        await refresh();
      } catch (ex) {
        console.error("[UAW] crew add failed:", ex);
        _safeAlert("Crew add failed.");
      }
    });

    _popup.querySelectorAll("[data-remove='1']").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const pid = (btn.getAttribute("data-pid") || "").trim();
        if (!pid) return;

        try {
          const res = await _postCrewUnassign(pid, aid);
          if (res?.ok === false) {
            _safeAlert(res?.error || "Crew remove rejected.");
            return;
          }
          _refreshPanels();
          await refresh();
        } catch (ex) {
          console.error("[UAW] crew remove failed:", ex);
          _safeAlert("Crew remove failed.");
        }
      });
    });

    _onEscape = back;
    _onEnter = () => _popup.querySelector("#uaw-crew-add")?.click();

    _focusFirst("#uaw-crew-pid");
  },

  // ------------------------------------------------------------
  // ACTIONS
  // ------------------------------------------------------------
  async _handle(action) {
    const uid = _unitId;
    if (!uid) return;

    if (!_validateKnownUnitOrWarn(uid)) return;

    if (action === "close") {
      await this.close();
      return;
    }

    if (action === "assign") {
      await this._showAssignToApparatus();
      return;
    }

    if (action === "crew") {
      await this._showCrewAssignments();
      return;
    }

    if (action === "dispatch") {
      if (_incidentId) return;
      this._showDispatch();
      return;
    }

    if (action === "misc") {
      this._showMisc();
      return;
    }

    if (action === "transfer-command") {
      this._showTransferCommand();
      return;
    }

    if (action === "create_incident") {
      this._showMiniCalltaker();
      return;
    }

    if (["enroute", "arrive", "transport", "at_medical"].includes(action)) {
      if (!_incidentId) return;

      const map = {
        enroute: "ENROUTE",
        arrive: "ARRIVED",
        transport: "TRANSPORTING",
        at_medical: "AT_MEDICAL",
      };

      try {
        const res = await _postUnitStatus(uid, map[action]);
        if (res?.ok === false) {
          _safeAlert(res?.error || "Unit action rejected by backend.");
          return;
        }
        _refreshPanels();
        await this.close();
      } catch (err) {
        console.error("[UAW] status update failed:", err);
        _safeAlert("Unit action failed.");
      }
      return;
    }

    if (action === "ten7") {
      try {
        await _postUnitMisc(uid, "10-7");
        _refreshPanels();
      } catch (err) {
        console.error("[UAW] 10-7 failed:", err);
        _safeAlert("10-7 failed.");
      }
      await this.close();
      return;
    }

    if (action === "clear") {
      this._showClearOptions();
      return;
    }

    if (action === "add_remark") {
      this._showQuickRemark();
      return;
    }
  },

  // ------------------------------------------------------------
  // DISPATCH
  // ------------------------------------------------------------
  async _showDispatch() {
    if (!_popup || !_unitId) return;

    const uid = _unitId;

    const rows = await _tryGetDispatchTargets();

    if (Array.isArray(rows) && rows.length > 0) {
      const list = rows
        .map((r) => {
          const label = `${r.incident_number || r.incident_id} - ${r.type || ""} - ${r.location || ""}`.trim();
          return `<button class="uaw-list-item" data-inc="${r.incident_id}">${label}</button>`;
        })
        .join("");

      _render(`
        <div class="uaw-head">
          <div class="uaw-title">Dispatch ${uid}</div>
          <div class="uaw-sub">Select incident</div>
        </div>
        <div class="uaw-list">
          ${list}
        </div>
        <div class="uaw-foot">
          <button data-back>Back</button>
        </div>
      `);

      const back = () => {
        _render(this._menuHTML(false));
        _bindActions();
        _onEscape = null;
        _onEnter = null;
        _focusFirst();
      };

      _popup.querySelector("[data-back]")?.addEventListener("click", (e) => {
        e.stopPropagation();
        back();
      });

      _onEscape = back;
      _onEnter = null;

      _popup.querySelectorAll(".uaw-list-item").forEach((btn) => {
        btn.addEventListener("click", async (e) => {
          e.stopPropagation();
          const incId = Number(btn.dataset.inc);
          if (!incId) return;

          try {
            const res = await _postUnitDispatch(uid, incId);
            if (res?.ok === false) {
              _safeAlert(res?.error || "Dispatch rejected by backend.");
              return;
            }

            try { await _postUnitStatus(uid, "DISPATCHED"); } catch (_) {}

            _refreshPanels();
          } catch (err) {
            console.error("[UAW] dispatch failed:", err);
            _safeAlert("Dispatch failed.");
          }

          await this.close();
        });
      });

      _focusFirst(".uaw-list-item");
      return;
    }

    _render(`
      <div class="uaw-head">
        <div class="uaw-title">Dispatch ${uid}</div>
        <div class="uaw-sub">Enter Incident ID</div>
      </div>

      <div class="uaw-inline">
        <input id="uaw-dispatch-incident" type="number" placeholder="Incident ID..." data-autofocus="1" />
        <button id="uaw-dispatch-go">Go</button>
      </div>

      <div class="uaw-foot">
        <button data-back>Back</button>
      </div>
    `);

    const back = () => {
      _render(this._menuHTML(false));
      _bindActions();
      _onEscape = null;
      _onEnter = null;
      _focusFirst();
    };

    const submit = async () => {
      const incVal = (_popup.querySelector("#uaw-dispatch-incident")?.value || "").trim();
      const incId = Number(incVal);
      if (!incId) return;

      try {
        const res = await _postUnitDispatch(uid, incId);
        if (res?.ok === false) {
          _safeAlert(res?.error || "Dispatch rejected by backend.");
          return;
        }

        try { await _postUnitStatus(uid, "DISPATCHED"); } catch (_) {}

        _refreshPanels();
        await this.close();
      } catch (err) {
        console.error("[UAW] dispatch failed:", err);
        _safeAlert("Dispatch failed.");
      }
    };

    _popup.querySelector("[data-back]")?.addEventListener("click", (e) => {
      e.stopPropagation();
      back();
    });

    _popup.querySelector("#uaw-dispatch-go")?.addEventListener("click", (e) => {
      e.stopPropagation();
      submit();
    });

    _onEscape = back;
    _onEnter = submit;

    _focusFirst("#uaw-dispatch-incident");
  },

  // ------------------------------------------------------------
  // CLEAR OPTIONS
  // ------------------------------------------------------------
  _showClearOptions() {
    if (!_popup) return;

    const uid = _unitId;
    const inc = _incidentId;

    _render(`
      <div class="uaw-head">
        <div class="uaw-title">Clear ${uid}</div>
        <div class="uaw-sub">${inc ? `Inc #${inc}` : "Not assigned"}</div>
      </div>

      <div class="uaw-grid">
        ${inc ? `
          <button data-clear="unit">Clear Unit (Return Available)</button>
          <button data-clear="all">Clear All Units on Incident</button>
        ` : `
          <button data-clear="avail">Set Available</button>
          <button data-clear="misc">Clear Misc Status Only</button>
        `}
        <div class="uaw-separator"></div>
        <button data-clear="back">Back</button>
      </div>
    `);

    const back = () => {
      _render(this._menuHTML(!!inc));
      _bindActions();
      _onEscape = null;
      _onEnter = null;
      _focusFirst();
    };

    _onEscape = back;
    _onEnter = null;

    _popup.querySelectorAll("[data-clear]").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const mode = btn.dataset.clear;

        if (mode === "back") {
          back();
          return;
        }

        if (!inc) {
          if (mode === "misc") {
            try {
              await _postUnitMisc(uid, "");
              _refreshPanels();
            } catch (err) {
              console.error("[UAW] clear misc failed:", err);
              _safeAlert("Clear misc failed.");
            }
            await this.close();
            return;
          }

          if (mode === "avail") {
            try {
              await _postUnitMisc(uid, "");
              await _postUnitStatus(uid, "AVAILABLE");
              _refreshPanels();
            } catch (err) {
              console.error("[UAW] set available failed:", err);
              _safeAlert("Set available failed.");
            }
            await this.close();
            return;
          }

          return;
        }

        if (mode === "unit") {
          try {
            const dispo = prompt("Unit disposition code (R/NA/NF/C/CT/O). Enter H to HOLD the incident:", "R") || "R";
            const code = dispo.trim().toUpperCase();
            const note = (code === "H")
              ? (prompt("Held reason (required):", "") || "")
              : (prompt("Disposition note (optional):", "") || "");

            if (code === "H") {
              if (!note.trim()) {
                _safeAlert("Held requires a reason.");
                return;
              }
              const held = await CAD_UTIL.postJSON(`/incident/${encodeURIComponent(inc)}/hold`, { reason: note.trim() });
              if (held?.ok === false) {
                _safeAlert(held?.error || "Unable to hold incident.");
                return;
              }
              _refreshPanels();
              await this.close();
              return;
            }

            const res = await _postUnitClear(uid, inc, code, note);

            if (res?.ok === false) {
              _safeAlert(res?.error || "Clear rejected by backend.");
              return;
            }

            try { await _postUnitMisc(uid, ""); } catch (_) {}

            _refreshPanels();

            const needs = !!(res?.requires_event_disposition || res?.last_unit_cleared || res?.requires_disposition);
            await this.close();
            if (needs) {
              try { DISP.open(inc); } catch (_) {}
            }
          } catch (err) {
            console.error("[UAW] clear unit failed:", err);
            _safeAlert("Clear failed.");
          }
          return;
        }

        if (mode === "all") {
          try {
            const res = await CAD_UTIL.postJSON("/api/uaw/clear_all", { incident_id: inc });
            _refreshPanels();

            const needs = !!(res?.requires_event_disposition || res?.last_unit_cleared || res?.requires_disposition);
            await this.close();

            if (needs) {
              try { DISP.open(inc); } catch (_) {}
            }
          } catch (err) {
            console.error("[UAW] clear all failed:", err);
            _safeAlert("Clear All failed (endpoint missing or error).");
            await this.close();
          }
        }
      });
    });

    _focusFirst("[data-clear]");
  },

  // ------------------------------------------------------------
  // QUICK REMARK
  // ------------------------------------------------------------
  _showQuickRemark() {
    if (!_popup) return;

    const uid = _unitId;
    const inc = _incidentId;

    _render(`
      <div class="uaw-head">
        <div class="uaw-title">Add Remark</div>
        <div class="uaw-sub">${uid}${inc ? ` - Inc #${inc}` : ""}</div>
      </div>

      <div class="uaw-inline">
        <input id="uaw-remark-input" type="text" placeholder="Type remark..." data-autofocus="1" />
        <button id="uaw-remark-submit">Send</button>
      </div>

      <div class="uaw-foot">
        <button data-back>Cancel</button>
      </div>
    `);

    const back = () => {
      _render(this._menuHTML(!!inc));
      _bindActions();
      _onEscape = null;
      _onEnter = null;
      _focusFirst();
    };

    const submit = async () => {
      const text = (_popup.querySelector("#uaw-remark-input")?.value || "").trim();
      if (!text) return;

      try {
        const res = await CAD_UTIL.postJSON("/remark", {
          incident_id: inc || null,
          unit_id: uid,
          text,
        });

        if (res?.ok === false) {
          _safeAlert(res?.error || "Remark rejected by backend.");
          return;
        }

        _refreshPanels();
        await this.close();
      } catch (e) {
        console.error("[UAW] remark failed", e);
        _safeAlert("Remark failed.");
      }
    };

    _popup.querySelector("[data-back]")?.addEventListener("click", (e) => {
      e.stopPropagation();
      back();
    });

    _popup.querySelector("#uaw-remark-submit")?.addEventListener("click", (e) => {
      e.stopPropagation();
      submit();
    });

    _onEscape = back;
    _onEnter = submit;

    _focusFirst("#uaw-remark-input");
  },

  // ------------------------------------------------------------
  // MISC STATUS
  // ------------------------------------------------------------
  _showMisc() {
    if (!_popup) return;

    const uid = _unitId;
    const inc = _incidentId;

    _render(`
      <div class="uaw-head">
        <div class="uaw-title">Misc Status</div>
        <div class="uaw-sub">${uid}</div>
      </div>

      <div class="uaw-inline">
        <input id="uaw-misc-input" type="text" placeholder="Enter status..." data-autofocus="1" />
        <button id="uaw-misc-save">Save</button>
      </div>

      <div class="uaw-foot">
        <button data-back>Back</button>
      </div>
    `);

    const back = () => {
      _render(this._menuHTML(!!inc));
      _bindActions();
      _onEscape = null;
      _onEnter = null;
      _focusFirst();
    };

    const submit = async () => {
      const val = (_popup.querySelector("#uaw-misc-input")?.value || "").trim();

      try {
        const res = await _postUnitMisc(uid, val);
        if (res?.ok === false) {
          _safeAlert(res?.error || "Misc status rejected by backend.");
          return;
        }
        _refreshPanels();
        await this.close();
      } catch (err) {
        console.error("[UAW] misc failed:", err);
        _safeAlert("Misc status failed.");
      }
    };

    _popup.querySelector("[data-back]")?.addEventListener("click", (e) => {
      e.stopPropagation();
      back();
    });

    _popup.querySelector("#uaw-misc-save")?.addEventListener("click", (e) => {
      e.stopPropagation();
      submit();
    });

    _onEscape = back;
    _onEnter = submit;

    _focusFirst("#uaw-misc-input");
  },

  // ------------------------------------------------------------
  // TRANSFER COMMAND
  // ------------------------------------------------------------
  async _showTransferCommand() {
    if (!_popup || !_unitId || !_incidentId) return;

    const uid = _unitId;

    let list = [];
    try {
      list = await _getUnitsOnScene(uid);
    } catch (e) {
      console.error("[UAW] units_on_scene load failed", e);
    }

    const options = (list || [])
      .map((u) => `<option value="${u.unit_id}">${u.unit_id}</option>`)
      .join("");

    _render(`
      <div class="uaw-head">
        <div class="uaw-title">Transfer Command</div>
        <div class="uaw-sub">${uid} - Inc #${_incidentId}</div>
      </div>

      <div class="uaw-inline">
        <select id="uaw-cmd-select" data-autofocus="1">
          <option value="">Select unit...</option>
          ${options}
        </select>
        <button id="uaw-cmd-go">Go</button>
      </div>

      <div class="uaw-foot">
        <button data-back>Back</button>
      </div>
    `);

    const back = () => {
      _render(this._menuHTML(true));
      _bindActions();
      _onEscape = null;
      _onEnter = null;
      _focusFirst();
    };

    const submit = async () => {
      const newCmd = (_popup.querySelector("#uaw-cmd-select")?.value || "").trim();
      if (!newCmd) return;

      if (_knownUnits && !_knownUnits.has(String(newCmd))) {
        _safeAlert(`Unknown unit ID: ${newCmd}`);
        return;
      }

      try {
        const res = await _postTransferCommand(uid, newCmd);
        if (res?.ok === false) {
          _safeAlert(res?.error || "Transfer command rejected by backend.");
          return;
        }
        _refreshPanels();
        await this.close();
      } catch (err) {
        console.error("[UAW] transfer command failed:", err);
        _safeAlert("Transfer command failed.");
      }
    };

    _popup.querySelector("[data-back]")?.addEventListener("click", (e) => {
      e.stopPropagation();
      back();
    });

    _popup.querySelector("#uaw-cmd-go")?.addEventListener("click", (e) => {
      e.stopPropagation();
      submit();
    });

    _onEscape = back;
    _onEnter = submit;

    _focusFirst("#uaw-cmd-select");
  },
};

globalThis.UAW = UAW;

console.log("[UAW] Inline popup UAW module loaded (crew assignments + registry validation + mini calltaker + disposition forcing).");
export default UAW;
