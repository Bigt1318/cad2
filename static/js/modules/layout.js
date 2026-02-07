// ============================================================================
// FORD-CAD — LAYOUT CONTROLLER
// Phase-3 Canonical
// ============================================================================
// Responsibilities:
//   • Left drawer open/close
//   • Toolbar button wiring
//   • Held calls watcher (badge + alert styling)
//   • Refresh delegation (event-driven)
//   • Phase-3 Session (Login = shift context initializer)
// ============================================================================

import { CAD_MODAL } from "./modal.js";
import CAD_UTIL from "./utils.js";
import IAW from "./iaw.js";

export const LAYOUT = {};

// ---------------------------------------------------------------------------
// Drawer
// ---------------------------------------------------------------------------
function _drawerEls() {
  return {
    drawer: document.getElementById("left-drawer"),
    backdrop: document.getElementById("left-drawer-backdrop"),
    openBtn: document.getElementById("btn-app-menu"),
    closeBtn: document.getElementById("btn-drawer-close"),
  };
}

function _drawerOpen() {
  const { drawer, backdrop } = _drawerEls();
  if (!drawer || !backdrop) return;
  drawer.classList.add("is-open");
  backdrop.classList.add("is-open");
  drawer.setAttribute("aria-hidden", "false");
}

function _drawerClose() {
  const { drawer, backdrop } = _drawerEls();
  if (!drawer || !backdrop) return;
  drawer.classList.remove("is-open");
  backdrop.classList.remove("is-open");
  drawer.setAttribute("aria-hidden", "true");
}

function _drawerToggle() {
  const { drawer } = _drawerEls();
  if (!drawer) return;
  drawer.classList.contains("is-open") ? _drawerClose() : _drawerOpen();
}

function _wireDrawer() {
  const { openBtn, closeBtn, backdrop } = _drawerEls();

  if (openBtn) {
    openBtn.addEventListener("click", (e) => {
      e.preventDefault();
      _drawerToggle();
    });
  }

  if (closeBtn) {
    closeBtn.addEventListener("click", (e) => {
      e.preventDefault();
      _drawerClose();
    });
  }

  if (backdrop) {
    backdrop.addEventListener("click", (e) => {
      e.preventDefault();
      _drawerClose();
    });
  }

  // Delegated actions
  document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-drawer-action]");
    if (!el) return;

    e.preventDefault();
    const action = (el.dataset.drawerAction || "").trim();

    try {
      switch (action) {
        case "home":
          // Scroll to top / refresh main view
          window.scrollTo(0, 0);
          CAD_UTIL.refreshPanels();
          break;
        case "calls":
          // Focus calltaker panel
          document.getElementById("panel-calltaker")?.scrollIntoView({ behavior: "smooth" });
          document.getElementById("ctLocation")?.focus();
          break;
        case "units":
          // Focus units panel
          document.getElementById("panel-units")?.scrollIntoView({ behavior: "smooth" });
          break;
        case "new_incident":
          window.CALLTAKER?.startNewIncident?.();
          break;
        case "refresh":
          CAD_UTIL.refreshPanels();
          break;
        case "dailylog":
          CAD_MODAL.open("/modals/dailylog");
          break;
        case "held":
          CAD_MODAL.open("/modals/held");
          break;
        case "history":
          CAD_MODAL.open("/modals/history");
          break;
        case "settings":
          window.SETTINGS?.openModal?.();
          break;
        case "reports":
          CAD_MODAL.open("/modals/reports") || TOAST?.info?.("Reports coming soon");
          break;
        case "roster":
          CAD_MODAL.open("/modals/roster") || TOAST?.info?.("Roster management coming soon");
          break;
        case "contacts":
          CAD_MODAL.open("/modals/contacts") || TOAST?.info?.("Contacts coming soon");
          break;
        case "calendar":
          CAD_MODAL.open("/modals/calendar") || TOAST?.info?.("Calendar coming soon");
          break;
        case "keyboard_help":
          CAD_MODAL.open("/modals/keyboard_help");
          break;
        case "noop":
        default:
          break;
      }
    } finally {
      _drawerClose();
    }
  });

  // ESC closes drawer
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") _drawerClose();
  });
}

// ---------------------------------------------------------------------------
// Toolbar
// ---------------------------------------------------------------------------
function _wireToolbar() {
  const btnNew = document.getElementById("btn-new-incident");
  const btnRefresh = document.getElementById("btn-refresh");
  const btnRemark = document.getElementById("btn-add-remark");
  const btnDaily = document.getElementById("btn-dailylog");
  const btnHistory = document.getElementById("btn-history");
  const btnHeld = document.getElementById("btn-held-calls");

  if (btnNew) btnNew.addEventListener("click", () => window.CALLTAKER?.startNewIncident?.());
  if (btnRefresh) btnRefresh.addEventListener("click", () => CAD_UTIL.refreshPanels());

  if (btnRemark) {
    btnRemark.addEventListener("click", async () => {
      const inc = IAW?.getCurrentIncidentId?.();
      if (!inc) {
        alert("Open an incident first (IAW), then use Add Remark.");
        return;
      }
      await CAD_MODAL.open(`/incident/${encodeURIComponent(inc)}/remark`);
    });
  }

  if (btnDaily) btnDaily.addEventListener("click", () => CAD_MODAL.open("/modals/dailylog"));
  if (btnHistory) btnHistory.addEventListener("click", () => CAD_MODAL.open("/modals/history"));
  if (btnHeld) btnHeld.addEventListener("click", () => CAD_MODAL.open("/modals/held"));
}

// ---------------------------------------------------------------------------
// Held count watcher
// ---------------------------------------------------------------------------
async function _fetchHeldCount() {
  try {
    const res = await fetch("/api/held_count", { headers: { "Accept": "application/json" } });
    const data = await res.json();
    return Number(data?.count || 0);
  } catch (e) {
    return null;
  }
}

function _applyHeldCount(count) {
  const badge = document.getElementById("held-count-badge");
  const drawerPill = document.getElementById("drawer-held-pill");
  const btnHeld = document.getElementById("btn-held-calls");

  if (badge) badge.textContent = count > 0 ? String(count) : "";

  const alertOn = count > 0;
  if (btnHeld) btnHeld.classList.toggle("cad-held-alert", alertOn);
  if (drawerPill) drawerPill.classList.toggle("cad-held-alert", alertOn);
}

function _startHeldWatcher() {
  const tick = async () => {
    const count = await _fetchHeldCount();
    if (count === null) return;
    _applyHeldCount(count);
  };

  tick();
  setInterval(tick, 6000);
}

// ---------------------------------------------------------------------------
// Phase-3 Session (Login = shift context initializer)
// ---------------------------------------------------------------------------
let CAD_SESSION = {
  logged_in: false,
  shift_letter: "",
  shift_effective: "",
  user: "",
  dispatcher_unit: "",
  roster_view_mode: "CURRENT",
};

async function _postJSON(url, payload) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  const j = await r.json().catch(() => ({}));
  return { ok: r.ok, data: j };
}

function _applySessionToHeader() {
  const headerLine = document.getElementById("header-userline");
  const drawerName = document.getElementById("drawer-name") || document.querySelector(".drawer-name");

  if (!CAD_SESSION.logged_in) {
    if (headerLine) headerLine.textContent = "LOGIN REQUIRED";
    if (drawerName) drawerName.textContent = "LOGIN REQUIRED";
    return;
  }

  const who = (CAD_SESSION.dispatcher_unit || CAD_SESSION.user || "Dispatcher");
  const label = `${CAD_SESSION.shift_letter} Shift – ${who} – ${CAD_SESSION.user || who}`;

  if (headerLine) headerLine.textContent = label;
  if (drawerName) drawerName.textContent = who;
}

async function _refreshSessionStatus() {
  const r = await fetch("/api/session/status", { headers: { "Accept": "application/json" } });
  const j = await r.json().catch(() => ({}));

  CAD_SESSION = {
    logged_in: !!j.logged_in,
    shift_letter: j.shift_letter || "",
    shift_effective: j.shift_effective || "",
    user: j.user || "",
    dispatcher_unit: j.dispatcher_unit || "",
    roster_view_mode: j.roster_view_mode || "CURRENT",
  };

  _applySessionToHeader();
  return CAD_SESSION;
}

function _openLogin() {
  CAD_MODAL.open("/modals/login");
}

function _wireSessionButtons() {
  const btnLogin =
    document.getElementById("btn-login") ||
    document.querySelector(".login-btn");

  const btnLogout =
    document.getElementById("btn-logout") ||
    document.querySelector(".logout-btn");

  if (btnLogin) {
    btnLogin.addEventListener("click", (e) => {
      e.preventDefault();
      _openLogin();
    });
  }

  // Logout is handled by inline onclick in the HTML template
  // No additional JavaScript listener needed
}

// Expose modal submit handler (login modal calls this)
LAYOUT.loginFromModal = async function () {
  const du = document.getElementById("login-dispatcher-unit");
  const sh = document.getElementById("login-shift-letter");
  if (!du || !sh) return;

  const dispatcher_unit = (du.value || "").trim();
  const shift_letter = (sh.value || "").trim().toUpperCase();
  if (!dispatcher_unit || !shift_letter) return;

  const res = await _postJSON("/api/session/login", {
    dispatcher_unit,
    user: dispatcher_unit,
    shift_letter,
  });

  if (!res.ok || !res.data || !res.data.ok) return;

  await _refreshSessionStatus();

  CAD_MODAL.close();
  CAD_UTIL.refreshPanels();
};

// Roster view mode toggle (visibility/filter mode only)
LAYOUT.setRosterViewMode = async function (mode) {
  const view_mode = String(mode || "").trim().toUpperCase();
  if (view_mode !== "CURRENT" && view_mode !== "ALL") return;

  await _postJSON("/api/session/view_mode", { roster_view_mode: view_mode });
  await _refreshSessionStatus();

  CAD_UTIL.refreshPanels();
};

// ---------------------------------------------------------------------------
// Global Keyboard Shortcuts
// ---------------------------------------------------------------------------
function _wireGlobalShortcuts() {
  document.addEventListener("keydown", (e) => {
    // Skip if user is typing in an input/textarea/select (unless Alt is pressed)
    const tag = document.activeElement?.tagName?.toLowerCase();
    const isTyping = tag === "input" || tag === "textarea" || tag === "select";

    // Handle ALT shortcuts (OSSI/Sungard CAD style) - work even in input fields
    if (e.altKey && !e.ctrlKey && !e.metaKey) {
      const key = e.key.toLowerCase();

      switch (key) {
        case "n":
          // Alt+N = New Incident
          e.preventDefault();
          window.CALLTAKER?.startNewIncident?.();
          break;

        case "k":
          // Alt+K = Add Remark to current incident
          e.preventDefault();
          const incK = IAW?.getCurrentIncidentId?.();
          if (incK) {
            CAD_MODAL.open(`/incident/${encodeURIComponent(incK)}/remark`);
          } else {
            window.TOAST?.warning?.("Select an incident first") || alert("Select an incident first");
          }
          break;

        case "d":
          // Alt+D = Dispatch (focus command line with DSP prefix)
          e.preventDefault();
          const cmdD = document.getElementById("cmdline-input") || document.querySelector(".cmdline-input");
          if (cmdD) {
            cmdD.focus();
            cmdD.value = "DSP ";
            cmdD.setSelectionRange(4, 4);
          }
          break;

        case "e":
          // Alt+E = Enroute (focus command line with ENR prefix)
          e.preventDefault();
          const cmdE = document.getElementById("cmdline-input") || document.querySelector(".cmdline-input");
          if (cmdE) {
            cmdE.focus();
            cmdE.value = "ENR ";
            cmdE.setSelectionRange(4, 4);
          }
          break;

        case "a":
          // Alt+A = Arrived (focus command line with ARV prefix)
          e.preventDefault();
          const cmdA = document.getElementById("cmdline-input") || document.querySelector(".cmdline-input");
          if (cmdA) {
            cmdA.focus();
            cmdA.value = "ARV ";
            cmdA.setSelectionRange(4, 4);
          }
          break;

        case "c":
          // Alt+C = Clear unit (focus command line with CLR prefix)
          e.preventDefault();
          const cmdC = document.getElementById("cmdline-input") || document.querySelector(".cmdline-input");
          if (cmdC) {
            cmdC.focus();
            cmdC.value = "CLR ";
            cmdC.setSelectionRange(4, 4);
          }
          break;

        case "h":
          // Alt+H = Held calls
          e.preventDefault();
          CAD_MODAL.open("/modals/held");
          break;

        case "l":
          // Alt+L = Daily Log
          e.preventDefault();
          CAD_MODAL.open("/modals/dailylog");
          break;

        case "r":
          // Alt+R = Send Report
          e.preventDefault();
          if (window.ReportConfirm && window.ReportConfirm.triggerManualReport) {
            window.ReportConfirm.triggerManualReport();
          }
          break;

        case "i":
          // Alt+I = Open incident in IAW (focus command line with INC prefix)
          e.preventDefault();
          const cmdI = document.getElementById("cmdline-input") || document.querySelector(".cmdline-input");
          if (cmdI) {
            cmdI.focus();
            cmdI.value = "INC ";
            cmdI.setSelectionRange(4, 4);
          }
          break;

        case "u":
          // Alt+U = Units panel
          e.preventDefault();
          document.getElementById("panel-units")?.scrollIntoView({ behavior: "smooth" });
          break;

        case "s":
          // Alt+S = Search / History
          e.preventDefault();
          CAD_MODAL.open("/modals/history");
          break;

        case "t":
          // Alt+T = Transport (focus command line with TRP prefix)
          e.preventDefault();
          const cmdT = document.getElementById("cmdline-input") || document.querySelector(".cmdline-input");
          if (cmdT) {
            cmdT.focus();
            cmdT.value = "TRP ";
            cmdT.setSelectionRange(4, 4);
          }
          break;

        case "o":
          // Alt+O = On Scene (same as Arrived)
          e.preventDefault();
          const cmdO = document.getElementById("cmdline-input") || document.querySelector(".cmdline-input");
          if (cmdO) {
            cmdO.focus();
            cmdO.value = "ARV ";
            cmdO.setSelectionRange(4, 4);
          }
          break;

        case "b":
          // Alt+B = Back in service (same as Clear)
          e.preventDefault();
          const cmdB = document.getElementById("cmdline-input") || document.querySelector(".cmdline-input");
          if (cmdB) {
            cmdB.focus();
            cmdB.value = "CLR ";
            cmdB.setSelectionRange(4, 4);
          }
          break;

        case "f":
          // Alt+F = Focus command line
          e.preventDefault();
          const cmdF = document.getElementById("cmdline-input") || document.querySelector(".cmdline-input");
          if (cmdF) {
            cmdF.focus();
            cmdF.select();
          }
          break;

        default:
          // Unknown Alt combo - don't prevent default
          break;
      }
      return; // Don't process further if Alt was pressed
    }

    // Skip non-Alt shortcuts if typing in input fields
    if (isTyping) return;

    // Non-Alt shortcuts (function keys, etc.)
    switch (e.key) {
      case "F1":
        // F1 = Keyboard shortcuts help
        e.preventDefault();
        CAD_MODAL.open("/modals/keyboard_help");
        break;

      case "F2":
        // F2 = New Incident
        e.preventDefault();
        window.CALLTAKER?.startNewIncident?.();
        break;

      case "F5":
        // F5 = Refresh panels (prevent browser refresh)
        e.preventDefault();
        CAD_UTIL.refreshPanels();
        break;

      case "F9":
        // F9 = Daily Log
        e.preventDefault();
        CAD_MODAL.open("/modals/dailylog");
        break;

      case "Escape":
        // ESC = Close modal (if open)
        if (CAD_MODAL.isOpen?.()) {
          e.preventDefault();
          CAD_MODAL.close();
        }
        break;

      case "h":
        // H = Held calls (when no modifier)
        e.preventDefault();
        CAD_MODAL.open("/modals/held");
        break;

      default:
        break;
    }
  });

}

// ---------------------------------------------------------------------------
// Public init
// ---------------------------------------------------------------------------
LAYOUT.init = async () => {
  _wireDrawer();
  _wireToolbar();
  _wireSessionButtons();
  _wireGlobalShortcuts();
  _startHeldWatcher();
  await _refreshSessionStatus();
};

// Global exposure (debug + templates may refer to LAYOUT)
window.LAYOUT = LAYOUT;
