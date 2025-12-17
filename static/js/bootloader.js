// ============================================================================
// BOSK-CAD — BOOTLOADER
// Phase-3 Enterprise Edition
// ============================================================================
// Responsibilities:
//   • Load modules.json
//   • Dynamically import JS modules in correct sequence
//   • Initialize BOSK_MODAL engine
//   • Initialize layout watchers (held badge, clock, etc.)
//   • Expose BOSK namespace to window for debugging
// ============================================================================

(async function () {

    console.log("[BOOT] BOSK-CAD Bootloader starting…");

    // ---------------------------------------------------------------------
    // 1. Load modules.json to determine module load order
    // ---------------------------------------------------------------------
    let moduleList = [];

    try {
        const res = await fetch("/static/js/modules/modules.json");
        moduleList = await res.json();
        console.log("[BOOT] modules.json loaded:", moduleList);
    } catch (err) {
        console.error("[BOOT] Unable to load modules.json", err);
        alert("BOSK-CAD failed to load required modules.");
        return;
    }

    // Global namespace (optional)
    window.BOSK = {};

    // ---------------------------------------------------------------------
    // 2. Import modules IN ORDER
    // ---------------------------------------------------------------------
    try {
        for (const path of moduleList) {
            console.log(`[BOOT] Importing module: ${path}`);
            const module = await import(path);

            // Bind module exports into BOSK namespace by filename key
            const key = path.split("/").pop().replace(".js", "");
            window.BOSK[key] = module.default ?? module;

            console.log(`[BOOT] Loaded: ${key}`);
        }
    } catch (err) {
        console.error("[BOOT] Module import error:", err);
        alert("A required BOSK-CAD module failed to load.");
        return;
    }

    // ---------------------------------------------------------------------
    // 3. Initialize Modal Engine
    // ---------------------------------------------------------------------
    try {
        if (window.BOSK["modal"]) {
            window.BOSK["modal"].init();
        } else if (window.BOSK["modal.js"]) {
            window.BOSK["modal.js"].init();
        } else if (window.BOSK["modal"]?.init) {
            window.BOSK["modal"].init();
        } else {
            console.warn("[BOOT] BOSK_MODAL was not found in namespace.");
        }
    } catch (err) {
        console.error("[BOOT] Failed to initialize Modal Engine:", err);
    }

    // ---------------------------------------------------------------------
    // 4. Initialize Layout Watchers (Held, Clock, etc.)
    //    layout.js will define: startHeldCallWatcher()
    // ---------------------------------------------------------------------
    try {
        if (window.BOSK["layout"]?.startHeldCallWatcher) {
            window.BOSK["layout"].startHeldCallWatcher();
            console.log("[BOOT] Held Call Watcher started.");
        }
    } catch (err) {
        console.error("[BOOT] Failed to start Held Call Watcher:", err);
    }

    // Optional future watchers:
    //   - startClock()
    //   - startAutoRefresh()
    //   - startUnitHeartbeat()

    // ---------------------------------------------------------------------
    // 5. Boot Complete
    // ---------------------------------------------------------------------
    console.log("[BOOT] BOSK-CAD fully initialized (Phase-3).");

})();
