// ============================================================================
// FORD CAD — Report Confirm Module
// Handles manual report generation from CLI REPORT command and Alt+R shortcut.
// Calls /api/reporting/run, writes history entry, shows toast confirmation.
// ============================================================================

const ReportConfirm = {

  /**
   * Trigger a manual report run (default: blotter for current shift).
   * Called from CLI "REPORT" command and Alt+R keyboard shortcut.
   */
  async triggerManualReport(templateKey = "blotter") {
    console.log("[REPORT] Manual report triggered:", templateKey);

    if (window.TOAST?.info) {
      window.TOAST.info("Generating report...");
    }

    try {
      const res = await (window.CAD_UTIL?.postJSON || _postJSON)(
        "/api/reporting/run",
        {
          template_key: templateKey,
          title: `Manual ${templateKey} — ${new Date().toLocaleString()}`,
          filters: {},
          formats: ["html"],
        }
      );

      if (res?.ok) {
        console.log("[REPORT] Report generated: run_id=%d, status=%s", res.run_id, res.status);

        // Show success toast with link to view
        const link = res.links?.html;
        if (link && window.TOAST?.success) {
          window.TOAST.success(`Report ready (run #${res.run_id})`);
        } else if (window.TOAST?.success) {
          window.TOAST.success(`Report generated (run #${res.run_id})`);
        }

        // If reporting modal is available, open the history view
        if (link && window.CAD_MODAL?.open) {
          window.CAD_MODAL.open("/modals/reporting");
        }

        return res;
      } else {
        const errMsg = res?.error || "Unknown error";
        console.error("[REPORT] Report generation failed:", errMsg);
        if (window.TOAST?.error) {
          window.TOAST.error(`Report failed: ${errMsg}`);
        }
        return res;
      }
    } catch (err) {
      console.error("[REPORT] Report request failed:", err);
      if (window.TOAST?.error) {
        window.TOAST.error("Report request failed — check console");
      }
      return null;
    }
  },
};

// Simple fallback POST if CAD_UTIL not loaded yet
async function _postJSON(url, data) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  return resp.json();
}

window.ReportConfirm = ReportConfirm;

export default ReportConfirm;
