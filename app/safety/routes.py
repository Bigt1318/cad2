"""
FORD-CAD Safety Inspection — API Routes
"""
import json
import os
import uuid
from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from .models import (
    init_safety_schema,
    get_asset_types, get_asset_type, create_asset_type,
    get_locations, get_location, create_location, update_location, delete_location,
    get_assets, get_asset, get_asset_by_qr, create_asset, update_asset, delete_asset,
    get_templates, get_template,
    get_inspections, get_inspection, create_inspection, get_pending_inspections,
    get_deficiencies, get_deficiency, update_deficiency, get_deficiency_dashboard,
    get_dashboard_stats, get_compliance_report,
    get_schedules, create_schedule, update_schedule, delete_schedule,
)
from .qr import generate_qr_png, generate_batch_zip, generate_print_sheet


UPLOAD_DIR = os.path.join("static", "uploads", "safety")


def register_safety_routes(app: FastAPI):
    """Register all safety inspection endpoints."""

    init_safety_schema()
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    # ============================================================
    # ASSET TYPES
    # ============================================================

    @app.get("/api/safety/types")
    async def api_get_types(request: Request):
        types = get_asset_types()
        return {"ok": True, "types": types}

    @app.post("/api/safety/types")
    async def api_create_type(request: Request):
        data = await request.json()
        tid = create_asset_type(data)
        return {"ok": True, "type_id": tid}

    # ============================================================
    # LOCATIONS
    # ============================================================

    @app.get("/api/safety/locations")
    async def api_get_locations(request: Request):
        building = request.query_params.get("building")
        floor = request.query_params.get("floor")
        locs = get_locations(building=building, floor=floor)
        return {"ok": True, "locations": locs}

    @app.post("/api/safety/locations")
    async def api_create_location(request: Request):
        data = await request.json()
        lid = create_location(data)
        return {"ok": True, "location_id": lid}

    @app.put("/api/safety/locations/{loc_id}")
    async def api_update_location(loc_id: int, request: Request):
        data = await request.json()
        update_location(loc_id, data)
        return {"ok": True}

    @app.delete("/api/safety/locations/{loc_id}")
    async def api_delete_location(loc_id: int, request: Request):
        delete_location(loc_id)
        return {"ok": True}

    # ============================================================
    # ASSETS
    # ============================================================

    @app.get("/api/safety/assets")
    async def api_get_assets(request: Request):
        params = request.query_params
        assets = get_assets(
            asset_type_id=int(params["type"]) if params.get("type") else None,
            location_id=int(params["location"]) if params.get("location") else None,
            status=params.get("status"),
            overdue=params.get("overdue") == "true",
            search=params.get("search"),
        )
        return {"ok": True, "assets": assets}

    @app.get("/api/safety/assets/scan/{qr_code}")
    async def api_scan_qr(qr_code: str, request: Request):
        asset = get_asset_by_qr(qr_code)
        if not asset:
            return JSONResponse({"ok": False, "error": "Asset not found"}, status_code=404)
        # Include available templates
        templates = get_templates(asset_type_id=asset["asset_type_id"])
        return {"ok": True, "asset": asset, "templates": templates}

    @app.get("/api/safety/assets/{asset_id}")
    async def api_get_asset(asset_id: int, request: Request):
        asset = get_asset(asset_id)
        if not asset:
            return JSONResponse({"ok": False, "error": "Not found"}, status_code=404)
        history = get_inspections(asset_id=asset_id, limit=20)
        templates = get_templates(asset_type_id=asset["asset_type_id"])
        deficiencies_list = get_deficiencies(asset_id=asset_id)
        return {"ok": True, "asset": asset, "history": history,
                "templates": templates, "deficiencies": deficiencies_list}

    @app.post("/api/safety/assets")
    async def api_create_asset(request: Request):
        data = await request.json()
        aid = create_asset(data)
        return {"ok": True, "asset_id": aid}

    @app.put("/api/safety/assets/{asset_id}")
    async def api_update_asset(asset_id: int, request: Request):
        data = await request.json()
        update_asset(asset_id, data)
        return {"ok": True}

    @app.delete("/api/safety/assets/{asset_id}")
    async def api_delete_asset(asset_id: int, request: Request):
        delete_asset(asset_id)

        try:
            from app.eventstream.emitter import emit_event
            emit_event("SAFETY_ASSET_RETIRED", summary=f"Asset #{asset_id} retired",
                       category="safety", severity="info")
        except Exception:
            pass

        return {"ok": True}

    @app.get("/api/safety/assets/{asset_id}/qr")
    async def api_get_qr(asset_id: int, request: Request):
        asset = get_asset(asset_id)
        if not asset:
            return JSONResponse({"ok": False, "error": "Not found"}, status_code=404)
        png = generate_qr_png(asset["qr_code"])
        return Response(content=png, media_type="image/png",
                        headers={"Content-Disposition": f'inline; filename="{asset["asset_tag"]}-qr.png"'})

    @app.post("/api/safety/assets/{asset_id}/photo")
    async def api_upload_photo(asset_id: int, file: UploadFile = File(...)):
        ext = os.path.splitext(file.filename)[1] if file.filename else ".jpg"
        fname = f"asset-{asset_id}-{uuid.uuid4().hex[:8]}{ext}"
        fpath = os.path.join(UPLOAD_DIR, fname)
        content = await file.read()
        with open(fpath, "wb") as f:
            f.write(content)
        url = f"/static/uploads/safety/{fname}"
        update_asset(asset_id, {"photo_url": url})
        return {"ok": True, "photo_url": url}

    # ============================================================
    # INSPECTION TEMPLATES
    # ============================================================

    @app.get("/api/safety/templates")
    async def api_get_templates(request: Request):
        type_id = request.query_params.get("asset_type_id")
        templates = get_templates(asset_type_id=int(type_id) if type_id else None)
        return {"ok": True, "templates": templates}

    # ============================================================
    # INSPECTIONS
    # ============================================================

    @app.get("/api/safety/inspections")
    async def api_get_inspections(request: Request):
        params = request.query_params
        inspections = get_inspections(
            asset_id=int(params["asset_id"]) if params.get("asset_id") else None,
            inspector=params.get("inspector"),
            result=params.get("result"),
            date_from=params.get("date_from"),
            date_to=params.get("date_to"),
        )
        return {"ok": True, "inspections": inspections}

    @app.get("/api/safety/inspections/pending")
    async def api_pending_inspections(request: Request):
        days = int(request.query_params.get("days", "7"))
        pending = get_pending_inspections(days_ahead=days)
        return {"ok": True, "pending": pending}

    @app.get("/api/safety/inspections/{insp_id}")
    async def api_get_inspection(insp_id: int, request: Request):
        insp = get_inspection(insp_id)
        if not insp:
            return JSONResponse({"ok": False, "error": "Not found"}, status_code=404)
        return {"ok": True, "inspection": insp}

    @app.post("/api/safety/inspections")
    async def api_submit_inspection(request: Request):
        data = await request.json()
        insp_id = create_inspection(data)

        # Emit events
        try:
            from app.eventstream.emitter import emit_event
            asset = get_asset(data["asset_id"])
            tag = asset["asset_tag"] if asset else f"#{data['asset_id']}"
            result = data.get("result", "pass")
            emit_event(
                "SAFETY_INSPECTION_COMPLETED",
                summary=f"Inspection completed: {tag} — {result}",
                user=data.get("inspector_name"),
                category="safety",
                severity="info" if result == "pass" else "warning",
            )
        except Exception:
            pass

        return {"ok": True, "inspection_id": insp_id}

    # ============================================================
    # DEFICIENCIES
    # ============================================================

    @app.get("/api/safety/deficiencies")
    async def api_get_deficiencies(request: Request):
        params = request.query_params
        defs = get_deficiencies(
            status=params.get("status"),
            severity=params.get("severity"),
            asset_id=int(params["asset_id"]) if params.get("asset_id") else None,
        )
        return {"ok": True, "deficiencies": defs}

    @app.get("/api/safety/deficiencies/dashboard")
    async def api_deficiency_dashboard(request: Request):
        dash = get_deficiency_dashboard()
        return {"ok": True, "dashboard": dash}

    @app.put("/api/safety/deficiencies/{def_id}")
    async def api_update_deficiency(def_id: int, request: Request):
        data = await request.json()
        update_deficiency(def_id, data)

        # Emit event on resolution
        if data.get("status") == "resolved":
            try:
                from app.eventstream.emitter import emit_event
                d = get_deficiency(def_id)
                emit_event(
                    "SAFETY_DEFICIENCY_RESOLVED",
                    summary=f"Deficiency resolved: {d['asset_tag'] if d else def_id}",
                    user=data.get("resolved_by"),
                    category="safety", severity="info",
                )
            except Exception:
                pass

        return {"ok": True}

    # ============================================================
    # DASHBOARD
    # ============================================================

    @app.get("/api/safety/dashboard")
    async def api_dashboard(request: Request):
        stats = get_dashboard_stats()
        return {"ok": True, "dashboard": stats}

    @app.get("/api/safety/reports/compliance")
    async def api_compliance_report(request: Request):
        group_by = request.query_params.get("group_by", "type")
        report = get_compliance_report(group_by=group_by)
        return {"ok": True, "report": report}

    # ============================================================
    # SCHEDULES
    # ============================================================

    @app.get("/api/safety/schedules")
    async def api_get_schedules(request: Request):
        scheds = get_schedules()
        return {"ok": True, "schedules": scheds}

    @app.post("/api/safety/schedules")
    async def api_create_schedule(request: Request):
        data = await request.json()
        sid = create_schedule(data)
        return {"ok": True, "schedule_id": sid}

    @app.put("/api/safety/schedules/{sched_id}")
    async def api_update_schedule(sched_id: int, request: Request):
        data = await request.json()
        update_schedule(sched_id, data)
        return {"ok": True}

    @app.delete("/api/safety/schedules/{sched_id}")
    async def api_delete_schedule(sched_id: int, request: Request):
        delete_schedule(sched_id)
        return {"ok": True}

    # ============================================================
    # QR BATCH
    # ============================================================

    @app.post("/api/safety/qr/generate-batch")
    async def api_qr_batch(request: Request):
        data = await request.json()
        asset_ids = data.get("asset_ids", [])
        assets_list = []
        for aid in asset_ids:
            a = get_asset(aid)
            if a:
                assets_list.append(a)
        if not assets_list:
            return JSONResponse({"ok": False, "error": "No assets found"}, status_code=400)
        zip_bytes = generate_batch_zip(assets_list)
        return Response(content=zip_bytes, media_type="application/zip",
                        headers={"Content-Disposition": 'attachment; filename="safety-qr-codes.zip"'})

    @app.get("/api/safety/qr/print-sheet")
    async def api_qr_print_sheet(request: Request):
        type_id = request.query_params.get("type")
        loc_id = request.query_params.get("location")
        assets_list = get_assets(
            asset_type_id=int(type_id) if type_id else None,
            location_id=int(loc_id) if loc_id else None,
        )
        html = generate_print_sheet(assets_list)
        return HTMLResponse(html)

    # ============================================================
    # MODAL
    # ============================================================

    @app.get("/modals/safety", response_class=HTMLResponse)
    async def modal_safety(request: Request):
        return _render_safety_modal()


def _render_safety_modal() -> str:
    """Render the safety inspection admin modal."""
    stats = get_dashboard_stats()
    types = get_asset_types()
    locations = get_locations()

    types_options = "".join(f'<option value="{t["id"]}">{t["name"]}</option>' for t in types)
    loc_options = "".join(
        f'<option value="{l["id"]}">{l["name"]}{" — " + l["building"] if l.get("building") else ""}</option>'
        for l in locations
    )

    # KPI cards
    overdue_color = "#e53e3e" if stats["overdue"] > 0 else "#48bb78"
    def_color = "#e53e3e" if stats["critical_deficiencies"] > 0 else ("#d69e2e" if stats["open_deficiencies"] > 0 else "#48bb78")

    by_type_rows = ""
    for t in stats["by_type"]:
        bar_color = "#48bb78" if t["pct"] >= 90 else ("#d69e2e" if t["pct"] >= 70 else "#e53e3e")
        by_type_rows += f"""
        <tr>
            <td>{t["name"]}</td>
            <td style="text-align:center;">{t["total"]}</td>
            <td style="text-align:center;color:{bar_color};">{t["pct"]}%</td>
            <td style="text-align:center;color:#e53e3e;">{t["overdue_count"]}</td>
        </tr>"""

    return f"""
<div class="cad-modal-overlay" onclick="CAD_MODAL.close()"></div>
<div class="cad-modal safety-modal" role="dialog" aria-modal="true" aria-label="Safety Inspections">
    <div class="cad-modal-header">
        <div class="cad-modal-title">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
            </svg>
            Safety Inspections
        </div>
        <button class="cad-modal-close" onclick="CAD_MODAL.close()">&times;</button>
    </div>
    <div class="cad-modal-body" style="padding:0;display:flex;flex-direction:column;">
        <!-- Tab Bar -->
        <div class="safety-tabs">
            <button class="safety-tab active" onclick="SAFETY.switchTab('dashboard')" data-tab="dashboard">Dashboard</button>
            <button class="safety-tab" onclick="SAFETY.switchTab('assets')" data-tab="assets">Assets</button>
            <button class="safety-tab" onclick="SAFETY.switchTab('inspections')" data-tab="inspections">Inspections</button>
            <button class="safety-tab" onclick="SAFETY.switchTab('deficiencies')" data-tab="deficiencies">Deficiencies</button>
            <button class="safety-tab" onclick="SAFETY.switchTab('scan')" data-tab="scan">Scan</button>
            <button class="safety-tab" onclick="SAFETY.switchTab('locations')" data-tab="locations">Locations</button>
            <button class="safety-tab" onclick="SAFETY.switchTab('settings')" data-tab="settings">Settings</button>
        </div>

        <!-- Tab Content -->
        <div class="safety-content">

        <!-- ========== DASHBOARD TAB ========== -->
        <div id="safety-tab-dashboard" class="safety-panel">
            <div class="safety-kpi-grid">
                <div class="safety-kpi">
                    <div class="safety-kpi-value" style="color:var(--ford-blue,#63b3ed);">{stats["total_assets"]}</div>
                    <div class="safety-kpi-label">Total Assets</div>
                </div>
                <div class="safety-kpi">
                    <div class="safety-kpi-value" style="color:#48bb78;">{stats["compliant_pct"]}%</div>
                    <div class="safety-kpi-label">Compliant</div>
                </div>
                <div class="safety-kpi">
                    <div class="safety-kpi-value" style="color:{overdue_color};">{stats["overdue"]}</div>
                    <div class="safety-kpi-label">Overdue</div>
                </div>
                <div class="safety-kpi">
                    <div class="safety-kpi-value" style="color:{def_color};">{stats["open_deficiencies"]}</div>
                    <div class="safety-kpi-label">Open Deficiencies</div>
                </div>
            </div>

            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                <div>
                    <h4 class="safety-section-title">Compliance by Type</h4>
                    <table class="safety-table">
                        <thead><tr>
                            <th style="text-align:left;">Type</th>
                            <th>Total</th>
                            <th>Compliant</th>
                            <th>Overdue</th>
                        </tr></thead>
                        <tbody>{by_type_rows}</tbody>
                    </table>
                </div>
                <div>
                    <h4 class="safety-section-title">Recent Activity</h4>
                    <div id="safety-recent-activity" style="padding:8px;text-align:center;color:var(--text-muted,#6e7681);">
                        {stats["inspections_30d"]} inspections in last 30 days
                    </div>
                </div>
            </div>
        </div>

        <!-- ========== ASSETS TAB ========== -->
        <div id="safety-tab-assets" class="safety-panel" style="display:none;">
            <div class="safety-filter-bar">
                <select id="safety-filter-type" onchange="SAFETY.loadAssets()">
                    <option value="">All Types</option>
                    {types_options}
                </select>
                <select id="safety-filter-location" onchange="SAFETY.loadAssets()">
                    <option value="">All Locations</option>
                    {loc_options}
                </select>
                <select id="safety-filter-status" onchange="SAFETY.loadAssets()">
                    <option value="">All Status</option>
                    <option value="active">Active</option>
                    <option value="deficient">Deficient</option>
                    <option value="out_of_service">Out of Service</option>
                </select>
                <input id="safety-search" placeholder="Search tag/serial..." onkeyup="SAFETY.debounceSearch()" style="width:160px;" />
                <label style="font-size:var(--text-xs,11px);display:flex;align-items:center;gap:4px;">
                    <input type="checkbox" id="safety-filter-overdue" onchange="SAFETY.loadAssets()" style="width:auto;"> Overdue Only
                </label>
                <div style="flex:1;"></div>
                <button class="btn-primary" onclick="SAFETY.showAddAsset()">+ Add Asset</button>
            </div>
            <div id="safety-assets-table" class="safety-scroll-area">
                <div class="safety-empty">Loading assets...</div>
            </div>
        </div>

        <!-- ========== INSPECTIONS TAB ========== -->
        <div id="safety-tab-inspections" class="safety-panel" style="display:none;">
            <div style="display:flex;gap:var(--space-2,8px);margin-bottom:var(--space-3,12px);">
                <button id="safety-insp-pending-btn" class="btn-primary" onclick="SAFETY.loadPending()">Pending</button>
                <button id="safety-insp-history-btn" class="btn-secondary" onclick="SAFETY.loadHistory()">History</button>
            </div>
            <div id="safety-inspections-content" class="safety-scroll-area">
                <div class="safety-empty">Select Pending or History</div>
            </div>
        </div>

        <!-- ========== DEFICIENCIES TAB ========== -->
        <div id="safety-tab-deficiencies" class="safety-panel" style="display:none;">
            <div class="safety-filter-bar">
                <select id="safety-def-status" onchange="SAFETY.loadDeficiencies()">
                    <option value="">All Status</option>
                    <option value="open" selected>Open</option>
                    <option value="in_progress">In Progress</option>
                    <option value="resolved">Resolved</option>
                    <option value="deferred">Deferred</option>
                </select>
                <select id="safety-def-severity" onchange="SAFETY.loadDeficiencies()">
                    <option value="">All Severity</option>
                    <option value="critical">Critical</option>
                    <option value="major">Major</option>
                    <option value="minor">Minor</option>
                </select>
            </div>
            <div id="safety-deficiencies-content" class="safety-scroll-area">
                <div class="safety-empty">Loading...</div>
            </div>
        </div>

        <!-- ========== SCAN TAB ========== -->
        <div id="safety-tab-scan" class="safety-panel" style="display:none;">
            <div style="text-align:center;padding:var(--space-3,12px);">
                <div style="position:relative;width:320px;height:240px;margin:0 auto var(--space-3,12px);background:#000;border-radius:var(--radius-md,6px);overflow:hidden;">
                    <video id="safety-scanner-video" autoplay playsinline style="width:100%;height:100%;object-fit:cover;"></video>
                    <div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:200px;height:200px;border:2px solid var(--ford-blue,#3b82f6);border-radius:8px;pointer-events:none;"></div>
                </div>
                <button class="btn-primary" onclick="SAFETY.startScanner()" style="margin-right:8px;">Start Camera</button>
                <button class="btn-secondary" onclick="SAFETY.stopScanner()">Stop</button>
                <div style="margin-top:var(--space-3,12px);">
                    <span style="font-size:var(--text-sm,12px);color:var(--text-secondary,#8b949e);">Or enter asset tag manually:</span>
                    <div style="display:flex;gap:6px;justify-content:center;margin-top:6px;">
                        <input id="safety-manual-tag" placeholder="FE-001 or QR UUID" style="width:200px;" />
                        <button class="btn-primary" onclick="SAFETY.manualLookup()">Lookup</button>
                    </div>
                </div>
                <div id="safety-scan-result" style="margin-top:var(--space-4,16px);"></div>
            </div>
        </div>

        <!-- ========== LOCATIONS TAB ========== -->
        <div id="safety-tab-locations" class="safety-panel" style="display:none;">
            <div style="display:flex;gap:var(--space-2,8px);margin-bottom:var(--space-3,12px);align-items:center;">
                <h4 class="safety-section-title" style="flex:1;margin:0;">Locations</h4>
                <button class="btn-primary" onclick="SAFETY.showAddLocation()">+ Add Location</button>
            </div>
            <div id="safety-locations-content" class="safety-scroll-area">
                <div class="safety-empty">Loading...</div>
            </div>
        </div>

        <!-- ========== SETTINGS TAB ========== -->
        <div id="safety-tab-settings" class="safety-panel" style="display:none;">
            <h4 class="safety-section-title">Asset Types</h4>
            <div id="safety-settings-types" style="margin-bottom:var(--space-4,16px);">Loading...</div>

            <h4 class="safety-section-title">Inspection Templates</h4>
            <div id="safety-settings-templates">Loading...</div>

            <h4 class="safety-section-title" style="margin-top:var(--space-4,16px);">QR Batch Tools</h4>
            <div style="display:flex;gap:var(--space-2,8px);flex-wrap:wrap;">
                <button class="btn-secondary" onclick="SAFETY.printAllQR()">Print All QR Labels</button>
                <button class="btn-secondary" onclick="SAFETY.downloadQRZip()">Download QR ZIP</button>
            </div>
        </div>

        </div><!-- end safety-content -->
    </div><!-- end cad-modal-body -->

<style>
.safety-modal {{ min-width: 700px; max-width: 1000px; width: 92vw; max-height: 88vh; }}
.safety-tabs {{
    display: flex; gap: var(--space-1, 4px);
    border-bottom: 1px solid var(--border-default, #30363d);
    padding: 0 var(--space-3, 12px);
    background: var(--bg-elevated, #21262d);
}}
.safety-tab {{
    padding: var(--space-2, 8px) var(--space-3, 12px);
    background: transparent; border: none;
    color: var(--text-secondary, #8b949e);
    font-size: var(--text-sm, 12px); font-weight: 600;
    cursor: pointer; border-bottom: 2px solid transparent;
}}
.safety-tab.active {{ color: var(--ford-blue, #3b82f6); border-bottom-color: var(--ford-blue, #3b82f6); }}
.safety-tab:hover {{ color: var(--text-primary, #f0f6fc); }}
.safety-content {{ flex: 1; overflow-y: auto; padding: var(--space-4, 16px); }}
.safety-kpi-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--space-3, 12px); margin-bottom: var(--space-4, 16px); }}
.safety-kpi {{
    background: var(--bg-elevated, #21262d); border-radius: var(--radius-md, 6px);
    padding: var(--space-3, 12px); text-align: center;
    border: 1px solid var(--border-default, #30363d);
}}
.safety-kpi-value {{ font-size: 24px; font-weight: bold; }}
.safety-kpi-label {{ font-size: var(--text-xs, 11px); color: var(--text-secondary, #8b949e); margin-top: 2px; }}
.safety-section-title {{ margin: 0 0 var(--space-2, 8px); font-size: var(--text-sm, 12px); font-weight: 700; color: var(--text-secondary, #8b949e); text-transform: uppercase; }}
.safety-table {{ width: 100%; border-collapse: collapse; }}
.safety-table th {{
    padding: var(--space-1, 4px) var(--space-2, 8px);
    text-align: center; font-size: var(--text-xs, 11px);
    font-weight: 700; color: var(--text-secondary, #8b949e);
    text-transform: uppercase;
    border-bottom: 1px solid var(--border-default, #30363d);
}}
.safety-table td {{
    padding: var(--space-1, 4px) var(--space-2, 8px);
    font-size: var(--text-sm, 12px); color: var(--text-primary, #f0f6fc);
    border-bottom: 1px solid var(--border-light, rgba(48,54,61,0.5));
}}
.safety-filter-bar {{
    display: flex; gap: var(--space-2, 8px); margin-bottom: var(--space-3, 12px);
    flex-wrap: wrap; align-items: center;
}}
.safety-filter-bar select, .safety-filter-bar input {{
    padding: var(--space-1, 4px) var(--space-2, 8px);
    font-size: var(--text-sm, 12px);
}}
.safety-scroll-area {{ max-height: 55vh; overflow-y: auto; }}
.safety-empty {{ text-align: center; color: var(--text-muted, #6e7681); padding: var(--space-6, 24px); }}
.safety-form-panel {{
    background: var(--bg-elevated, #21262d); border-radius: var(--radius-md, 6px);
    padding: var(--space-3, 12px); border: 1px solid var(--border-default, #30363d);
}}
.safety-form-panel h4 {{ margin: 0 0 var(--space-3, 12px); color: var(--ford-blue, #3b82f6); }}
.safety-form-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-2, 8px); }}
.safety-form-grid label {{ font-size: var(--text-xs, 11px); }}
.safety-form-grid input, .safety-form-grid select {{ font-size: var(--text-sm, 12px); }}
.safety-loc-group {{ margin-bottom: var(--space-3, 12px); }}
.safety-loc-group h5 {{
    margin: 0 0 var(--space-1, 4px); font-size: var(--text-sm, 12px);
    color: var(--ford-blue, #3b82f6); border-bottom: 1px solid var(--border-default, #30363d);
    padding-bottom: var(--space-1, 4px);
}}
.safety-loc-item {{
    display: flex; align-items: center; gap: var(--space-2, 8px);
    padding: var(--space-1, 4px) var(--space-2, 8px);
}}
.safety-loc-item span {{ color: var(--text-secondary, #8b949e); }}
</style>

<script>
window.SAFETY = window.SAFETY || {{}};

/* ---- Tab switching ---- */
SAFETY.switchTab = function(tab) {{
    document.querySelectorAll('.safety-panel').forEach(function(el) {{ el.style.display = 'none'; }});
    document.querySelectorAll('.safety-tab').forEach(function(el) {{ el.classList.remove('active'); }});
    var panel = document.getElementById('safety-tab-' + tab);
    if (panel) panel.style.display = 'block';
    var btn = document.querySelector('.safety-tab[data-tab="' + tab + '"]');
    if (btn) btn.classList.add('active');

    if (tab === 'assets') SAFETY.loadAssets();
    else if (tab === 'inspections') SAFETY.loadPending();
    else if (tab === 'deficiencies') SAFETY.loadDeficiencies();
    else if (tab === 'locations') SAFETY.loadLocations();
    else if (tab === 'settings') SAFETY.loadSettings();
}};

/* ---- Assets ---- */
SAFETY._searchTimer = null;
SAFETY.debounceSearch = function() {{
    clearTimeout(SAFETY._searchTimer);
    SAFETY._searchTimer = setTimeout(SAFETY.loadAssets, 300);
}};

SAFETY.loadAssets = function() {{
    var type = document.getElementById('safety-filter-type').value;
    var loc = document.getElementById('safety-filter-location').value;
    var status = document.getElementById('safety-filter-status').value;
    var search = document.getElementById('safety-search').value;
    var overdue = document.getElementById('safety-filter-overdue').checked;
    var q = '/api/safety/assets?';
    if (type) q += 'type=' + type + '&';
    if (loc) q += 'location=' + loc + '&';
    if (status) q += 'status=' + status + '&';
    if (search) q += 'search=' + encodeURIComponent(search) + '&';
    if (overdue) q += 'overdue=true&';

    fetch(q).then(function(r) {{ return r.json(); }}).then(function(data) {{
        if (!data.ok) return;
        var assets = data.assets;
        var today = new Date().toISOString().slice(0, 10);
        var soon = new Date(Date.now() + 7 * 86400000).toISOString().slice(0, 10);
        var html = '<table class="safety-table">';
        html += '<thead><tr>';
        html += '<th style="text-align:left;">Tag</th>';
        html += '<th style="text-align:left;">Type</th>';
        html += '<th style="text-align:left;">Location</th>';
        html += '<th>Status</th>';
        html += '<th>Last Inspected</th>';
        html += '<th>Next Due</th>';
        html += '<th style="width:100px;"></th>';
        html += '</tr></thead><tbody>';
        if (assets.length === 0) {{
            html += '<tr><td colspan="7" class="safety-empty">No assets found</td></tr>';
        }}
        assets.forEach(function(a) {{
            var rowColor = '';
            if (a.next_inspection_due && a.next_inspection_due < today) rowColor = 'border-left:3px solid #e53e3e;';
            else if (a.next_inspection_due && a.next_inspection_due <= soon) rowColor = 'border-left:3px solid #d69e2e;';
            else rowColor = 'border-left:3px solid #48bb78;';

            var statusBadge = '<span style="font-size:10px;padding:2px 6px;border-radius:3px;';
            if (a.status === 'active') statusBadge += 'background:#22543d20;color:#48bb78;">Active</span>';
            else if (a.status === 'deficient') statusBadge += 'background:#ecc94b20;color:#ecc94b;">Deficient</span>';
            else statusBadge += 'background:#ef444420;color:#ef4444;">OOS</span>';

            html += '<tr style="' + rowColor + 'cursor:pointer;" onclick="SAFETY.viewAsset(' + a.id + ')">';
            html += '<td style="font-weight:bold;">' + (a.asset_tag || '') + '</td>';
            html += '<td>' + (a.type_name || '') + '</td>';
            html += '<td>' + (a.location_name || '') + '</td>';
            html += '<td style="text-align:center;">' + statusBadge + '</td>';
            html += '<td style="text-align:center;color:var(--text-secondary);">' + (a.last_inspection_date || 'Never') + '</td>';
            html += '<td style="text-align:center;">' + (a.next_inspection_due || '\u2014') + '</td>';
            html += '<td style="text-align:center;">';
            html += '<button onclick="event.stopPropagation();SAFETY.inspectAsset(' + a.id + ')" class="btn-primary" style="padding:2px 8px;font-size:10px;">Inspect</button> ';
            html += '<button onclick="event.stopPropagation();SAFETY.showQR(' + a.id + ')" class="btn-secondary" style="padding:2px 8px;font-size:10px;">QR</button>';
            html += '</td></tr>';
        }});
        html += '</tbody></table>';
        document.getElementById('safety-assets-table').innerHTML = html;
    }});
}};

/* ---- View single asset ---- */
SAFETY.viewAsset = function(id) {{
    fetch('/api/safety/assets/' + id).then(function(r) {{ return r.json(); }}).then(function(data) {{
        if (!data.ok) return;
        var a = data.asset;
        var hist = data.history || [];
        var defs = data.deficiencies || [];

        var histRows = '';
        hist.forEach(function(h) {{
            var rColor = h.result === 'pass' ? '#48bb78' : (h.result === 'partial' ? '#ecc94b' : '#e53e3e');
            histRows += '<tr><td>' + (h.inspection_date || '') + '</td>';
            histRows += '<td>' + (h.template_name || '') + '</td>';
            histRows += '<td style="color:' + rColor + ';">' + (h.result || '') + '</td>';
            histRows += '<td>' + (h.inspector_name || h.inspector_unit_id || '') + '</td></tr>';
        }});

        var defRows = '';
        defs.forEach(function(d) {{
            var sColor = d.severity === 'critical' ? '#e53e3e' : (d.severity === 'major' ? '#ecc94b' : 'var(--text-secondary)');
            defRows += '<tr><td style="color:' + sColor + ';">' + d.severity + '</td>';
            defRows += '<td>' + (d.description || '') + '</td>';
            defRows += '<td>' + d.status + '</td></tr>';
        }});

        var html = '<div class="safety-form-panel" style="margin-bottom:12px;">';
        html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">';
        html += '<h4 style="margin:0;color:var(--ford-blue,#3b82f6);">' + (a.asset_tag || '') + '</h4>';
        html += '<button class="btn-secondary" onclick="SAFETY.loadAssets()" style="padding:3px 10px;font-size:11px;">Back</button>';
        html += '</div>';
        html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:var(--text-sm,12px);">';
        html += '<div><span style="color:var(--text-muted);">Type:</span> ' + (a.type_name || '') + '</div>';
        html += '<div><span style="color:var(--text-muted);">Location:</span> ' + (a.location_name || '') + '</div>';
        html += '<div><span style="color:var(--text-muted);">Serial:</span> ' + (a.serial_number || '\u2014') + '</div>';
        html += '<div><span style="color:var(--text-muted);">Manufacturer:</span> ' + (a.manufacturer || '\u2014') + '</div>';
        html += '<div><span style="color:var(--text-muted);">Install Date:</span> ' + (a.install_date || '\u2014') + '</div>';
        html += '<div><span style="color:var(--text-muted);">Expiration:</span> ' + (a.expiration_date || '\u2014') + '</div>';
        html += '<div><span style="color:var(--text-muted);">Status:</span> ' + (a.status || '') + '</div>';
        html += '<div><span style="color:var(--text-muted);">Next Due:</span> ' + (a.next_inspection_due || '\u2014') + '</div>';
        html += '</div>';
        if (a.photo_url) html += '<img src="' + a.photo_url + '" style="max-width:120px;margin-top:8px;border-radius:4px;" />';
        html += '<div style="margin-top:8px;"><button class="btn-primary" onclick="SAFETY.inspectAsset(' + a.id + ')">Start Inspection</button></div>';
        html += '</div>';

        if (hist.length > 0) {{
            html += '<h5 class="safety-section-title" style="margin-top:8px;">Inspection History</h5>';
            html += '<table class="safety-table"><thead><tr>';
            html += '<th style="text-align:left;">Date</th>';
            html += '<th style="text-align:left;">Template</th>';
            html += '<th style="text-align:left;">Result</th>';
            html += '<th style="text-align:left;">Inspector</th>';
            html += '</tr></thead><tbody>' + histRows + '</tbody></table>';
        }}

        if (defs.length > 0) {{
            html += '<h5 class="safety-section-title" style="margin-top:8px;">Deficiencies</h5>';
            html += '<table class="safety-table"><thead><tr>';
            html += '<th style="text-align:left;">Severity</th>';
            html += '<th style="text-align:left;">Description</th>';
            html += '<th style="text-align:left;">Status</th>';
            html += '</tr></thead><tbody>' + defRows + '</tbody></table>';
        }}

        document.getElementById('safety-assets-table').innerHTML = html;
    }});
}};

/* ---- Add Asset Form ---- */
SAFETY.showAddAsset = function() {{
    var html = '<div class="safety-form-panel">';
    html += '<h4>Add New Asset</h4>';
    html += '<div class="safety-form-grid">';
    html += '<div><label>Type</label><select id="sa-type">{types_options}</select></div>';
    html += '<div><label>Location</label><select id="sa-loc"><option value="">None</option>{loc_options}</select></div>';
    html += '<div><label>Asset Tag (auto if blank)</label><input id="sa-tag" /></div>';
    html += '<div><label>Serial Number</label><input id="sa-serial" /></div>';
    html += '<div><label>Manufacturer</label><input id="sa-mfg" /></div>';
    html += '<div><label>Model</label><input id="sa-model" /></div>';
    html += '<div><label>Install Date</label><input id="sa-install" type="date" /></div>';
    html += '<div><label>Expiration Date</label><input id="sa-expire" type="date" /></div>';
    html += '</div>';
    html += '<div style="margin-top:var(--space-2,8px);"><label>Notes</label><textarea id="sa-notes" rows="2" style="resize:vertical;"></textarea></div>';
    html += '<div style="margin-top:var(--space-3,12px);display:flex;gap:var(--space-2,8px);">';
    html += '<button class="btn-primary" onclick="SAFETY.saveAsset()">Save</button>';
    html += '<button class="btn-secondary" onclick="SAFETY.loadAssets()">Cancel</button>';
    html += '</div></div>';
    document.getElementById('safety-assets-table').innerHTML = html;
}};

SAFETY.saveAsset = function() {{
    var body = {{
        asset_type_id: parseInt(document.getElementById('sa-type').value),
        location_id: document.getElementById('sa-loc').value ? parseInt(document.getElementById('sa-loc').value) : null,
        asset_tag: document.getElementById('sa-tag').value || undefined,
        serial_number: document.getElementById('sa-serial').value || undefined,
        manufacturer: document.getElementById('sa-mfg').value || undefined,
        model: document.getElementById('sa-model').value || undefined,
        install_date: document.getElementById('sa-install').value || undefined,
        expiration_date: document.getElementById('sa-expire').value || undefined,
        notes: document.getElementById('sa-notes').value || undefined,
    }};
    fetch('/api/safety/assets', {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify(body)}})
        .then(function(r) {{ return r.json(); }})
        .then(function(data) {{
            if (data.ok) SAFETY.loadAssets();
            else alert('Error: ' + (data.error || 'Unknown'));
        }});
}};

/* ---- Inspect Asset ---- */
SAFETY.inspectAsset = function(assetId) {{
    fetch('/api/safety/assets/' + assetId).then(function(r) {{ return r.json(); }}).then(function(data) {{
        if (!data.ok) return;
        var a = data.asset;
        var templates = data.templates || [];
        if (templates.length === 0) {{
            alert('No inspection templates available for this asset type.');
            return;
        }}

        // Default to first template
        SAFETY._currentInspection = {{ assetId: assetId, asset: a }};
        SAFETY._showInspectionForm(a, templates, templates[0]);
    }});
}};

SAFETY._showInspectionForm = function(asset, templates, selectedTemplate) {{
    var items = [];
    try {{ items = JSON.parse(selectedTemplate.checklist_items || '[]'); }} catch(e) {{}}

    var tplSelect = '<select id="si-template" onchange="SAFETY._changeTemplate(' + asset.id + ')">';
    templates.forEach(function(t) {{
        tplSelect += '<option value="' + t.id + '"' + (t.id === selectedTemplate.id ? ' selected' : '') + '>' + t.name + ' (' + t.tier + ')</option>';
    }});
    tplSelect += '</select>';

    var checklistHtml = '';
    items.forEach(function(item, idx) {{
        if (item.type === 'pass_fail') {{
            checklistHtml += '<div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--border-default,#30363d);">';
            checklistHtml += '<span style="flex:1;font-size:var(--text-sm,12px);">' + item.label + (item.required ? ' *' : '') + '</span>';
            checklistHtml += '<select data-field="' + item.field + '" class="si-response" style="width:80px;padding:3px 6px;">';
            checklistHtml += '<option value="">\u2014</option><option value="pass">Pass</option><option value="fail">Fail</option>';
            checklistHtml += '</select></div>';
        }} else if (item.type === 'date') {{
            checklistHtml += '<div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--border-default,#30363d);">';
            checklistHtml += '<span style="flex:1;font-size:var(--text-sm,12px);">' + item.label + '</span>';
            checklistHtml += '<input data-field="' + item.field + '" class="si-response" type="date" style="width:130px;padding:3px 6px;" />';
            checklistHtml += '</div>';
        }}
    }});

    var html = '<div class="safety-form-panel">';
    html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:var(--space-3,12px);">';
    html += '<h4 style="margin:0;">Inspect: ' + (asset.asset_tag || '') + '</h4>';
    html += '<button class="btn-secondary" onclick="SAFETY.loadAssets()" style="padding:3px 10px;font-size:11px;">Cancel</button>';
    html += '</div>';
    html += '<div style="font-size:var(--text-xs,11px);color:var(--text-secondary);margin-bottom:var(--space-2,8px);">' + (asset.type_name || '') + ' \u2014 ' + (asset.location_name || '') + '</div>';
    html += '<div style="margin-bottom:var(--space-3,12px);">' + tplSelect + '</div>';
    html += '<div style="max-height:300px;overflow-y:auto;">' + checklistHtml + '</div>';
    html += '<div style="margin-top:var(--space-3,12px);"><label>Inspector Name</label><input id="si-inspector" value="" /></div>';
    html += '<div style="margin-top:var(--space-2,8px);"><label>Notes</label><textarea id="si-notes" rows="2" style="resize:vertical;"></textarea></div>';
    html += '<div style="margin-top:var(--space-3,12px);">';
    html += '<button class="btn-primary" onclick="SAFETY.submitInspection(' + asset.id + ')" style="font-weight:bold;">Submit Inspection</button>';
    html += '</div></div>';

    document.getElementById('safety-assets-table').innerHTML = html;
    SAFETY._currentTemplateId = selectedTemplate.id;
    SAFETY._allTemplates = templates;
}};

SAFETY._changeTemplate = function(assetId) {{
    var tplId = parseInt(document.getElementById('si-template').value);
    var tpl = SAFETY._allTemplates.find(function(t) {{ return t.id === tplId; }});
    if (tpl && SAFETY._currentInspection) {{
        SAFETY._showInspectionForm(SAFETY._currentInspection.asset, SAFETY._allTemplates, tpl);
    }}
}};

SAFETY.submitInspection = function(assetId) {{
    var responses = {{}};
    document.querySelectorAll('.si-response').forEach(function(el) {{
        var field = el.getAttribute('data-field');
        if (el.value) responses[field] = el.value;
    }});

    var body = {{
        asset_id: assetId,
        template_id: SAFETY._currentTemplateId,
        inspector_name: document.getElementById('si-inspector').value,
        notes: document.getElementById('si-notes').value,
        responses: responses,
    }};

    fetch('/api/safety/inspections', {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify(body)}})
        .then(function(r) {{ return r.json(); }})
        .then(function(data) {{
            if (data.ok) {{
                alert('Inspection submitted successfully!');
                SAFETY.viewAsset(assetId);
            }} else {{
                alert('Error: ' + (data.error || 'Unknown'));
            }}
        }});
}};

/* ---- Pending / History ---- */
SAFETY.loadPending = function() {{
    document.getElementById('safety-insp-pending-btn').className = 'btn-primary';
    document.getElementById('safety-insp-history-btn').className = 'btn-secondary';
    fetch('/api/safety/inspections/pending?days=30').then(function(r) {{ return r.json(); }}).then(function(data) {{
        if (!data.ok) return;
        var items = data.pending || [];
        var today = new Date().toISOString().slice(0, 10);
        var html = '<table class="safety-table">';
        html += '<thead><tr>';
        html += '<th style="text-align:left;">Asset</th>';
        html += '<th style="text-align:left;">Type</th>';
        html += '<th style="text-align:left;">Location</th>';
        html += '<th>Due Date</th>';
        html += '<th style="width:80px;"></th>';
        html += '</tr></thead><tbody>';
        if (items.length === 0) html += '<tr><td colspan="5" class="safety-empty">No pending inspections</td></tr>';
        items.forEach(function(a) {{
            var overdue = a.next_inspection_due && a.next_inspection_due < today;
            var rowStyle = overdue ? 'border-left:3px solid #e53e3e;' : 'border-left:3px solid #d69e2e;';
            html += '<tr style="' + rowStyle + '">';
            html += '<td style="font-weight:bold;">' + (a.asset_tag || '') + '</td>';
            html += '<td>' + (a.type_name || '') + '</td>';
            html += '<td>' + (a.location_name || '') + '</td>';
            html += '<td style="text-align:center;color:' + (overdue ? '#e53e3e' : '#d69e2e') + ';">' + (a.next_inspection_due || '') + (overdue ? ' OVERDUE' : '') + '</td>';
            html += '<td><button onclick="SAFETY.inspectAsset(' + a.id + ')" class="btn-primary" style="padding:2px 8px;font-size:10px;">Inspect</button></td>';
            html += '</tr>';
        }});
        html += '</tbody></table>';
        document.getElementById('safety-inspections-content').innerHTML = html;
    }});
}};

SAFETY.loadHistory = function() {{
    document.getElementById('safety-insp-history-btn').className = 'btn-primary';
    document.getElementById('safety-insp-pending-btn').className = 'btn-secondary';
    fetch('/api/safety/inspections').then(function(r) {{ return r.json(); }}).then(function(data) {{
        if (!data.ok) return;
        var items = data.inspections || [];
        var html = '<table class="safety-table">';
        html += '<thead><tr>';
        html += '<th style="text-align:left;">Date</th>';
        html += '<th style="text-align:left;">Asset</th>';
        html += '<th style="text-align:left;">Template</th>';
        html += '<th>Result</th>';
        html += '<th style="text-align:left;">Inspector</th>';
        html += '</tr></thead><tbody>';
        if (items.length === 0) html += '<tr><td colspan="5" class="safety-empty">No inspection records</td></tr>';
        items.forEach(function(i) {{
            var rColor = i.result === 'pass' ? '#48bb78' : (i.result === 'partial' ? '#ecc94b' : '#e53e3e');
            html += '<tr>';
            html += '<td>' + (i.inspection_date || '') + '</td>';
            html += '<td style="font-weight:bold;">' + (i.asset_tag || '') + '</td>';
            html += '<td>' + (i.template_name || '') + '</td>';
            html += '<td style="text-align:center;color:' + rColor + ';font-weight:bold;">' + (i.result || '').toUpperCase() + '</td>';
            html += '<td>' + (i.inspector_name || i.inspector_unit_id || '') + '</td>';
            html += '</tr>';
        }});
        html += '</tbody></table>';
        document.getElementById('safety-inspections-content').innerHTML = html;
    }});
}};

/* ---- Deficiencies ---- */
SAFETY.loadDeficiencies = function() {{
    var status = document.getElementById('safety-def-status').value;
    var severity = document.getElementById('safety-def-severity').value;
    var q = '/api/safety/deficiencies?';
    if (status) q += 'status=' + status + '&';
    if (severity) q += 'severity=' + severity + '&';

    fetch(q).then(function(r) {{ return r.json(); }}).then(function(data) {{
        if (!data.ok) return;
        var defs = data.deficiencies || [];
        var html = '<table class="safety-table">';
        html += '<thead><tr>';
        html += '<th style="text-align:left;">Asset</th>';
        html += '<th style="text-align:left;">Description</th>';
        html += '<th>Severity</th>';
        html += '<th>Status</th>';
        html += '<th style="text-align:left;">Assigned</th>';
        html += '<th style="width:120px;"></th>';
        html += '</tr></thead><tbody>';
        if (defs.length === 0) html += '<tr><td colspan="6" class="safety-empty">No deficiencies found</td></tr>';
        defs.forEach(function(d) {{
            var sColor = d.severity === 'critical' ? '#e53e3e' : (d.severity === 'major' ? '#ecc94b' : 'var(--text-secondary)');
            var stColor = d.status === 'open' ? '#e53e3e' : (d.status === 'in_progress' ? '#ecc94b' : '#48bb78');
            html += '<tr>';
            html += '<td style="font-weight:bold;">' + (d.asset_tag || '') + '</td>';
            html += '<td>' + (d.description || '') + '</td>';
            html += '<td style="text-align:center;"><span style="font-size:10px;padding:2px 6px;border-radius:3px;color:' + sColor + ';">' + d.severity + '</span></td>';
            html += '<td style="text-align:center;"><span style="font-size:10px;padding:2px 6px;border-radius:3px;color:' + stColor + ';">' + d.status + '</span></td>';
            html += '<td>' + (d.assigned_to || '\u2014') + '</td>';
            html += '<td>';
            if (d.status !== 'resolved') {{
                html += '<select onchange="SAFETY.updateDefStatus(' + d.id + ', this.value)" style="width:auto;padding:2px 4px;font-size:10px;">';
                html += '<option value="">Action...</option>';
                html += '<option value="in_progress">In Progress</option>';
                html += '<option value="resolved">Resolve</option>';
                html += '<option value="deferred">Defer</option>';
                html += '</select>';
            }}
            html += '</td></tr>';
        }});
        html += '</tbody></table>';
        document.getElementById('safety-deficiencies-content').innerHTML = html;
    }});
}};

SAFETY.updateDefStatus = function(defId, newStatus) {{
    if (!newStatus) return;
    var body = {{ status: newStatus }};
    if (newStatus === 'resolved') {{
        body.resolved_date = new Date().toISOString().slice(0, 10);
        body.resolved_by = 'Admin';
    }}
    fetch('/api/safety/deficiencies/' + defId, {{method: 'PUT', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify(body)}})
        .then(function() {{ SAFETY.loadDeficiencies(); }});
}};

/* ---- QR Scanner ---- */
SAFETY._scannerStream = null;
SAFETY._scannerInterval = null;

SAFETY.startScanner = function() {{
    var video = document.getElementById('safety-scanner-video');
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {{
        document.getElementById('safety-scan-result').innerHTML = '<div style="color:#e53e3e;font-size:12px;">Camera not available. Use manual entry.</div>';
        return;
    }}
    navigator.mediaDevices.getUserMedia({{ video: {{ facingMode: 'environment' }} }}).then(function(stream) {{
        SAFETY._scannerStream = stream;
        video.srcObject = stream;
        video.play();
        // Start scanning frames
        var canvas = document.createElement('canvas');
        var ctx = canvas.getContext('2d');
        SAFETY._scannerInterval = setInterval(function() {{
            if (video.readyState !== video.HAVE_ENOUGH_DATA) return;
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            ctx.drawImage(video, 0, 0);
            var imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
            if (typeof jsQR !== 'undefined') {{
                var code = jsQR(imageData.data, canvas.width, canvas.height);
                if (code && code.data) {{
                    var qrData = code.data;
                    // Strip prefix if present
                    if (qrData.startsWith('FORDCAD:SAFETY:')) qrData = qrData.substring(15);
                    SAFETY.stopScanner();
                    SAFETY._lookupQR(qrData);
                }}
            }}
        }}, 250);
    }}).catch(function(err) {{
        document.getElementById('safety-scan-result').innerHTML = '<div style="color:#e53e3e;font-size:12px;">Camera error: ' + err.message + '</div>';
    }});
}};

SAFETY.stopScanner = function() {{
    if (SAFETY._scannerInterval) {{ clearInterval(SAFETY._scannerInterval); SAFETY._scannerInterval = null; }}
    if (SAFETY._scannerStream) {{
        SAFETY._scannerStream.getTracks().forEach(function(t) {{ t.stop(); }});
        SAFETY._scannerStream = null;
    }}
}};

SAFETY.manualLookup = function() {{
    var val = document.getElementById('safety-manual-tag').value.trim();
    if (!val) return;
    SAFETY._lookupQR(val);
}};

SAFETY._lookupQR = function(qrCode) {{
    document.getElementById('safety-scan-result').innerHTML = '<div style="color:var(--text-secondary);font-size:var(--text-sm,12px);">Looking up...</div>';
    fetch('/api/safety/assets/scan/' + encodeURIComponent(qrCode)).then(function(r) {{ return r.json(); }}).then(function(data) {{
        if (!data.ok) {{
            document.getElementById('safety-scan-result').innerHTML = '<div style="color:#e53e3e;font-size:var(--text-sm,12px);">Asset not found for: ' + qrCode + '</div>';
            return;
        }}
        var a = data.asset;
        var html = '<div class="safety-form-panel" style="text-align:left;">';
        html += '<h4 style="margin:0 0 8px;color:#48bb78;">Found: ' + a.asset_tag + '</h4>';
        html += '<div style="font-size:var(--text-sm,12px);margin-bottom:4px;"><span style="color:var(--text-muted);">Type:</span> ' + (a.type_name || '') + '</div>';
        html += '<div style="font-size:var(--text-sm,12px);margin-bottom:4px;"><span style="color:var(--text-muted);">Location:</span> ' + (a.location_name || '') + '</div>';
        html += '<div style="font-size:var(--text-sm,12px);margin-bottom:4px;"><span style="color:var(--text-muted);">Status:</span> ' + (a.status || '') + '</div>';
        html += '<div style="font-size:var(--text-sm,12px);margin-bottom:8px;"><span style="color:var(--text-muted);">Next Due:</span> ' + (a.next_inspection_due || '\u2014') + '</div>';
        html += '<button onclick="SAFETY.switchTab(\\x27assets\\x27);SAFETY.inspectAsset(' + a.id + ')" class="btn-primary" style="font-weight:bold;">Start Inspection</button> ';
        html += '<button onclick="SAFETY.switchTab(\\x27assets\\x27);SAFETY.viewAsset(' + a.id + ')" class="btn-secondary">View Details</button>';
        html += '</div>';
        document.getElementById('safety-scan-result').innerHTML = html;
    }}).catch(function() {{
        document.getElementById('safety-scan-result').innerHTML = '<div style="color:#e53e3e;font-size:var(--text-sm,12px);">Lookup failed</div>';
    }});
}};

/* ---- Locations ---- */
SAFETY.loadLocations = function() {{
    fetch('/api/safety/locations').then(function(r) {{ return r.json(); }}).then(function(data) {{
        if (!data.ok) return;
        var locs = data.locations || [];
        var grouped = {{}};
        locs.forEach(function(l) {{
            var bldg = l.building || 'Unassigned';
            if (!grouped[bldg]) grouped[bldg] = [];
            grouped[bldg].push(l);
        }});
        var html = '';
        Object.keys(grouped).sort().forEach(function(bldg) {{
            html += '<div class="safety-loc-group">';
            html += '<h5>' + bldg + '</h5>';
            grouped[bldg].forEach(function(l) {{
                html += '<div class="safety-loc-item">';
                html += '<span style="flex:1;color:var(--text-primary);">' + l.name + '</span>';
                html += '<span>' + (l.floor ? 'Floor ' + l.floor : '') + (l.area ? ' / ' + l.area : '') + '</span>';
                html += '<button class="btn-icon danger" onclick="SAFETY.deleteLocation(' + l.id + ')">Del</button>';
                html += '</div>';
            }});
            html += '</div>';
        }});
        if (locs.length === 0) html = '<div class="safety-empty">No locations defined yet.</div>';
        document.getElementById('safety-locations-content').innerHTML = html;
    }});
}};

SAFETY.showAddLocation = function() {{
    var html = '<div class="safety-form-panel">';
    html += '<h4>Add Location</h4>';
    html += '<div class="safety-form-grid">';
    html += '<div><label>Name</label><input id="sl-name" /></div>';
    html += '<div><label>Building</label><input id="sl-bldg" /></div>';
    html += '<div><label>Floor</label><input id="sl-floor" /></div>';
    html += '<div><label>Area</label><input id="sl-area" /></div>';
    html += '</div>';
    html += '<div style="margin-top:var(--space-2,8px);"><label>Notes</label><textarea id="sl-notes" rows="2" style="resize:vertical;"></textarea></div>';
    html += '<div style="margin-top:var(--space-3,12px);display:flex;gap:var(--space-2,8px);">';
    html += '<button class="btn-primary" onclick="SAFETY.saveLocation()">Save</button>';
    html += '<button class="btn-secondary" onclick="SAFETY.loadLocations()">Cancel</button>';
    html += '</div></div>';
    document.getElementById('safety-locations-content').innerHTML = html;
}};

SAFETY.saveLocation = function() {{
    var body = {{
        name: document.getElementById('sl-name').value,
        building: document.getElementById('sl-bldg').value || undefined,
        floor: document.getElementById('sl-floor').value || undefined,
        area: document.getElementById('sl-area').value || undefined,
        notes: document.getElementById('sl-notes').value || undefined,
    }};
    if (!body.name) {{ alert('Name is required'); return; }}
    fetch('/api/safety/locations', {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify(body)}})
        .then(function(r) {{ return r.json(); }})
        .then(function(data) {{
            if (data.ok) {{ SAFETY.loadLocations(); CAD_MODAL.open('/modals/safety'); }}
        }});
}};

SAFETY.deleteLocation = function(id) {{
    if (!confirm('Delete this location?')) return;
    fetch('/api/safety/locations/' + id, {{method: 'DELETE'}}).then(function() {{ SAFETY.loadLocations(); }});
}};

/* ---- Settings ---- */
SAFETY.loadSettings = function() {{
    fetch('/api/safety/types').then(function(r) {{ return r.json(); }}).then(function(data) {{
        var html = '<table class="safety-table">';
        html += '<thead><tr><th style="text-align:left;">Name</th>';
        html += '<th>Code</th><th>Interval</th>';
        html += '<th style="text-align:left;">Standard</th></tr></thead><tbody>';
        (data.types || []).forEach(function(t) {{
            html += '<tr><td>' + t.name + '</td>';
            html += '<td style="text-align:center;"><span style="background:var(--bg-elevated);padding:2px 6px;border-radius:3px;">' + t.code + '</span></td>';
            html += '<td style="text-align:center;">' + t.default_interval_days + ' days</td>';
            html += '<td style="color:var(--text-secondary);">' + (t.regulatory_standard || '') + '</td></tr>';
        }});
        html += '</tbody></table>';
        document.getElementById('safety-settings-types').innerHTML = html;
    }});

    fetch('/api/safety/templates').then(function(r) {{ return r.json(); }}).then(function(data) {{
        var html = '<table class="safety-table">';
        html += '<thead><tr><th style="text-align:left;">Template</th>';
        html += '<th>Tier</th><th>Items</th>';
        html += '<th style="text-align:left;">Reference</th></tr></thead><tbody>';
        (data.templates || []).forEach(function(t) {{
            var items = [];
            try {{ items = JSON.parse(t.checklist_items || '[]'); }} catch(e) {{}}
            html += '<tr><td>' + t.name + '</td>';
            html += '<td style="text-align:center;"><span style="background:var(--bg-elevated);padding:2px 6px;border-radius:3px;">' + t.tier + '</span></td>';
            html += '<td style="text-align:center;">' + items.length + '</td>';
            html += '<td style="color:var(--text-secondary);">' + (t.regulatory_reference || '') + '</td></tr>';
        }});
        html += '</tbody></table>';
        document.getElementById('safety-settings-templates').innerHTML = html;
    }});
}};

/* ---- QR Tools ---- */
SAFETY.showQR = function(assetId) {{
    window.open('/api/safety/assets/' + assetId + '/qr', '_blank');
}};

SAFETY.printAllQR = function() {{
    window.open('/api/safety/qr/print-sheet', '_blank');
}};

SAFETY.downloadQRZip = function() {{
    fetch('/api/safety/assets').then(function(r) {{ return r.json(); }}).then(function(data) {{
        var ids = (data.assets || []).map(function(a) {{ return a.id; }});
        if (ids.length === 0) {{ alert('No assets to generate QR for'); return; }}
        fetch('/api/safety/qr/generate-batch', {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{asset_ids: ids}})}})
            .then(function(r) {{ return r.blob(); }})
            .then(function(blob) {{
                var a = document.createElement('a');
                a.href = URL.createObjectURL(blob);
                a.download = 'safety-qr-codes.zip';
                a.click();
            }});
    }});
}};
</script>
</div>
"""
