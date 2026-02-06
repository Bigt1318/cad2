// ============================================================================
// FORD CAD — INCIDENT DISPOSITION (INLINE SMALL BOX)
// Phase-3 Canonical
//
// RULE:
//   - Do NOT force-open IAW when disposition is needed.
//   - If IAW is already open for the incident, use its inline section.
//   - Otherwise, show a small inline disposition box (no IAW modal).
// ============================================================================

import CAD_UTIL from "./utils.js";
import IAW from "./iaw.js";

let _overlay = null;

function _closePopup() {
  if (_overlay) _overlay.remove();
  _overlay = null;
}

function _ensurePopupStyles() {
  if (document.getElementById("disp-inline-style")) return;

  const style = document.createElement("style");
  style.id = "disp-inline-style";
  style.textContent = `
    .disp-overlay{
      position:fixed; inset:0;
      background:rgba(0,0,0,.45);
      z-index:1200;
      display:flex;
      align-items:center;
      justify-content:center;
      padding:16px;
    }
    .disp-box{
      width:380px;
      max-width:92vw;
      background:#ffffff;
      border:1px solid #cfd8e3;
      border-radius:12px;
      box-shadow:0 12px 30px rgba(0,0,0,.25);
      overflow:hidden;
      color:#0b1b2a;
      font-family:system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
    }
    .disp-head{
      padding:10px 12px;
      background:#f4f7fb;
      border-bottom:1px solid #eef2f7;
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:10px;
    }
    .disp-title{ font-weight:900; font-size:14px; }
    .disp-close{
      border:0;
      background:transparent;
      font-size:18px;
      cursor:pointer;
      color:#0b1b2a;
      padding:0 6px;
    }
    .disp-body{
      padding:12px;
      display:flex;
      flex-direction:column;
      gap:10px;
    }
    .disp-body label{ font-size:12px; font-weight:800; opacity:.85; }
    .disp-body select, .disp-body input{
      width:100%;
      border:1px solid #cfd8e3;
      border-radius:8px;
      padding:8px;
      font-weight:700;
      font-size:12px;
      outline:none;
      color:#0b1b2a;
      background:#ffffff;
    }
    .disp-actions{
      display:flex;
      gap:8px;
      justify-content:flex-end;
      padding-top:2px;
    }
    .disp-actions button{
      appearance:none;
      border:1px solid #cfd8e3;
      background:#ffffff;
      border-radius:8px;
      padding:8px 10px;
      font-weight:900;
      font-size:12px;
      cursor:pointer;
      color:#0b1b2a;
    }
    .disp-actions button:hover{ background:#f0f6ff; }
    .disp-actions button:disabled{ opacity:.45; cursor:not-allowed; }
  `;
  document.head.appendChild(style);
}

function _getEventBox(incident_id) {
  return document.getElementById(`iaw-event-dispo-${String(incident_id)}`);
}

function _ensureEventBoxOpen(incident_id) {
  const box = _getEventBox(incident_id);
  if (!box) return false;

  if (box.style.display === "none" || box.style.display === "") {
    IAW.ui.toggleEventDisposition(incident_id);
  }

  const box2 = _getEventBox(incident_id);
  if (box2 && box2.style.display !== "block") box2.style.display = "block";
  return true;
}

function _setDefaultCodeIAW(incident_id, defaultCode) {
  if (!defaultCode) return;

  const box = _getEventBox(incident_id);
  if (!box) return;

  const sel = box.querySelector(`[data-role="event-dispo-code"]`);
  if (!sel) return;

  const code = String(defaultCode).trim().toUpperCase();
  const exists = Array.from(sel.options).some(o => String(o.value).toUpperCase() === code);
  if (!exists) return;

  sel.value = code;

  if (IAW?.ui?.eventCodeChanged) IAW.ui.eventCodeChanged(incident_id);
}

function _openPopup(incident_id, defaultCode = null) {
  _ensurePopupStyles();
  _closePopup();

  _overlay = document.createElement("div");
  _overlay.className = "disp-overlay";
  _overlay.addEventListener("click", (e) => {
    if (e.target === _overlay) _closePopup();
  });

  const box = document.createElement("div");
  box.className = "disp-box";

  box.innerHTML = `
    <div class="disp-head">
      <div class="disp-title">Event Disposition • Inc #${String(incident_id)}</div>
      <button class="disp-close" title="Close">✖</button>
    </div>
    <div class="disp-body">
      <div>
        <label>Code</label>
        <select id="disp-code">
          <option value="">Select code…</option>
          <option value="FA">FA — False Alarm</option>
          <option value="FF">FF — Fire Found</option>
          <option value="MF">MF — Medical First Aid</option>
          <option value="MT">MT — Medical Transport</option>
          <option value="PR">PR — Patient Refusal</option>
          <option value="NF">NF — No Finding</option>
          <option value="C">C — Cancelled</option>
          <option value="CT">CT — Cancelled Enroute</option>
          <option value="O">O — Other</option>
          <option value="H">H — Hold Incident</option>
        </select>
      </div>
      <div>
        <label>Optional remark</label>
        <input id="disp-comment" type="text" placeholder="Optional remark…" />
      </div>
      <div class="disp-actions">
        <button id="disp-cancel">Cancel</button>
        <button id="disp-submit" disabled>Submit</button>
      </div>
    </div>
  `;

  _overlay.appendChild(box);
  document.body.appendChild(_overlay);

  box.querySelector(".disp-close")?.addEventListener("click", (e) => {
    e.preventDefault(); e.stopPropagation();
    _closePopup();
  });

  const sel = box.querySelector("#disp-code");
  const comment = box.querySelector("#disp-comment");
  const submit = box.querySelector("#disp-submit");
  const cancel = box.querySelector("#disp-cancel");

  if (defaultCode) {
    const dc = String(defaultCode).trim().toUpperCase();
    const ok = Array.from(sel.options).some(o => String(o.value).toUpperCase() === dc);
    if (ok) sel.value = dc;
  }

  const sync = () => {
    submit.disabled = !(sel.value || "").trim();
  };
  sel.addEventListener("change", sync);
  sync();

  cancel.addEventListener("click", (e) => {
    e.preventDefault(); e.stopPropagation();
    _closePopup();
  });

  submit.addEventListener("click", async (e) => {
    e.preventDefault(); e.stopPropagation();

    const code = (sel.value || "").trim().toUpperCase();
    if (!code) return;

    submit.disabled = true;

    try {
      const res = await CAD_UTIL.postJSON(`/incident/${encodeURIComponent(incident_id)}/disposition`, {
        code,
        comment: (comment.value || "").trim()
      });

      if (res?.ok !== true) {
        CAD_UTIL.notify(res?.error || "Disposition rejected by backend.");
        submit.disabled = false;
        return;
      }

      CAD_UTIL.refreshPanels?.();
      _closePopup();
    } catch (err) {
      console.error("[DISPOSITION] submit failed:", err);
      CAD_UTIL.notify("Disposition submit failed.");
      submit.disabled = false;
    }
  });
}

const DISP = {

  // OPEN -> use IAW inline if already open, otherwise popup (no forced IAW)
  async open(incident_id, defaultCode = null) {
    if (!incident_id) return;

    const current = IAW.getCurrentIncidentId?.();
    const box = _getEventBox(incident_id);

    if (String(current || "") === String(incident_id) && box) {
      const ok = _ensureEventBoxOpen(incident_id);
      if (ok) _setDefaultCodeIAW(incident_id, defaultCode);
      return;
    }

    _openPopup(incident_id, defaultCode);
  },

  // SUBMIT -> if IAW inline exists, delegate. Else submit from popup (open if needed).
  async submit(incident_id) {
    if (!incident_id) return;

    const current = IAW.getCurrentIncidentId?.();
    const box = _getEventBox(incident_id);

    if (String(current || "") === String(incident_id) && box && IAW?.ui?.submitEventDisposition) {
      _ensureEventBoxOpen(incident_id);
      return IAW.ui.submitEventDisposition(incident_id);
    }

    _openPopup(incident_id, null);
  }
};

window.DISP = DISP;
Object.freeze(DISP);


export default DISP;
