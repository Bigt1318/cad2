# ============================================================================
# FORD CAD - Multi-Format Report Renderer
# ============================================================================
# Renders report data (Python dicts with rows, stats, metadata) into multiple
# output formats: PDF, CSV, XLSX, HTML, TXT.
#
# Artifacts are saved to artifacts/reports/{run_id}/ via ensure_artifact_dir().
# ============================================================================

import csv
import io
import logging
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
from html import escape as html_escape
from zoneinfo import ZoneInfo

from .models import ensure_artifact_dir, ARTIFACT_DIR

logger = logging.getLogger("reporting.renderer")

EASTERN = ZoneInfo("America/New_York")

# ---------------------------------------------------------------------------
# Shared CSS & HTML fragments  (inline for self-contained output)
# ---------------------------------------------------------------------------

_BRAND_BLUE_DARK = "#1e40af"
_BRAND_BLUE_LIGHT = "#3b82f6"
_BRAND_GREEN = "#16a34a"
_BRAND_RED = "#dc2626"
_BRAND_YELLOW = "#ca8a04"
_GRAY_50 = "#f9fafb"
_GRAY_100 = "#f3f4f6"
_GRAY_200 = "#e5e7eb"
_GRAY_500 = "#6b7280"
_GRAY_700 = "#374151"

_BASE_CSS = f"""
    * {{ box-sizing: border-box; }}
    body {{
        font-family: Arial, Helvetica, sans-serif;
        margin: 0;
        padding: 0;
        background: {_GRAY_50};
        color: #111827;
        font-size: 13px;
        line-height: 1.5;
    }}
    .page-wrap {{
        max-width: 960px;
        margin: 0 auto;
        padding: 20px;
    }}
    .card {{
        background: #fff;
        border-radius: 12px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        overflow: hidden;
        margin-bottom: 24px;
    }}
    .header {{
        background: linear-gradient(135deg, {_BRAND_BLUE_DARK}, {_BRAND_BLUE_LIGHT});
        color: #fff;
        padding: 24px 28px;
    }}
    .header h1 {{ margin: 0; font-size: 22px; }}
    .header .subtitle {{ margin: 4px 0 0; opacity: 0.9; font-size: 15px; }}
    .body {{ padding: 24px 28px; }}
    .filter-bar {{
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        margin-bottom: 20px;
    }}
    .filter-chip {{
        background: {_GRAY_100};
        padding: 6px 14px;
        border-radius: 6px;
        font-size: 12px;
    }}
    .filter-chip strong {{ color: {_BRAND_BLUE_DARK}; }}
    table {{
        width: 100%;
        border-collapse: collapse;
        margin-bottom: 16px;
        font-size: 12px;
    }}
    th {{
        background: {_BRAND_BLUE_DARK};
        color: #fff;
        padding: 8px 10px;
        text-align: left;
        font-weight: 600;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.3px;
    }}
    td {{
        padding: 7px 10px;
        border-bottom: 1px solid {_GRAY_200};
    }}
    tr:nth-child(even) {{ background: #f8fafc; }}
    tr:hover {{ background: #eff6ff; }}
    .stat-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
        gap: 14px;
        margin-bottom: 24px;
    }}
    .stat-box {{
        border: 1px solid {_GRAY_200};
        border-radius: 8px;
        padding: 14px;
        text-align: center;
    }}
    .stat-box .value {{
        font-size: 26px;
        font-weight: 700;
        color: {_BRAND_BLUE_DARK};
    }}
    .stat-box .label {{
        font-size: 11px;
        color: {_GRAY_500};
        margin-top: 2px;
    }}
    .section-title {{
        color: {_GRAY_700};
        border-bottom: 2px solid {_GRAY_200};
        padding-bottom: 8px;
        margin: 28px 0 14px;
        font-size: 16px;
    }}
    .incident-card {{
        border: 1px solid {_GRAY_200};
        border-radius: 8px;
        padding: 14px;
        margin-bottom: 12px;
    }}
    .incident-card.issue {{ border-left: 4px solid {_BRAND_RED}; background: #fef2f2; }}
    .badge {{
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 10px;
        font-weight: 600;
    }}
    .badge-red {{ background: {_BRAND_RED}; color: #fff; }}
    .badge-green {{ background: #dcfce7; color: {_BRAND_GREEN}; }}
    .badge-yellow {{ background: #fef9c3; color: {_BRAND_YELLOW}; }}
    .badge-gray {{ background: {_GRAY_200}; color: {_GRAY_700}; }}
    .pass {{ color: {_BRAND_GREEN}; font-weight: 700; }}
    .fail {{ color: {_BRAND_RED}; font-weight: 700; }}
    .footer {{
        text-align: center;
        color: {_GRAY_500};
        font-size: 11px;
        padding: 16px 28px;
        border-top: 1px solid {_GRAY_200};
    }}
    @media print {{
        body {{ background: #fff; }}
        .page-wrap {{ padding: 0; max-width: 100%; }}
        .card {{ box-shadow: none; border: 1px solid #ccc; }}
    }}
    @page {{
        size: letter;
        margin: 0.6in 0.5in;
        @bottom-center {{
            content: "Page " counter(page) " of " counter(pages);
            font-size: 9px;
            color: {_GRAY_500};
        }}
        @bottom-right {{
            content: "Generated {{generated_ts}}";
            font-size: 9px;
            color: {_GRAY_500};
        }}
    }}
"""


# ============================================================================
# Helper utilities
# ============================================================================

def _safe(val: Any) -> str:
    """Return a safe, HTML-escaped string representation of a value."""
    if val is None:
        return ""
    return html_escape(str(val))


def _now_eastern() -> datetime:
    """Current time in US/Eastern."""
    return datetime.now(EASTERN)


def _format_ts(dt: Optional[datetime] = None) -> str:
    """Format a datetime for display."""
    if dt is None:
        dt = _now_eastern()
    return dt.strftime("%Y-%m-%d %H:%M:%S %Z")


def _flatten_rows(data: Dict) -> List[Dict]:
    """
    Extract a flat list-of-dicts from various data shapes.

    Tries these keys in order: rows, daily_log, incidents.
    Falls back to creating a single-row dict from the top-level stats.
    """
    for key in ("rows", "daily_log", "incidents"):
        candidate = data.get(key)
        if candidate and isinstance(candidate, list):
            # Normalise list-of-lists into list-of-dicts
            if candidate and isinstance(candidate[0], (list, tuple)):
                headers = data.get("headers", [f"col_{i}" for i in range(len(candidate[0]))])
                return [dict(zip(headers, row)) for row in candidate]
            if candidate and isinstance(candidate[0], dict):
                return candidate
    # Fallback: wrap stats or metadata as a single "row"
    stats = data.get("stats")
    if stats and isinstance(stats, dict):
        return [stats]
    return []


def _dict_keys_union(rows: List[Dict]) -> List[str]:
    """Return an ordered list of all keys present across all row dicts."""
    seen = {}
    for row in rows:
        for k in row.keys():
            if k not in seen:
                seen[k] = True
    return list(seen.keys())


def _humanize_header(key: str) -> str:
    """Turn a snake_case key into a Title Case header."""
    return key.replace("_", " ").title()


# ============================================================================
# ReportRenderer
# ============================================================================

class ReportRenderer:
    """Renders report data into multiple formats (PDF, CSV, XLSX, HTML, TXT)."""

    # ------------------------------------------------------------------
    # Public entry-point
    # ------------------------------------------------------------------

    def render_all(
        self,
        run_id: int,
        template_key: str,
        title: str,
        data: Dict,
        formats: List[str],
        filters: Optional[Dict] = None,
    ) -> Dict[str, str]:
        """
        Render a report to every requested format.

        Parameters
        ----------
        run_id : int
            The report_runs.id value; used to create the artifact directory.
        template_key : str
            Determines the HTML layout (blotter, incident_summary, etc.).
        title : str
            Human-readable title shown in headers.
        data : dict
            Report payload with keys like rows, stats, metadata, incidents,
            daily_log.
        formats : list[str]
            Subset of ["pdf", "csv", "xlsx", "html", "txt"].
        filters : dict, optional
            Active filter parameters to display in the report header.

        Returns
        -------
        dict[str, str]
            Mapping of format name to the absolute path of the rendered file.
        """
        if filters is None:
            filters = {}

        artifact_dir = ensure_artifact_dir(run_id)
        generated_ts = _format_ts()
        results: Dict[str, str] = {}

        # We always need the HTML string (for html + pdf), so generate it once
        html_string: Optional[str] = None
        needs_html = any(f in formats for f in ("html", "pdf"))
        if needs_html:
            try:
                html_string = self.render_html(template_key, title, data, filters)
            except Exception:
                logger.error("HTML render failed:\n%s", traceback.format_exc())
                html_string = self._fallback_html(title, data, filters)

        # --- HTML ---
        if "html" in formats and html_string is not None:
            try:
                out = artifact_dir / f"{template_key}_{run_id}.html"
                out.write_text(html_string, encoding="utf-8")
                results["html"] = str(out.resolve())
                logger.info("HTML artifact saved: %s", out)
            except Exception:
                logger.error("Failed to write HTML artifact:\n%s", traceback.format_exc())

        # --- PDF ---
        if "pdf" in formats and html_string is not None:
            out = artifact_dir / f"{template_key}_{run_id}.pdf"
            ok = self.render_pdf(html_string, out)
            if ok:
                results["pdf"] = str(out.resolve())

        # --- CSV ---
        if "csv" in formats:
            out = artifact_dir / f"{template_key}_{run_id}.csv"
            ok = self.render_csv(data, out)
            if ok:
                results["csv"] = str(out.resolve())

        # --- XLSX ---
        if "xlsx" in formats:
            out = artifact_dir / f"{template_key}_{run_id}.xlsx"
            ok = self.render_xlsx(data, out, title=title)
            if ok:
                results["xlsx"] = str(out.resolve())

        # --- TXT ---
        if "txt" in formats:
            try:
                txt_string = self.render_txt(template_key, title, data, filters)
                out = artifact_dir / f"{template_key}_{run_id}.txt"
                out.write_text(txt_string, encoding="utf-8")
                results["txt"] = str(out.resolve())
                logger.info("TXT artifact saved: %s", out)
            except Exception:
                logger.error("Failed to write TXT artifact:\n%s", traceback.format_exc())

        logger.info(
            "render_all complete for run_id=%s template=%s formats=%s -> %s artifacts",
            run_id, template_key, formats, len(results),
        )
        return results

    # ------------------------------------------------------------------
    # HTML rendering
    # ------------------------------------------------------------------

    def render_html(
        self,
        template_key: str,
        title: str,
        data: Dict,
        filters: Optional[Dict] = None,
    ) -> str:
        """
        Render a self-contained HTML report.

        The layout varies by *template_key*; unrecognised keys fall through
        to a generic data-table layout.
        """
        if filters is None:
            filters = {}

        generated_ts = _format_ts()
        css = _BASE_CSS.replace("{{generated_ts}}", _safe(generated_ts))

        # Dispatch to specialised body builders
        body_builder = {
            "blotter": self._html_body_blotter,
            "incident_summary": self._html_body_incident_summary,
            "unit_response_stats": self._html_body_stats_table,
            "calltaker_stats": self._html_body_stats_table,
            "shift_workload": self._html_body_stats_table,
            "response_compliance": self._html_body_compliance,
        }.get(template_key)

        if body_builder is None:
            # custom:* or unknown -> generic table
            body_builder = self._html_body_generic

        body_html = body_builder(template_key, title, data, filters)

        # Assemble full document
        html = (
            "<!DOCTYPE html>\n"
            "<html lang=\"en\">\n"
            "<head>\n"
            "  <meta charset=\"utf-8\">\n"
            f"  <title>{_safe(title)} - Ford Fire Department</title>\n"
            f"  <style>{css}</style>\n"
            "</head>\n"
            "<body>\n"
            "<div class=\"page-wrap\">\n"
            "  <div class=\"card\">\n"
            f"    {self._html_header(title, data)}\n"
            "    <div class=\"body\">\n"
            f"      {self._html_filter_bar(filters)}\n"
            f"      {body_html}\n"
            "    </div>\n"
            f"    {self._html_footer(generated_ts)}\n"
            "  </div>\n"
            "</div>\n"
            "</body>\n"
            "</html>"
        )
        return html

    # -- HTML fragments ------------------------------------------------

    def _html_header(self, title: str, data: Dict) -> str:
        """Blue gradient banner with department branding."""
        subtitle = ""
        meta = data.get("metadata") or {}
        if meta.get("shift"):
            subtitle += f"Shift {_safe(meta['shift'])}"
        if meta.get("date") or data.get("date"):
            d = meta.get("date") or data.get("date")
            if subtitle:
                subtitle += " &middot; "
            subtitle += _safe(str(d))
        if not subtitle:
            subtitle = _format_ts()

        return (
            "<div class=\"header\">\n"
            "  <h1>Ford Fire Department</h1>\n"
            f"  <div class=\"subtitle\">{_safe(title)}"
            f"{'  &mdash; ' + subtitle if subtitle else ''}</div>\n"
            "</div>\n"
        )

    def _html_filter_bar(self, filters: Dict) -> str:
        """Render a row of filter chips (or empty string if no filters)."""
        if not filters:
            return ""
        chips = []
        for k, v in filters.items():
            if v is None or v == "":
                continue
            chips.append(
                f"<div class=\"filter-chip\"><strong>{_safe(_humanize_header(k))}:</strong> "
                f"{_safe(str(v))}</div>"
            )
        if not chips:
            return ""
        return f"<div class=\"filter-bar\">{''.join(chips)}</div>"

    def _html_footer(self, generated_ts: str) -> str:
        return (
            "<div class=\"footer\">\n"
            f"  Generated: {_safe(generated_ts)} &nbsp;|&nbsp; "
            "FORD CAD Reporting System\n"
            "</div>\n"
        )

    def _html_stat_boxes(self, stats: Dict) -> str:
        """Render a grid of stat boxes from a stats dict."""
        if not stats:
            return ""
        boxes = []
        for k, v in stats.items():
            if isinstance(v, dict):
                continue  # skip nested dicts (e.g. incidents_by_type)
            boxes.append(
                "<div class=\"stat-box\">"
                f"<div class=\"value\">{_safe(str(v))}</div>"
                f"<div class=\"label\">{_safe(_humanize_header(k))}</div>"
                "</div>"
            )
        if not boxes:
            return ""
        return f"<div class=\"stat-grid\">{''.join(boxes)}</div>"

    def _html_data_table(self, rows: List[Dict], highlight_col: Optional[str] = None) -> str:
        """Generic table from list-of-dicts."""
        if not rows:
            return "<p style=\"text-align:center;color:#6b7280;padding:20px;\">No data available.</p>"
        headers = _dict_keys_union(rows)
        ths = "".join(f"<th>{_safe(_humanize_header(h))}</th>" for h in headers)
        trs = []
        for row in rows:
            tds = []
            for h in headers:
                val = row.get(h, "")
                cell = _safe(str(val)) if val is not None else ""
                if highlight_col and h == highlight_col:
                    css_class = ""
                    sv = str(val).lower()
                    if sv in ("pass", "true", "yes", "compliant"):
                        css_class = " class=\"pass\""
                    elif sv in ("fail", "false", "no", "non-compliant"):
                        css_class = " class=\"fail\""
                    tds.append(f"<td{css_class}>{cell}</td>")
                else:
                    tds.append(f"<td>{cell}</td>")
            trs.append(f"<tr>{''.join(tds)}</tr>")
        return f"<table><thead><tr>{ths}</tr></thead><tbody>{''.join(trs)}</tbody></table>"

    # -- Specialised body builders --------------------------------------

    def _html_body_blotter(self, template_key: str, title: str, data: Dict, filters: Dict) -> str:
        """Chronological event list (daily log / blotter)."""
        parts: List[str] = []

        # Stats summary boxes
        stats = data.get("stats") or {}
        parts.append(self._html_stat_boxes(stats))

        # Daily log table
        log_entries = data.get("daily_log") or data.get("rows") or []
        if log_entries:
            parts.append("<h2 class=\"section-title\">Daily Log</h2>")
            # Pick columns that are most useful for blotter view
            display_cols = ["timestamp", "category", "event_type", "unit_id",
                            "details", "created_by", "issue_found"]
            # Filter to columns that actually exist
            available = set()
            for entry in log_entries:
                available.update(entry.keys())
            cols = [c for c in display_cols if c in available]
            # Add any remaining columns
            for entry in log_entries:
                for k in entry.keys():
                    if k not in cols:
                        cols.append(k)

            ths = "".join(f"<th>{_safe(_humanize_header(c))}</th>" for c in cols)
            trs = []
            for entry in log_entries:
                tds = []
                for c in cols:
                    val = entry.get(c, "")
                    cell = _safe(str(val)) if val is not None else ""
                    style = ""
                    if c == "issue_found" and str(val) == "1":
                        style = " style=\"color:#dc2626;font-weight:700;\""
                    tds.append(f"<td{style}>{cell}</td>")
                is_issue = str(entry.get("issue_found", "0")) == "1"
                row_style = " style=\"background:#fef2f2;\"" if is_issue else ""
                trs.append(f"<tr{row_style}>{''.join(tds)}</tr>")
            parts.append(
                f"<table><thead><tr>{ths}</tr></thead><tbody>{''.join(trs)}</tbody></table>"
            )
        else:
            parts.append(
                "<p style=\"text-align:center;color:#6b7280;padding:20px;\">"
                "No daily log entries for this period.</p>"
            )

        return "\n".join(parts)

    def _html_body_incident_summary(self, template_key: str, title: str, data: Dict, filters: Dict) -> str:
        """Incident cards with full details."""
        parts: List[str] = []
        stats = data.get("stats") or {}
        parts.append(self._html_stat_boxes(stats))

        incidents = data.get("incidents") or data.get("rows") or []
        if not incidents:
            parts.append(
                "<p style=\"text-align:center;color:#6b7280;padding:20px;\">"
                "No incidents for this period.</p>"
            )
            return "\n".join(parts)

        parts.append(f"<h2 class=\"section-title\">Incidents ({len(incidents)})</h2>")

        for inc in incidents:
            is_issue = inc.get("issue_found") in (1, "1", True)
            card_cls = "incident-card issue" if is_issue else "incident-card"
            issue_badge = (" <span class=\"badge badge-red\">ISSUE</span>" if is_issue else "")

            inc_id = inc.get("incident_number") or inc.get("incident_id") or ""
            status = inc.get("status", "")
            status_cls = "badge-green" if status == "CLOSED" else (
                "badge-yellow" if status in ("ACTIVE", "OPEN", "IN_PROGRESS") else "badge-gray"
            )

            detail_rows = ""
            for field in ("type", "location", "caller_name", "narrative",
                          "priority", "final_disposition", "created", "updated", "closed_at"):
                val = inc.get(field)
                if val:
                    detail_rows += (
                        f"<tr><td style=\"width:130px;color:{_GRAY_500};\">"
                        f"{_safe(_humanize_header(field))}:</td>"
                        f"<td>{_safe(str(val))}</td></tr>"
                    )

            # Unit assignments
            units = inc.get("units") or []
            units_html = ""
            if units:
                u_ths = ""
                u_cols = ["unit_id", "dispatched", "enroute", "arrived",
                          "cleared", "disposition"]
                available_u = set()
                for u in units:
                    available_u.update(u.keys())
                u_cols = [c for c in u_cols if c in available_u]
                u_ths = "".join(f"<th>{_safe(_humanize_header(c))}</th>" for c in u_cols)
                u_trs = []
                for u in units:
                    u_tds = "".join(f"<td>{_safe(str(u.get(c, '')))}</td>" for c in u_cols)
                    u_trs.append(f"<tr>{u_tds}</tr>")
                units_html = (
                    f"<div style=\"margin-top:10px;\"><strong>Units:</strong>"
                    f"<table><thead><tr>{u_ths}</tr></thead>"
                    f"<tbody>{''.join(u_trs)}</tbody></table></div>"
                )

            parts.append(
                f"<div class=\"{card_cls}\">"
                f"  <div style=\"display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;\">"
                f"    <strong style=\"color:{_BRAND_BLUE_DARK};font-size:14px;\">"
                f"#{_safe(str(inc_id))}{issue_badge}</strong>"
                f"    <span class=\"badge {status_cls}\">{_safe(status)}</span>"
                f"  </div>"
                f"  <table style=\"font-size:12px;\">{detail_rows}</table>"
                f"  {units_html}"
                f"</div>"
            )

        return "\n".join(parts)

    def _html_body_stats_table(self, template_key: str, title: str, data: Dict, filters: Dict) -> str:
        """Generic stats table layout used for unit_response_stats, calltaker_stats, shift_workload."""
        parts: List[str] = []
        stats = data.get("stats") or {}
        parts.append(self._html_stat_boxes(stats))

        rows = _flatten_rows(data)
        if rows:
            parts.append(f"<h2 class=\"section-title\">Details</h2>")
            parts.append(self._html_data_table(rows))
        else:
            parts.append(
                "<p style=\"text-align:center;color:#6b7280;padding:20px;\">"
                "No detail rows available.</p>"
            )
        return "\n".join(parts)

    def _html_body_compliance(self, template_key: str, title: str, data: Dict, filters: Dict) -> str:
        """Pass/fail compliance table with colour coding."""
        parts: List[str] = []
        stats = data.get("stats") or {}
        parts.append(self._html_stat_boxes(stats))

        rows = _flatten_rows(data)
        if rows:
            # Try to detect the pass/fail column
            compliance_col = None
            for candidate in ("compliance", "result", "pass_fail", "status", "compliant"):
                if any(candidate in r for r in rows):
                    compliance_col = candidate
                    break
            parts.append(f"<h2 class=\"section-title\">Compliance Detail</h2>")
            parts.append(self._html_data_table(rows, highlight_col=compliance_col))
        else:
            parts.append(
                "<p style=\"text-align:center;color:#6b7280;padding:20px;\">"
                "No compliance data available.</p>"
            )
        return "\n".join(parts)

    def _html_body_generic(self, template_key: str, title: str, data: Dict, filters: Dict) -> str:
        """Fallback generic data table for custom:* templates."""
        parts: List[str] = []
        stats = data.get("stats") or {}
        parts.append(self._html_stat_boxes(stats))

        rows = _flatten_rows(data)
        if rows:
            parts.append(self._html_data_table(rows))
        else:
            # Show raw metadata when no rows
            meta = data.get("metadata") or {}
            if meta:
                parts.append("<h2 class=\"section-title\">Metadata</h2>")
                meta_rows = [{"Key": k, "Value": str(v)} for k, v in meta.items()]
                parts.append(self._html_data_table(meta_rows))
            else:
                parts.append(
                    "<p style=\"text-align:center;color:#6b7280;padding:20px;\">"
                    "No data available for this report.</p>"
                )
        return "\n".join(parts)

    def _fallback_html(self, title: str, data: Dict, filters: Dict) -> str:
        """Ultra-minimal fallback HTML when the main renderer errors."""
        generated_ts = _format_ts()
        rows = _flatten_rows(data)
        row_count = len(rows)
        return (
            "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
            f"<title>{_safe(title)}</title></head>"
            f"<body style=\"font-family:Arial,sans-serif;padding:20px;\">"
            f"<h1>Ford Fire Department</h1>"
            f"<h2>{_safe(title)}</h2>"
            f"<p>Rows: {row_count}</p>"
            f"<p>Generated: {_safe(generated_ts)}</p>"
            f"</body></html>"
        )

    # ------------------------------------------------------------------
    # PDF rendering
    # ------------------------------------------------------------------

    def render_pdf(self, html: str, output_path: Path) -> bool:
        """
        Convert an HTML string to PDF via WeasyPrint.

        Returns True on success, False on failure (logged).
        """
        try:
            from weasyprint import HTML as WeasyprintHTML  # type: ignore
        except ImportError:
            logger.error(
                "WeasyPrint is not installed. Install with: pip install weasyprint  "
                "PDF rendering skipped for %s", output_path,
            )
            return False

        try:
            WeasyprintHTML(string=html).write_pdf(str(output_path))
            logger.info("PDF artifact saved: %s", output_path)
            return True
        except Exception:
            logger.error("PDF render failed for %s:\n%s", output_path, traceback.format_exc())
            return False

    # ------------------------------------------------------------------
    # CSV rendering
    # ------------------------------------------------------------------

    def render_csv(self, data: Dict, output_path: Path) -> bool:
        """
        Write report data rows to a CSV file.

        Handles list-of-dicts and list-of-lists (with optional ``headers``
        key in *data*).
        """
        try:
            rows = _flatten_rows(data)
            if not rows:
                logger.warning("CSV render: no rows to write for %s", output_path)
                # Write an empty CSV with a note
                output_path.write_text("No data available\n", encoding="utf-8")
                return True

            headers = _dict_keys_union(rows)

            with open(str(output_path), "w", newline="", encoding="utf-8") as fp:
                writer = csv.DictWriter(fp, fieldnames=headers, extrasaction="ignore")
                writer.writeheader()
                for row in rows:
                    # Ensure every value is a simple type
                    clean = {}
                    for h in headers:
                        v = row.get(h, "")
                        if isinstance(v, (dict, list)):
                            v = str(v)
                        clean[h] = v
                    writer.writerow(clean)

            logger.info("CSV artifact saved: %s (%d rows)", output_path, len(rows))
            return True

        except Exception:
            logger.error("CSV render failed for %s:\n%s", output_path, traceback.format_exc())
            return False

    # ------------------------------------------------------------------
    # XLSX rendering
    # ------------------------------------------------------------------

    def render_xlsx(self, data: Dict, output_path: Path, title: str = "Report") -> bool:
        """
        Render data to an XLSX workbook using openpyxl.

        Features:
        - Title row
        - Filter summary rows
        - Styled header row (bold, blue background)
        - Auto-width columns
        """
        try:
            from openpyxl import Workbook  # type: ignore
            from openpyxl.styles import Font, PatternFill, Alignment  # type: ignore
        except ImportError:
            logger.error(
                "openpyxl is not installed. Install with: pip install openpyxl  "
                "XLSX rendering skipped for %s", output_path,
            )
            return False

        try:
            wb = Workbook()
            ws = wb.active
            ws.title = title[:31]  # Excel limits sheet name to 31 chars

            header_font = Font(bold=True, color="FFFFFF", size=11)
            header_fill = PatternFill(start_color="1E40AF", end_color="1E40AF", fill_type="solid")
            title_font = Font(bold=True, size=14, color="1E40AF")

            current_row = 1

            # -- Title --
            ws.cell(row=current_row, column=1, value=f"Ford Fire Department - {title}")
            ws.cell(row=current_row, column=1).font = title_font
            current_row += 1

            # -- Generated timestamp --
            ws.cell(row=current_row, column=1, value=f"Generated: {_format_ts()}")
            ws.cell(row=current_row, column=1).font = Font(italic=True, color="6B7280")
            current_row += 1

            # -- Filter summary --
            filters = data.get("metadata") or {}
            if filters:
                for k, v in filters.items():
                    if v is None or v == "":
                        continue
                    ws.cell(row=current_row, column=1, value=_humanize_header(str(k)))
                    ws.cell(row=current_row, column=1).font = Font(bold=True)
                    ws.cell(row=current_row, column=2, value=str(v))
                    current_row += 1

            current_row += 1  # blank row separator

            # -- Data rows --
            rows = _flatten_rows(data)
            if rows:
                headers = _dict_keys_union(rows)

                # Header row
                for col_idx, h in enumerate(headers, 1):
                    cell = ws.cell(row=current_row, column=col_idx, value=_humanize_header(h))
                    cell.font = header_font
                    cell.fill = header_fill
                    cell.alignment = Alignment(horizontal="center")
                current_row += 1

                # Data rows
                for row_data in rows:
                    for col_idx, h in enumerate(headers, 1):
                        val = row_data.get(h, "")
                        if isinstance(val, (dict, list)):
                            val = str(val)
                        ws.cell(row=current_row, column=col_idx, value=val)
                    current_row += 1

                # Auto-width columns
                for col_idx, h in enumerate(headers, 1):
                    max_len = len(_humanize_header(h))
                    for row_data in rows[:200]:  # sample first 200 rows
                        val = str(row_data.get(h, ""))
                        if len(val) > max_len:
                            max_len = len(val)
                    ws.column_dimensions[
                        ws.cell(row=1, column=col_idx).column_letter
                    ].width = min(max_len + 4, 60)
            else:
                ws.cell(row=current_row, column=1, value="No data available")
                current_row += 1

            # -- Stats sheet (if stats present) --
            stats = data.get("stats")
            if stats and isinstance(stats, dict):
                ws_stats = wb.create_sheet(title="Summary Stats")
                ws_stats.cell(row=1, column=1, value="Metric").font = header_font
                ws_stats.cell(row=1, column=1).fill = header_fill
                ws_stats.cell(row=1, column=2, value="Value").font = header_font
                ws_stats.cell(row=1, column=2).fill = header_fill
                r = 2
                for k, v in stats.items():
                    if isinstance(v, dict):
                        # Expand nested dicts (e.g. incidents_by_type)
                        for sub_k, sub_v in v.items():
                            ws_stats.cell(row=r, column=1, value=f"{_humanize_header(k)}: {sub_k}")
                            ws_stats.cell(row=r, column=2, value=sub_v)
                            r += 1
                    else:
                        ws_stats.cell(row=r, column=1, value=_humanize_header(k))
                        ws_stats.cell(row=r, column=2, value=v)
                        r += 1
                ws_stats.column_dimensions["A"].width = 35
                ws_stats.column_dimensions["B"].width = 20

            wb.save(str(output_path))
            logger.info("XLSX artifact saved: %s (%d rows)", output_path, len(rows))
            return True

        except Exception:
            logger.error("XLSX render failed for %s:\n%s", output_path, traceback.format_exc())
            return False

    # ------------------------------------------------------------------
    # TXT rendering (for SMS / Signal / console)
    # ------------------------------------------------------------------

    def render_txt(
        self,
        template_key: str,
        title: str,
        data: Dict,
        filters: Optional[Dict] = None,
    ) -> str:
        """
        Render a concise plain-text summary suitable for SMS, Signal,
        or terminal output.

        Returns the text string (caller writes to file if needed).
        """
        if filters is None:
            filters = {}

        lines: List[str] = []
        sep = "=" * 60

        lines.append(sep)
        lines.append(f"FORD CAD - {title}")
        lines.append(sep)

        # Date range / filters
        meta = data.get("metadata") or {}
        date_range = filters.get("date_range") or meta.get("date") or data.get("date") or ""
        if date_range:
            lines.append(f"Date: {date_range}")
        shift = filters.get("shift") or meta.get("shift") or data.get("shift")
        if shift:
            lines.append(f"Shift: {shift}")

        for k, v in filters.items():
            if k in ("date_range", "shift") or v is None or v == "":
                continue
            lines.append(f"{_humanize_header(k)}: {v}")

        lines.append("")

        # Stats summary
        stats = data.get("stats") or {}
        if stats:
            lines.append("-" * 40)
            lines.append("SUMMARY")
            lines.append("-" * 40)
            for k, v in stats.items():
                if isinstance(v, dict):
                    lines.append(f"  {_humanize_header(k)}:")
                    for sub_k, sub_v in v.items():
                        lines.append(f"    {sub_k}: {sub_v}")
                else:
                    label = _humanize_header(k)
                    lines.append(f"  {label:.<30} {v}")
            lines.append("")

        # Top rows (template-dependent count)
        max_rows_map = {
            "blotter": 20,
            "incident_summary": 10,
            "unit_response_stats": 15,
            "calltaker_stats": 15,
            "shift_workload": 10,
            "response_compliance": 20,
        }
        max_rows = max_rows_map.get(template_key, 10)

        rows = _flatten_rows(data)
        if rows:
            lines.append("-" * 40)

            if template_key == "blotter":
                lines.append(f"DAILY LOG (showing {min(len(rows), max_rows)} of {len(rows)})")
                lines.append("-" * 40)
                for entry in rows[:max_rows]:
                    ts = entry.get("timestamp", "")
                    cat = entry.get("category") or entry.get("event_type", "")
                    unit = entry.get("unit_id", "")
                    details = entry.get("details", "")
                    issue = " [ISSUE]" if str(entry.get("issue_found", "0")) == "1" else ""
                    lines.append(f"  {ts}  {cat:<12} {unit:<8} {details[:60]}{issue}")

            elif template_key == "incident_summary":
                lines.append(f"INCIDENTS (showing {min(len(rows), max_rows)} of {len(rows)})")
                lines.append("-" * 40)
                for inc in rows[:max_rows]:
                    inc_id = inc.get("incident_number") or inc.get("incident_id", "?")
                    itype = inc.get("type", "")
                    loc = inc.get("location", "")
                    status = inc.get("status", "")
                    lines.append(f"  #{inc_id}  {itype}  {loc}  [{status}]")

            else:
                lines.append(f"DATA (showing {min(len(rows), max_rows)} of {len(rows)})")
                lines.append("-" * 40)
                headers = _dict_keys_union(rows)
                # Print column headers
                header_line = "  ".join(h[:12].ljust(12) for h in headers[:6])
                lines.append(f"  {header_line}")
                lines.append(f"  {'- ' * 30}")
                for row in rows[:max_rows]:
                    vals = "  ".join(str(row.get(h, ""))[:12].ljust(12) for h in headers[:6])
                    lines.append(f"  {vals}")

            if len(rows) > max_rows:
                lines.append(f"  ... and {len(rows) - max_rows} more rows")
            lines.append("")

        # Totals
        total_rows = len(rows)
        lines.append(f"Total records: {total_rows}")
        lines.append("")
        lines.append(f"Generated: {_format_ts()}")
        lines.append("Full report: [download link]")
        lines.append(sep)

        return "\n".join(lines)
