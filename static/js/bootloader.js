// FILE: static/js/bootloader.js
// ============================================================================
// FORD CAD — BOOTLOADER (Phase-3 Canonical)
// Loads modules.json, imports modules in order, then initializes core systems.
// ============================================================================

(async function boot() {
    console.log("[BOOT] Ford CAD boot starting…");

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
        console.log("[BOOT] Importing", url);
        const mod = await import(url);
        const key = keyFromPath(path);
        modules[key] = mod;
        loaded.push(key);
        console.log("[BOOT] Loaded module:", key);
        return mod;
    };


    try {
        const res = await fetch(modListUrl, { cache: "no-store", credentials: "same-origin" });
        if (!res.ok) throw new Error(`modules.json fetch failed (${res.status})`);
        const list = await res.json();

        console.log("[BOOT] modules.json loaded:", Array.isArray(list) ? `Array(${list.length})` : list);

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
                console.log("[BOOT] Modal engine initialized.");
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
                console.log("[BOOT] Context menu initialized.");
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
                console.log("[BOOT] Panels initialized.");
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
                console.log("[BOOT] Calltaker initialized.");
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
                console.log("[BOOT] Layout initialized.");
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
                console.log("[BOOT] Clock started.");
            } else {
                console.warn("[BOOT] clock.js loaded but CLOCK.start() not found.");
            }
        } catch (e) {
            console.error("[BOOT] Clock start failed:", e);
        }

        console.log("[BOOT] Ford CAD fully initialized (Phase-3).");

    } catch (err) {
        console.error("[BOOT] Fatal boot failure:", err);
    }
})();
