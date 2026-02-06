// FILE: static/js/modules/modal.js
// ============================================================================
// FORD CAD — GLOBAL MODAL ENGINE (CANONICAL)
// Phase-3 Stabilized Edition (FIX: SINGLETON + NO DOUBLE-FLASH + NO STUCK OVERLAY)
// ============================================================================
// Key fixes:
//   • Enforces a true singleton even if modal.js is imported twice (querystring mismatch).
//   • Reuses (and de-duplicates) #ford-cad-modal-container instead of creating a second one.
//   • Debounces duplicate open() calls (double-bound click handlers / double events).
//   • Keeps animations simple (no visibility hacks that create “ghost patches”).
//   • Primes Daily Log rows on open (no reliance on hx-trigger="load").
// ============================================================================

import { CAD_UTIL } from "./utils.js";

export const CAD_MODAL = (() => {
  // -------------------------------------------------------------------------
  // SINGLETON GUARD
  // -------------------------------------------------------------------------
  try {
    if (window?.CAD_MODAL && window.CAD_MODAL.__FORDCAD_MODAL_SINGLETON__ === true) {
      return window.CAD_MODAL;
    }
  } catch (_) {}

  // -------------------------------------------------------------------------
  // PRIVATE RUNTIME STATE (closure-scoped)
  // -------------------------------------------------------------------------
  let _container = null;
  let _active = false;
  let _escBound = false;

  // Debounce duplicate opens (double binding / double click)
  let _opening = false;
  let _lastOpenUrl = "";
  let _lastOpenAt = 0;

  // -------------------------------------------------------------------------
  // INTERNAL — ENSURE MODAL ROOT EXISTS (self-healing + de-dup)
  // -------------------------------------------------------------------------
  function _ensureContainer() {
    // If multiple containers exist (duplicate module loads), remove extras
    try {
      const all = Array.from(document.querySelectorAll("#ford-cad-modal-container"));
      if (all.length > 1) {
        all.slice(1).forEach((n) => {
          try {
            n.remove();
          } catch (_) {}
        });
      }
    } catch (_) {}

    // Reuse existing container if it already exists in DOM
    try {
      const existing = document.getElementById("ford-cad-modal-container");
      if (existing) {
        _container = existing;
        return;
      }
    } catch (_) {}

    // If our cached container exists but was detached, reattach
    if (_container && !_container.isConnected) {
      document.body.appendChild(_container);
      return;
    }

    if (_container) return;

    _container = document.createElement("div");
    _container.id = "ford-cad-modal-container";
    document.body.appendChild(_container);
  }

  // -------------------------------------------------------------------------
  // INTERNAL — AUTOFOCUS
  // -------------------------------------------------------------------------
  function _autofocus(modal) {
    if (!modal) return;

    const el =
      modal.querySelector("[data-autofocus='1']") ||
      modal.querySelector("[autofocus]") ||
      modal.querySelector("input:not([type='hidden']):not([disabled])") ||
      modal.querySelector("select:not([disabled])") ||
      modal.querySelector("textarea:not([disabled])") ||
      modal.querySelector("button:not([disabled])");

    if (!el) return;

    setTimeout(() => {
      try {
        el.focus?.();
        el.select?.();
      } catch (_) {}
    }, 0);
  }

  // -------------------------------------------------------------------------
  // INTERNAL — ENTER SUBMIT + ESC CLOSE (scoped to modal)
  // -------------------------------------------------------------------------
  function _bindModalKeys(modal, closeFn) {
    if (!modal) return;

    modal.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        closeFn();
        return;
      }

      if (e.key !== "Enter") return;

      const tag = (e.target?.tagName || "").toUpperCase();
      if (tag === "TEXTAREA" && !e.ctrlKey) return;
      if (tag === "BUTTON") return;

      const form = e.target?.closest?.("form") || modal.querySelector("form");
      if (!form) return;

      const submit =
        form.querySelector("button[type='submit']:not([disabled])") ||
        form.querySelector("input[type='submit']:not([disabled])");

      if (!submit) return;

      e.preventDefault();
      submit.click();
    });
  }

  // -------------------------------------------------------------------------
  // INTERNAL — HTMX PROCESS INJECTED MODAL DOM (once)
  // -------------------------------------------------------------------------
  function _processHtmx(root) {
    if (!root) return;
    if (!window.htmx || typeof window.htmx.process !== "function") return;

    try {
      window.htmx.process(root);
    } catch (e) {
      console.warn("[MODAL] htmx.process failed:", e);
    }
  }

  // -------------------------------------------------------------------------
  // INTERNAL — COLLECT hx-include VALUES (scoped to injected modal DOM)
  // -------------------------------------------------------------------------
  function _collectIncludeValues(root, selector) {
    const out = {};
    if (!root || !selector) return out;

    let nodes = [];
    try {
      nodes = Array.from(root.querySelectorAll(selector));
    } catch (_) {
      nodes = [];
    }

    nodes.forEach((node) => {
      const tag = (node.tagName || "").toUpperCase();

      if (tag === "FORM") {
        try {
          const fd = new FormData(node);
          fd.forEach((v, k) => {
            out[k] = String(v);
          });
        } catch (_) {}
        return;
      }

      try {
        node.querySelectorAll("input,select,textarea").forEach((el) => {
          const name = el.getAttribute("name");
          if (!name) return;

          const type = (el.getAttribute("type") || "").toLowerCase();
          if (type === "checkbox" || type === "radio") {
            if (el.checked) out[name] = String(el.value ?? "on");
            return;
          }

          out[name] = String(el.value ?? "");
        });
      } catch (_) {}
    });

    return out;
  }

  // -------------------------------------------------------------------------
  // INTERNAL — PRIME DAILY LOG TABLE ON MODAL OPEN (NO hx-trigger RELIANCE)
  // Fixes: "Daily Log rows do not load until I click Clear"
  // -------------------------------------------------------------------------
  function _primeDailyLogRows(root) {
    if (!root) return;

    const tbody = root.querySelector("#log-table-body");
    if (!tbody) return;

    if (tbody.dataset.dlPrimed === "1") return;
    tbody.dataset.dlPrimed = "1";

    const hxGet = tbody.getAttribute("hx-get") || tbody.getAttribute("data-hx-get") || "";
    if (!hxGet) return;

    // If rows already exist, do nothing
    const alreadyHasRows =
      tbody.querySelector("tr") !== null || (tbody.innerHTML || "").trim().length > 0;
    if (alreadyHasRows) return;

    const includeSel =
      tbody.getAttribute("hx-include") || tbody.getAttribute("data-hx-include") || "";

    const values = _collectIncludeValues(root, includeSel);
    const qs = new URLSearchParams(values).toString();
    const url = qs ? `${hxGet}?${qs}` : hxGet;

    (async () => {
      try {
        const rowsHtml = await CAD_UTIL.safeFetch(url);
        tbody.innerHTML = rowsHtml;
      } catch (e) {
        console.warn("[MODAL] DailyLog prime failed:", e);
      }
    })();
  }

  // -------------------------------------------------------------------------
  // INTERNAL — STABLE SCROLL LOCK (prevents layout jump)
  // -------------------------------------------------------------------------
  function _lockScrollStable(state) {
    const body = document.body;

    if (state) {
      const sbw = window.innerWidth - document.documentElement.clientWidth;
      if (sbw > 0) body.style.paddingRight = `${sbw}px`;
      body.style.overflow = "hidden";
    } else {
      body.style.overflow = "";
      body.style.paddingRight = "";
    }
  }

  // -------------------------------------------------------------------------
  // MODAL ENGINE OBJECT
  // -------------------------------------------------------------------------
  const api = {
    __FORDCAD_MODAL_SINGLETON__: true,

    get container() {
      return _container;
    },

    get active() {
      return _active;
    },

    init() {
      _ensureContainer();

      if (!_escBound) {
        document.addEventListener("keydown", (e) => {
          if (e.key === "Escape" && _active) {
            api.close();
          }
        });
        _escBound = true;
      }

    },

    async open(url, context = null) {
      // Debounce duplicate opens (double click / double binding)
      const now = Date.now();
      if (_opening && url === _lastOpenUrl && now - _lastOpenAt < 400) return;
      if (_active && url === _lastOpenUrl && now - _lastOpenAt < 400) return;

      _opening = true;
      _lastOpenUrl = url;
      _lastOpenAt = now;

      try {
        api.init();

        // Always hard-clear any existing modal HTML before open
        api._clear(true);
        _active = true;

        // Lock scroll immediately (prevents “snap after click”)
        _lockScrollStable(true);

        // Fetch + inject HTML
        const html = await CAD_UTIL.safeFetch(url);
        _container.innerHTML = html;

        const modal = _container.querySelector(".cad-modal");
        const overlay = _container.querySelector(".cad-modal-overlay");

        if (!modal || !overlay) {
          throw new Error(
            "Modal HTML missing required root elements (.cad-modal / .cad-modal-overlay)."
          );
        }

        // Overlay click closes (safety)
        overlay.addEventListener("click", (e) => {
          e.preventDefault();
          e.stopPropagation();
          api.close();
        });

        // Inject context data as data-* attributes
        if (context && typeof context === "object") {
          Object.entries(context).forEach(([key, value]) => {
            if (value !== undefined && value !== null) {
              modal.dataset[key] = String(value);
            }
          });
        }

        // Ensure focusability
        if (!modal.hasAttribute("tabindex")) modal.tabIndex = -1;

        // Scoped keys
        _bindModalKeys(modal, () => api.close());

        // Single, simple animation application (no double-flash hacks)
        modal.classList.remove("modal-fade-out");
        modal.classList.add("modal-fade-in");

        // HTMX + DailyLog prime after inject
        setTimeout(() => {
          _processHtmx(_container);
          _primeDailyLogRows(_container);

          requestAnimationFrame(() => {
            try {
              modal.focus?.();
            } catch (_) {}
            _autofocus(modal);
          });
        }, 0);
      } catch (err) {
        console.error("[MODAL] Open failed:", err);
        api._clear(true);
      } finally {
        _opening = false;
      }
    },

    close(instant = false) {
      if (!_container) {
        _active = false;
        _lockScrollStable(false);
        return;
      }

      if (!_active) {
        if ((_container.innerHTML || "").trim() !== "") {
          api._clear(true);
        }
        return;
      }

      const modal = _container.querySelector(".cad-modal");

      if (instant || !modal) {
        api._clear(true);
        return;
      }

      modal.classList.remove("modal-fade-in");
      modal.classList.add("modal-fade-out");

      setTimeout(() => api._clear(true), 250);
    },

    _clear(force = false) {
      if (_container) _container.innerHTML = "";
      if (force) {
        _active = false;
        _lockScrollStable(false);
      }
    }
  };

  // Expose for inline onclick handlers
  window.CAD_MODAL = api;


  return api;
})();

export default CAD_MODAL;
