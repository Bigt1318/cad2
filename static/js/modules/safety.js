/**
 * FORD-CAD Safety Inspection Module
 * Handles initialization and command-line integration for safety inspections.
 */
(function () {
  "use strict";

  // Register command-line shortcut
  if (window.COMMANDLINE) {
    const existing = COMMANDLINE._commands || [];
    // Check if already registered
    if (!existing.find(c => c.key === "SAFETY")) {
      existing.push({
        key: "SAFETY",
        aliases: ["INSPECT", "SAFEINSP"],
        desc: "Open Safety Inspections",
        handler: () => {
          if (window.CAD_MODAL) CAD_MODAL.open("/modals/safety");
        }
      });
    }
  }

  console.log("[Safety] Module loaded");
})();
