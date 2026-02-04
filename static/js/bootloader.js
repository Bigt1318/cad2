// FILE: static/js/bootloader.js
// ============================================================================
// FORD CAD — BOOTLOADER (Phase-3 Canonical)
// Loads modules.json, imports modules in order, then initializes core systems.
// ============================================================================

const DEBUG = false;  // Set to true to enable boot logging

(async function boot() {
    if (DEBUG) console.log("[BOOT] Ford CAD boot starting…");

    // Cache-buster: prevents stale ES module cache after updates.
    // One nonce per page load so all modules share the same version key.
    const BUILD_NONCE = (window.__CAD_BUILD_NONCE__ = window.__CAD_BUILD_NONCE__ || Date.now());

    const modListUrl = "/static/js/modules/modules.json";

    const modules = {};
    const loaded = [];

    const keyFromPath = (p) => {
        try {
            const file = String(p).split("/").pop() || "";
            return file.replace(".js", "");
        } catch {
            return String(p);
        }
    };

    // IMPORTANT:
    // Do NOT append ?v=... to module URLs.
    // Many modules import each other via "./modal.js" etc.
    // If bootloader imports "/modal.js?v=123" you get TWO module instances:
    //   - modal.js?v=123
    //   - modal.js
    // That causes duplicated listeners + modal state desync + "fixes on click" bugs.
    const importOne = async (path) => {
        const url = String(path);
        if (DEBUG) console.log("[BOOT] Importing", url);
        const mod = await import(url);
        const key = keyFromPath(path);
        modules[key] = mod;
        loaded.push(key);
        if (DEBUG) console.log("[BOOT] Loaded module:", key);
        return mod;
    };


    try {
        const res = await fetch(modListUrl, { cache: "no-store", credentials: "same-origin" });
        if (!res.ok) throw new Error(`modules.json fetch failed (${res.status})`);
        const list = await res.json();

        if (DEBUG) console.log("[BOOT] modules.json loaded:", Array.isArray(list) ? `Array(${list.length})` : list);

        for (const path of (list || [])) {
            await importOne(path);
        }

        // Expose module map for debugging
        window.CAD = window.CAD || {};
        window.CAD.modules = modules;

        // ----------------------------
        // 1) Modal Engine
        // ----------------------------
        try {
            const modalMod = modules.modal;
            const modal = modalMod?.CAD_MODAL || modalMod?.default || window.CAD_MODAL;
            if (modal?.init) {
                modal.init();
                if (DEBUG) console.log("[BOOT] Modal engine initialized.");
            } else {
                console.warn("[BOOT] modal.js loaded but CAD_MODAL.init() not found.");
            }
        } catch (e) {
            console.error("[BOOT] Modal init failed:", e);
        }

        // ----------------------------
        // 1b) Context Menu System
        // ----------------------------
        try {
            const ctxMod = modules.contextmenu;
            const ctx = ctxMod?.CAD_CONTEXTMENU || ctxMod?.default || window.CAD_CONTEXTMENU;
            if (ctx?.init) {
                ctx.init();
                if (DEBUG) console.log("[BOOT] Context menu initialized.");
            }
        } catch (e) {
            console.error("[BOOT] Context menu init failed:", e);
        }

        // ----------------------------
        // 2) Panels (helpers + refresh)
        // ----------------------------
        try {
            const panelsMod = modules.panels;
            const panels = panelsMod?.default || panelsMod?.PANELS || window.PANELS;
            if (panels?.init) {
                panels.init();
                if (DEBUG) console.log("[BOOT] Panels initialized.");
            } else {
                console.warn("[BOOT] panels.js loaded but PANELS.init() not found.");
            }
        } catch (e) {
            console.error("[BOOT] Panels init failed:", e);
        }

        // ----------------------------
        // 3) Calltaker (toolbar depends on this)
        // ----------------------------
        try {
            const ctMod = modules.calltaker;
            const ct = ctMod?.default || ctMod?.CALLTAKER || window.CALLTAKER;
            if (ct?.init) {
                ct.init();
                if (DEBUG) console.log("[BOOT] Calltaker initialized.");
            } else {
                console.warn("[BOOT] calltaker.js loaded but CALLTAKER.init() not found.");
            }
        } catch (e) {
            console.error("[BOOT] Calltaker init failed:", e);
        }

        // ----------------------------
        // 4) Layout (Toolbar + Drawer + Held Watcher)
        // ----------------------------
        try {
            const layoutMod = modules.layout;
            const layout = layoutMod?.LAYOUT || layoutMod?.default || window.LAYOUT;

            if (layout?.init) {
                layout.init();
                if (DEBUG) console.log("[BOOT] Layout initialized.");
            } else {
                console.warn("[BOOT] layout.js loaded but LAYOUT.init() not found.");
            }
        } catch (e) {
            console.error("[BOOT] Layout init failed:", e);
        }

        // ----------------------------
        // 5) Clock (single owner)
        // ----------------------------
        try {
            const clockMod = modules.clock;
            const clock = clockMod?.CLOCK || clockMod?.default || window.CLOCK;
            if (clock?.start) {
                clock.start();
                if (DEBUG) console.log("[BOOT] Clock started.");
            } else {
                console.warn("[BOOT] clock.js loaded but CLOCK.start() not found.");
            }
        } catch (e) {
            console.error("[BOOT] Clock start failed:", e);
        }

        if (DEBUG) console.log("[BOOT] Ford CAD fully initialized (Phase-3).");

        // ----------------------------
        // 6) Service Worker (PWA support)
        // ----------------------------
        if ('serviceWorker' in navigator) {
            try {
                const reg = await navigator.serviceWorker.register('/static/service-worker.js');
                if (DEBUG) console.log("[BOOT] Service worker registered:", reg.scope);
            } catch (e) {
                console.warn("[BOOT] Service worker registration failed:", e);
            }
        }

    } catch (err) {
        console.error("[BOOT] Fatal boot failure:", err);
    }
})();
