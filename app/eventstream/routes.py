"""
FORD-CAD Event Stream — API Routes & HTMX Partials
"""
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from typing import Optional

from .models import query_events, count_events, get_event_stats, init_eventstream_schema


def register_eventstream_routes(app: FastAPI):
    """Register all event stream endpoints."""

    init_eventstream_schema()

    @app.get("/api/event-stream")
    async def api_event_stream(
        request: Request,
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
        category: Optional[str] = None,
        event_type: Optional[str] = None,
        incident_id: Optional[int] = None,
        unit_id: Optional[str] = None,
        severity: Optional[str] = None,
        since: Optional[str] = None,
        shift: Optional[str] = None,
    ):
        """Paginated, filtered event stream JSON."""
        events = query_events(
            limit=limit, offset=offset,
            category=category, event_type=event_type,
            incident_id=incident_id, unit_id=unit_id,
            severity=severity, since=since, shift=shift,
        )
        total = count_events(
            category=category, event_type=event_type,
            incident_id=incident_id, unit_id=unit_id,
            severity=severity, since=since, shift=shift,
        )
        return {
            "ok": True,
            "events": events,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @app.get("/api/event-stream/stats")
    async def api_event_stream_stats(
        request: Request,
        since: Optional[str] = None,
    ):
        """Event count aggregations by category/type."""
        stats = get_event_stats(since=since)
        return {"ok": True, "stats": stats}

    @app.get("/partials/event-stream/rows", response_class=HTMLResponse)
    async def partials_event_stream_rows(
        request: Request,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        category: Optional[str] = None,
        severity: Optional[str] = None,
        incident_id: Optional[int] = None,
        since: Optional[str] = None,
    ):
        """HTMX row fragment for incremental timeline updates."""
        events = query_events(
            limit=limit, offset=offset,
            category=category, severity=severity,
            incident_id=incident_id, since=since,
        )
        return _render_timeline_rows(events)

    @app.get("/modals/event-stream", response_class=HTMLResponse)
    async def modal_event_stream(request: Request):
        """Full timeline modal HTML."""
        events = query_events(limit=100)
        stats = get_event_stats()
        rows_html = _render_timeline_rows(events)
        return _render_timeline_modal(rows_html, stats)


def _render_timeline_rows(events) -> str:
    """Render event rows as HTML table rows."""
    if not events:
        return '<tr><td colspan="7" style="text-align:center;color:#888;padding:20px;">No events yet</td></tr>'

    severity_colors = {
        "info": "#4a5568",
        "warning": "#d69e2e",
        "alert": "#e53e3e",
        "critical": "#e53e3e",
    }
    category_icons = {
        "incident": "&#x1F6A8;",
        "unit": "&#x1F692;",
        "narrative": "&#x1F4DD;",
        "system": "&#x2699;",
        "dailylog": "&#x1F4CB;",
        "chat": "&#x1F4AC;",
    }

    rows = []
    for ev in events:
        sev = ev.get("severity", "info")
        cat = ev.get("category", "system")
        color = severity_colors.get(sev, "#4a5568")
        icon = category_icons.get(cat, "&#x2022;")
        pulse = ' class="critical-pulse"' if sev == "critical" else ""

        ts = ev.get("timestamp", "")
        time_part = ts[11:19] if len(ts) >= 19 else ts

        inc = ev.get("incident_id") or ""
        uid = ev.get("unit_id") or ""
        summary = ev.get("summary") or ev.get("event_type", "")
        user = ev.get("user") or ""

        rows.append(f"""<tr{pulse} style="border-left:3px solid {color};">
            <td style="padding:4px 8px;font-size:11px;color:#999;">{time_part}</td>
            <td style="padding:4px 6px;font-size:12px;">{icon}</td>
            <td style="padding:4px 8px;font-size:11px;"><span style="background:{color};color:#fff;padding:1px 6px;border-radius:3px;font-size:10px;">{ev.get('event_type','')}</span></td>
            <td style="padding:4px 8px;font-size:11px;">{inc}</td>
            <td style="padding:4px 8px;font-size:11px;">{uid}</td>
            <td style="padding:4px 8px;font-size:11px;">{summary}</td>
            <td style="padding:4px 8px;font-size:11px;color:#888;">{user}</td>
        </tr>""")

    return "\n".join(rows)


def _render_timeline_modal(rows_html: str, stats: dict) -> str:
    """Render the full timeline modal HTML."""
    total = stats.get("total", 0)
    by_cat = stats.get("by_category", {})

    stat_chips = ""
    for cat, cnt in by_cat.items():
        stat_chips += f'<span style="background:#2d3748;color:#e2e8f0;padding:2px 8px;border-radius:10px;font-size:11px;margin:0 3px;">{cat}: {cnt}</span>'

    return f"""
<div style="font-family:'Segoe UI',system-ui,sans-serif;color:#e2e8f0;max-height:80vh;display:flex;flex-direction:column;">
    <!-- Header -->
    <div style="padding:12px 16px;border-bottom:1px solid #2d3748;display:flex;align-items:center;justify-content:space-between;">
        <div>
            <h3 style="margin:0;font-size:16px;color:#63b3ed;">Event Timeline</h3>
            <div style="margin-top:4px;">{stat_chips} <span style="color:#888;font-size:11px;">{total} total</span></div>
        </div>
        <div style="display:flex;gap:6px;" id="es-filter-bar">
            <button class="es-filter-chip es-active" data-category="" onclick="ES_TIMELINE.filterCategory(this,'')">All</button>
            <button class="es-filter-chip" data-category="incident" onclick="ES_TIMELINE.filterCategory(this,'incident')">Incidents</button>
            <button class="es-filter-chip" data-category="unit" onclick="ES_TIMELINE.filterCategory(this,'unit')">Units</button>
            <button class="es-filter-chip" data-category="system" onclick="ES_TIMELINE.filterCategory(this,'system')">System</button>
            <button class="es-filter-chip" data-category="narrative" onclick="ES_TIMELINE.filterCategory(this,'narrative')">Narrative</button>
        </div>
    </div>

    <!-- Timeline Table -->
    <div style="flex:1;overflow-y:auto;padding:0;" id="es-timeline-scroll">
        <table style="width:100%;border-collapse:collapse;" id="es-timeline-table">
            <thead>
                <tr style="background:#1a202c;position:sticky;top:0;z-index:1;">
                    <th style="padding:6px 8px;text-align:left;font-size:11px;color:#a0aec0;width:70px;">Time</th>
                    <th style="padding:6px 6px;width:24px;"></th>
                    <th style="padding:6px 8px;text-align:left;font-size:11px;color:#a0aec0;">Event</th>
                    <th style="padding:6px 8px;text-align:left;font-size:11px;color:#a0aec0;width:60px;">Inc#</th>
                    <th style="padding:6px 8px;text-align:left;font-size:11px;color:#a0aec0;width:60px;">Unit</th>
                    <th style="padding:6px 8px;text-align:left;font-size:11px;color:#a0aec0;">Summary</th>
                    <th style="padding:6px 8px;text-align:left;font-size:11px;color:#a0aec0;width:70px;">User</th>
                </tr>
            </thead>
            <tbody id="es-timeline-body">
                {rows_html}
            </tbody>
        </table>
    </div>

    <style>
        .es-filter-chip {{
            background: #2d3748; color: #a0aec0; border: 1px solid #4a5568;
            padding: 3px 10px; border-radius: 12px; font-size: 11px; cursor: pointer;
        }}
        .es-filter-chip:hover {{ background: #4a5568; }}
        .es-filter-chip.es-active {{ background: #2b6cb0; color: #fff; border-color: #3182ce; }}
        #es-timeline-table tr:hover {{ background: rgba(99,179,237,0.08); }}
        @keyframes critical-blink {{ 0%,100% {{ opacity:1; }} 50% {{ opacity:0.6; }} }}
        .critical-pulse {{ animation: critical-blink 1.5s infinite; }}
    </style>
</div>

<script>
    window.ES_TIMELINE = window.ES_TIMELINE || {{}};
    ES_TIMELINE.filterCategory = function(btn, cat) {{
        document.querySelectorAll('.es-filter-chip').forEach(b => b.classList.remove('es-active'));
        btn.classList.add('es-active');
        const url = cat
            ? '/partials/event-stream/rows?limit=100&category=' + encodeURIComponent(cat)
            : '/partials/event-stream/rows?limit=100';
        fetch(url).then(r => r.text()).then(html => {{
            document.getElementById('es-timeline-body').innerHTML = html;
        }});
    }};
</script>
"""
