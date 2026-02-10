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
            <td style="padding:4px 8px;font-size:12px;">{t["name"]}</td>
            <td style="padding:4px 8px;font-size:12px;text-align:center;">{t["total"]}</td>
            <td style="padding:4px 8px;font-size:12px;text-align:center;color:{bar_color};">{t["pct"]}%</td>
            <td style="padding:4px 8px;font-size:12px;text-align:center;color:#e53e3e;">{t["overdue_count"]}</td>
        </tr>"""

    return f"""
<div class="cad-modal-overlay" onclick="CAD_MODAL.close()"></div>
<div class="cad-modal" role="dialog" aria-modal="true" aria-label="Safety Inspections" style="max-width:1000px;width:92vw;max-height:88vh;overflow:hidden;padding:0;background:#1a1d23 !important;color:#e2e8f0 !important;border-radius:10px;font-family:'Segoe UI',system-ui,sans-serif;display:flex;flex-direction:column;">
<style>
  .cad-modal[aria-label="Safety Inspections"] {{
    --bg-surface: #1a1d23 !important;
    --bg-app: #1a1d23 !important;
    --bg-elevated: #1a202c !important;
    --bg-panel: #2d3748 !important;
    --text-primary: #e2e8f0 !important;
    --text-secondary: #a0aec0 !important;
    --border-default: #2d3748 !important;
    background: #1a1d23 !important;
    color: #e2e8f0 !important;
  }}
  .cad-modal[aria-label="Safety Inspections"] input,
  .cad-modal[aria-label="Safety Inspections"] select,
  .cad-modal[aria-label="Safety Inspections"] textarea {{
    background: #2d3748 !important;
    color: #e2e8f0 !important;
    border-color: #4a5568 !important;
  }}
  .cad-modal[aria-label="Safety Inspections"] label {{
    color: #a0aec0 !important;
  }}
  .cad-modal[aria-label="Safety Inspections"] th {{
    color: #718096 !important;
    background: #1a202c !important;
  }}
  .cad-modal[aria-label="Safety Inspections"] td {{
    color: #e2e8f0 !important;
  }}
  .cad-modal[aria-label="Safety Inspections"] select option {{
    background: #2d3748 !important;
    color: #e2e8f0 !important;
  }}
</style>
<div id="safety-modal" style="color:#e2e8f0;max-height:82vh;display:flex;flex-direction:column;background:#1a1d23;">
    <!-- Header -->
    <div style="padding:12px 16px;border-bottom:1px solid #2d3748;display:flex;justify-content:space-between;align-items:center;">
        <div>
            <h3 style="margin:0;font-size:16px;color:#f6ad55;">Safety Inspections</h3>
            <p style="margin:2px 0 0;font-size:11px;color:#888;">Equipment tracking &amp; compliance</p>
        </div>
    </div>

    <!-- Tab Bar -->
    <div id="safety-tabs" style="display:flex;border-bottom:1px solid #2d3748;background:#1a202c;padding:0 8px;">
        <button class="stab active" onclick="SAFETY.switchTab('dashboard')" data-tab="dashboard" style="padding:8px 14px;border:none;background:none;color:#f6ad55;font-size:12px;cursor:pointer;border-bottom:2px solid #f6ad55;">Dashboard</button>
        <button class="stab" onclick="SAFETY.switchTab('assets')" data-tab="assets" style="padding:8px 14px;border:none;background:none;color:#a0aec0;font-size:12px;cursor:pointer;border-bottom:2px solid transparent;">Assets</button>
        <button class="stab" onclick="SAFETY.switchTab('inspections')" data-tab="inspections" style="padding:8px 14px;border:none;background:none;color:#a0aec0;font-size:12px;cursor:pointer;border-bottom:2px solid transparent;">Inspections</button>
        <button class="stab" onclick="SAFETY.switchTab('deficiencies')" data-tab="deficiencies" style="padding:8px 14px;border:none;background:none;color:#a0aec0;font-size:12px;cursor:pointer;border-bottom:2px solid transparent;">Deficiencies</button>
        <button class="stab" onclick="SAFETY.switchTab('scan')" data-tab="scan" style="padding:8px 14px;border:none;background:none;color:#a0aec0;font-size:12px;cursor:pointer;border-bottom:2px solid transparent;">Scan</button>
        <button class="stab" onclick="SAFETY.switchTab('locations')" data-tab="locations" style="padding:8px 14px;border:none;background:none;color:#a0aec0;font-size:12px;cursor:pointer;border-bottom:2px solid transparent;">Locations</button>
        <button class="stab" onclick="SAFETY.switchTab('settings')" data-tab="settings" style="padding:8px 14px;border:none;background:none;color:#a0aec0;font-size:12px;cursor:pointer;border-bottom:2px solid transparent;">Settings</button>
    </div>

    <!-- Tab Content -->
    <div style="flex:1;overflow-y:auto;padding:12px 16px;">

    <!-- ========== DASHBOARD TAB ========== -->
    <div id="safety-tab-dashboard" class="safety-panel">
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:16px;">
            <div style="background:#2d3748;border-radius:6px;padding:12px;text-align:center;">
                <div style="font-size:24px;font-weight:bold;color:#63b3ed;">{stats["total_assets"]}</div>
                <div style="font-size:11px;color:#a0aec0;">Total Assets</div>
            </div>
            <div style="background:#2d3748;border-radius:6px;padding:12px;text-align:center;">
                <div style="font-size:24px;font-weight:bold;color:#48bb78;">{stats["compliant_pct"]}%</div>
                <div style="font-size:11px;color:#a0aec0;">Compliant</div>
            </div>
            <div style="background:#2d3748;border-radius:6px;padding:12px;text-align:center;">
                <div style="font-size:24px;font-weight:bold;color:{overdue_color};">{stats["overdue"]}</div>
                <div style="font-size:11px;color:#a0aec0;">Overdue</div>
            </div>
            <div style="background:#2d3748;border-radius:6px;padding:12px;text-align:center;">
                <div style="font-size:24px;font-weight:bold;color:{def_color};">{stats["open_deficiencies"]}</div>
                <div style="font-size:11px;color:#a0aec0;">Open Deficiencies</div>
            </div>
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div>
                <h4 style="margin:0 0 8px;font-size:13px;color:#a0aec0;">Compliance by Type</h4>
                <table style="width:100%;border-collapse:collapse;">
                    <thead><tr style="background:#1a202c;">
                        <th style="padding:4px 8px;text-align:left;font-size:11px;color:#718096;">Type</th>
                        <th style="padding:4px 8px;text-align:center;font-size:11px;color:#718096;">Total</th>
                        <th style="padding:4px 8px;text-align:center;font-size:11px;color:#718096;">Compliant</th>
                        <th style="padding:4px 8px;text-align:center;font-size:11px;color:#718096;">Overdue</th>
                    </tr></thead>
                    <tbody>{by_type_rows}</tbody>
                </table>
            </div>
            <div>
                <h4 style="margin:0 0 8px;font-size:13px;color:#a0aec0;">Recent Activity</h4>
                <div id="safety-recent-activity" style="font-size:12px;color:#888;">
                    <div style="padding:8px;text-align:center;">{stats["inspections_30d"]} inspections in last 30 days</div>
                </div>
            </div>
        </div>
    </div>

    <!-- ========== ASSETS TAB ========== -->
    <div id="safety-tab-assets" class="safety-panel" style="display:none;">
        <div style="display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap;align-items:center;">
            <select id="safety-filter-type" onchange="SAFETY.loadAssets()" style="background:#2d3748;color:#e2e8f0;border:1px solid #4a5568;padding:4px 8px;border-radius:4px;font-size:12px;">
                <option value="">All Types</option>
                {types_options}
            </select>
            <select id="safety-filter-location" onchange="SAFETY.loadAssets()" style="background:#2d3748;color:#e2e8f0;border:1px solid #4a5568;padding:4px 8px;border-radius:4px;font-size:12px;">
                <option value="">All Locations</option>
                {loc_options}
            </select>
            <select id="safety-filter-status" onchange="SAFETY.loadAssets()" style="background:#2d3748;color:#e2e8f0;border:1px solid #4a5568;padding:4px 8px;border-radius:4px;font-size:12px;">
                <option value="">All Status</option>
                <option value="active">Active</option>
                <option value="deficient">Deficient</option>
                <option value="out_of_service">Out of Service</option>
            </select>
            <input id="safety-search" placeholder="Search tag/serial..." onkeyup="SAFETY.debounceSearch()"
                   style="background:#2d3748;color:#e2e8f0;border:1px solid #4a5568;padding:4px 8px;border-radius:4px;font-size:12px;width:160px;" />
            <label style="font-size:11px;color:#a0aec0;display:flex;align-items:center;gap:4px;">
                <input type="checkbox" id="safety-filter-overdue" onchange="SAFETY.loadAssets()"> Overdue Only
            </label>
            <div style="flex:1;"></div>
            <button onclick="SAFETY.showAddAsset()" style="background:#2b6cb0;color:#fff;border:none;padding:5px 12px;border-radius:4px;font-size:12px;cursor:pointer;">+ Add Asset</button>
        </div>
        <div id="safety-assets-table" style="max-height:50vh;overflow-y:auto;">
            <div style="text-align:center;color:#888;padding:20px;">Loading assets...</div>
        </div>
    </div>

    <!-- ========== INSPECTIONS TAB ========== -->
    <div id="safety-tab-inspections" class="safety-panel" style="display:none;">
        <div style="display:flex;gap:8px;margin-bottom:10px;">
            <button id="safety-insp-pending-btn" onclick="SAFETY.loadPending()" style="background:#2b6cb0;color:#fff;border:none;padding:5px 12px;border-radius:4px;font-size:12px;cursor:pointer;">Pending</button>
            <button id="safety-insp-history-btn" onclick="SAFETY.loadHistory()" style="background:#4a5568;color:#e2e8f0;border:none;padding:5px 12px;border-radius:4px;font-size:12px;cursor:pointer;">History</button>
        </div>
        <div id="safety-inspections-content" style="max-height:55vh;overflow-y:auto;">
            <div style="text-align:center;color:#888;padding:20px;">Select Pending or History</div>
        </div>
    </div>

    <!-- ========== DEFICIENCIES TAB ========== -->
    <div id="safety-tab-deficiencies" class="safety-panel" style="display:none;">
        <div style="display:flex;gap:8px;margin-bottom:10px;">
            <select id="safety-def-status" onchange="SAFETY.loadDeficiencies()" style="background:#2d3748;color:#e2e8f0;border:1px solid #4a5568;padding:4px 8px;border-radius:4px;font-size:12px;">
                <option value="">All Status</option>
                <option value="open" selected>Open</option>
                <option value="in_progress">In Progress</option>
                <option value="resolved">Resolved</option>
                <option value="deferred">Deferred</option>
            </select>
            <select id="safety-def-severity" onchange="SAFETY.loadDeficiencies()" style="background:#2d3748;color:#e2e8f0;border:1px solid #4a5568;padding:4px 8px;border-radius:4px;font-size:12px;">
                <option value="">All Severity</option>
                <option value="critical">Critical</option>
                <option value="major">Major</option>
                <option value="minor">Minor</option>
            </select>
        </div>
        <div id="safety-deficiencies-content" style="max-height:55vh;overflow-y:auto;">
            <div style="text-align:center;color:#888;padding:20px;">Loading...</div>
        </div>
    </div>

    <!-- ========== SCAN TAB ========== -->
    <div id="safety-tab-scan" class="safety-panel" style="display:none;">
        <div style="text-align:center;padding:12px;">
            <div id="safety-scanner-container" style="position:relative;width:320px;height:240px;margin:0 auto 12px;background:#000;border-radius:8px;overflow:hidden;">
                <video id="safety-scanner-video" autoplay playsinline style="width:100%;height:100%;object-fit:cover;"></video>
                <div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:200px;height:200px;border:2px solid #f6ad55;border-radius:8px;pointer-events:none;"></div>
            </div>
            <button onclick="SAFETY.startScanner()" style="background:#2b6cb0;color:#fff;border:none;padding:6px 16px;border-radius:4px;font-size:12px;cursor:pointer;margin-right:8px;">Start Camera</button>
            <button onclick="SAFETY.stopScanner()" style="background:#4a5568;color:#e2e8f0;border:none;padding:6px 16px;border-radius:4px;font-size:12px;cursor:pointer;">Stop</button>
            <div style="margin-top:12px;">
                <span style="font-size:12px;color:#a0aec0;">Or enter asset tag manually:</span>
                <div style="display:flex;gap:6px;justify-content:center;margin-top:6px;">
                    <input id="safety-manual-tag" placeholder="FE-001 or QR UUID" style="background:#2d3748;color:#e2e8f0;border:1px solid #4a5568;padding:5px 10px;border-radius:4px;font-size:12px;width:200px;" />
                    <button onclick="SAFETY.manualLookup()" style="background:#2b6cb0;color:#fff;border:none;padding:5px 12px;border-radius:4px;font-size:12px;cursor:pointer;">Lookup</button>
                </div>
            </div>
            <div id="safety-scan-result" style="margin-top:16px;"></div>
        </div>
    </div>

    <!-- ========== LOCATIONS TAB ========== -->
    <div id="safety-tab-locations" class="safety-panel" style="display:none;">
        <div style="display:flex;gap:8px;margin-bottom:10px;align-items:center;">
            <h4 style="margin:0;font-size:13px;color:#a0aec0;flex:1;">Locations</h4>
            <button onclick="SAFETY.showAddLocation()" style="background:#2b6cb0;color:#fff;border:none;padding:5px 12px;border-radius:4px;font-size:12px;cursor:pointer;">+ Add Location</button>
        </div>
        <div id="safety-locations-content" style="max-height:55vh;overflow-y:auto;">
            <div style="text-align:center;color:#888;padding:20px;">Loading...</div>
        </div>
    </div>

    <!-- ========== SETTINGS TAB ========== -->
    <div id="safety-tab-settings" class="safety-panel" style="display:none;">
        <h4 style="margin:0 0 12px;font-size:13px;color:#a0aec0;">Asset Types</h4>
        <div id="safety-settings-types" style="margin-bottom:16px;">Loading...</div>

        <h4 style="margin:0 0 12px;font-size:13px;color:#a0aec0;">Inspection Templates</h4>
        <div id="safety-settings-templates">Loading...</div>

        <h4 style="margin:16px 0 12px;font-size:13px;color:#a0aec0;">QR Batch Tools</h4>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
            <button onclick="SAFETY.printAllQR()" style="background:#4a5568;color:#e2e8f0;border:none;padding:6px 14px;border-radius:4px;font-size:12px;cursor:pointer;">Print All QR Labels</button>
            <button onclick="SAFETY.downloadQRZip()" style="background:#4a5568;color:#e2e8f0;border:none;padding:6px 14px;border-radius:4px;font-size:12px;cursor:pointer;">Download QR ZIP</button>
        </div>
    </div>

    </div><!-- end tab content -->
</div>

<script>
window.SAFETY = window.SAFETY || {{}};

/* ---- Tab switching ---- */
SAFETY.switchTab = function(tab) {{
    document.querySelectorAll('.safety-panel').forEach(function(el) {{ el.style.display = 'none'; }});
    document.querySelectorAll('.stab').forEach(function(el) {{
        el.style.color = '#a0aec0';
        el.style.borderBottom = '2px solid transparent';
    }});
    var panel = document.getElementById('safety-tab-' + tab);
    if (panel) panel.style.display = 'block';
    var btn = document.querySelector('.stab[data-tab="' + tab + '"]');
    if (btn) {{ btn.style.color = '#f6ad55'; btn.style.borderBottom = '2px solid #f6ad55'; }}

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
        var html = '<table style="width:100%;border-collapse:collapse;">';
        html += '<thead><tr style="background:#1a202c;">';
        html += '<th style="padding:5px 8px;text-align:left;font-size:11px;color:#718096;">Tag</th>';
        html += '<th style="padding:5px 8px;text-align:left;font-size:11px;color:#718096;">Type</th>';
        html += '<th style="padding:5px 8px;text-align:left;font-size:11px;color:#718096;">Location</th>';
        html += '<th style="padding:5px 8px;text-align:center;font-size:11px;color:#718096;">Status</th>';
        html += '<th style="padding:5px 8px;text-align:center;font-size:11px;color:#718096;">Last Inspected</th>';
        html += '<th style="padding:5px 8px;text-align:center;font-size:11px;color:#718096;">Next Due</th>';
        html += '<th style="padding:5px 8px;width:100px;"></th>';
        html += '</tr></thead><tbody>';
        if (assets.length === 0) {{
            html += '<tr><td colspan="7" style="text-align:center;padding:20px;color:#888;">No assets found</td></tr>';
        }}
        assets.forEach(function(a) {{
            var rowColor = '';
            if (a.next_inspection_due && a.next_inspection_due < today) rowColor = 'border-left:3px solid #e53e3e;';
            else if (a.next_inspection_due && a.next_inspection_due <= soon) rowColor = 'border-left:3px solid #d69e2e;';
            else rowColor = 'border-left:3px solid #48bb78;';

            var statusBadge = '<span style="font-size:10px;padding:2px 6px;border-radius:3px;';
            if (a.status === 'active') statusBadge += 'background:#22543d;color:#48bb78;">Active</span>';
            else if (a.status === 'deficient') statusBadge += 'background:#744210;color:#ecc94b;">Deficient</span>';
            else statusBadge += 'background:#742a2a;color:#feb2b2;">OOS</span>';

            html += '<tr style="' + rowColor + 'cursor:pointer;" onclick="SAFETY.viewAsset(' + a.id + ')">';
            html += '<td style="padding:5px 8px;font-size:12px;font-weight:bold;">' + (a.asset_tag || '') + '</td>';
            html += '<td style="padding:5px 8px;font-size:12px;">' + (a.type_name || '') + '</td>';
            html += '<td style="padding:5px 8px;font-size:12px;">' + (a.location_name || '') + '</td>';
            html += '<td style="padding:5px 8px;text-align:center;">' + statusBadge + '</td>';
            html += '<td style="padding:5px 8px;text-align:center;font-size:11px;color:#a0aec0;">' + (a.last_inspection_date || 'Never') + '</td>';
            html += '<td style="padding:5px 8px;text-align:center;font-size:11px;">' + (a.next_inspection_due || '—') + '</td>';
            html += '<td style="padding:5px 8px;text-align:center;">';
            html += '<button onclick="event.stopPropagation();SAFETY.inspectAsset(' + a.id + ')" style="background:#2b6cb0;color:#fff;border:none;padding:2px 8px;border-radius:3px;font-size:10px;cursor:pointer;">Inspect</button> ';
            html += '<button onclick="event.stopPropagation();SAFETY.showQR(' + a.id + ')" style="background:#4a5568;color:#e2e8f0;border:none;padding:2px 8px;border-radius:3px;font-size:10px;cursor:pointer;">QR</button>';
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
            histRows += '<tr><td style="padding:3px 6px;font-size:11px;">' + (h.inspection_date || '') + '</td>';
            histRows += '<td style="padding:3px 6px;font-size:11px;">' + (h.template_name || '') + '</td>';
            histRows += '<td style="padding:3px 6px;font-size:11px;color:' + rColor + ';">' + (h.result || '') + '</td>';
            histRows += '<td style="padding:3px 6px;font-size:11px;">' + (h.inspector_name || h.inspector_unit_id || '') + '</td></tr>';
        }});

        var defRows = '';
        defs.forEach(function(d) {{
            var sColor = d.severity === 'critical' ? '#e53e3e' : (d.severity === 'major' ? '#ecc94b' : '#a0aec0');
            defRows += '<tr><td style="padding:3px 6px;font-size:11px;color:' + sColor + ';">' + d.severity + '</td>';
            defRows += '<td style="padding:3px 6px;font-size:11px;">' + (d.description || '') + '</td>';
            defRows += '<td style="padding:3px 6px;font-size:11px;">' + d.status + '</td></tr>';
        }});

        var html = '<div style="background:#1a202c;border-radius:6px;padding:12px;margin-bottom:12px;">';
        html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">';
        html += '<h4 style="margin:0;color:#f6ad55;">' + (a.asset_tag || '') + '</h4>';
        html += '<button onclick="SAFETY.loadAssets()" style="background:#4a5568;color:#e2e8f0;border:none;padding:3px 10px;border-radius:3px;font-size:11px;cursor:pointer;">Back</button>';
        html += '</div>';
        html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:12px;">';
        html += '<div><span style="color:#718096;">Type:</span> ' + (a.type_name || '') + '</div>';
        html += '<div><span style="color:#718096;">Location:</span> ' + (a.location_name || '') + '</div>';
        html += '<div><span style="color:#718096;">Serial:</span> ' + (a.serial_number || '—') + '</div>';
        html += '<div><span style="color:#718096;">Manufacturer:</span> ' + (a.manufacturer || '—') + '</div>';
        html += '<div><span style="color:#718096;">Install Date:</span> ' + (a.install_date || '—') + '</div>';
        html += '<div><span style="color:#718096;">Expiration:</span> ' + (a.expiration_date || '—') + '</div>';
        html += '<div><span style="color:#718096;">Status:</span> ' + (a.status || '') + '</div>';
        html += '<div><span style="color:#718096;">Next Due:</span> ' + (a.next_inspection_due || '—') + '</div>';
        html += '</div>';
        if (a.photo_url) html += '<img src="' + a.photo_url + '" style="max-width:120px;margin-top:8px;border-radius:4px;" />';
        html += '<div style="margin-top:8px;"><button onclick="SAFETY.inspectAsset(' + a.id + ')" style="background:#2b6cb0;color:#fff;border:none;padding:4px 14px;border-radius:4px;font-size:12px;cursor:pointer;">Start Inspection</button></div>';
        html += '</div>';

        if (hist.length > 0) {{
            html += '<h5 style="margin:8px 0 4px;font-size:12px;color:#a0aec0;">Inspection History</h5>';
            html += '<table style="width:100%;border-collapse:collapse;"><thead><tr style="background:#1a202c;">';
            html += '<th style="padding:3px 6px;text-align:left;font-size:10px;color:#718096;">Date</th>';
            html += '<th style="padding:3px 6px;text-align:left;font-size:10px;color:#718096;">Template</th>';
            html += '<th style="padding:3px 6px;text-align:left;font-size:10px;color:#718096;">Result</th>';
            html += '<th style="padding:3px 6px;text-align:left;font-size:10px;color:#718096;">Inspector</th>';
            html += '</tr></thead><tbody>' + histRows + '</tbody></table>';
        }}

        if (defs.length > 0) {{
            html += '<h5 style="margin:8px 0 4px;font-size:12px;color:#a0aec0;">Deficiencies</h5>';
            html += '<table style="width:100%;border-collapse:collapse;"><thead><tr style="background:#1a202c;">';
            html += '<th style="padding:3px 6px;text-align:left;font-size:10px;color:#718096;">Severity</th>';
            html += '<th style="padding:3px 6px;text-align:left;font-size:10px;color:#718096;">Description</th>';
            html += '<th style="padding:3px 6px;text-align:left;font-size:10px;color:#718096;">Status</th>';
            html += '</tr></thead><tbody>' + defRows + '</tbody></table>';
        }}

        document.getElementById('safety-assets-table').innerHTML = html;
    }});
}};

/* ---- Add Asset Form ---- */
SAFETY.showAddAsset = function() {{
    var html = '<div style="background:#1a202c;border-radius:6px;padding:12px;">';
    html += '<h4 style="margin:0 0 10px;font-size:13px;color:#f6ad55;">Add New Asset</h4>';
    html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">';
    html += '<div><label style="font-size:11px;color:#a0aec0;">Type</label><select id="sa-type" style="width:100%;background:#2d3748;color:#e2e8f0;border:1px solid #4a5568;padding:4px;border-radius:4px;font-size:12px;">{types_options}</select></div>';
    html += '<div><label style="font-size:11px;color:#a0aec0;">Location</label><select id="sa-loc" style="width:100%;background:#2d3748;color:#e2e8f0;border:1px solid #4a5568;padding:4px;border-radius:4px;font-size:12px;"><option value="">None</option>{loc_options}</select></div>';
    html += '<div><label style="font-size:11px;color:#a0aec0;">Asset Tag (auto if blank)</label><input id="sa-tag" style="width:100%;background:#2d3748;color:#e2e8f0;border:1px solid #4a5568;padding:4px;border-radius:4px;font-size:12px;" /></div>';
    html += '<div><label style="font-size:11px;color:#a0aec0;">Serial Number</label><input id="sa-serial" style="width:100%;background:#2d3748;color:#e2e8f0;border:1px solid #4a5568;padding:4px;border-radius:4px;font-size:12px;" /></div>';
    html += '<div><label style="font-size:11px;color:#a0aec0;">Manufacturer</label><input id="sa-mfg" style="width:100%;background:#2d3748;color:#e2e8f0;border:1px solid #4a5568;padding:4px;border-radius:4px;font-size:12px;" /></div>';
    html += '<div><label style="font-size:11px;color:#a0aec0;">Model</label><input id="sa-model" style="width:100%;background:#2d3748;color:#e2e8f0;border:1px solid #4a5568;padding:4px;border-radius:4px;font-size:12px;" /></div>';
    html += '<div><label style="font-size:11px;color:#a0aec0;">Install Date</label><input id="sa-install" type="date" style="width:100%;background:#2d3748;color:#e2e8f0;border:1px solid #4a5568;padding:4px;border-radius:4px;font-size:12px;" /></div>';
    html += '<div><label style="font-size:11px;color:#a0aec0;">Expiration Date</label><input id="sa-expire" type="date" style="width:100%;background:#2d3748;color:#e2e8f0;border:1px solid #4a5568;padding:4px;border-radius:4px;font-size:12px;" /></div>';
    html += '</div>';
    html += '<div style="margin-top:8px;"><label style="font-size:11px;color:#a0aec0;">Notes</label><textarea id="sa-notes" rows="2" style="width:100%;background:#2d3748;color:#e2e8f0;border:1px solid #4a5568;padding:4px;border-radius:4px;font-size:12px;resize:vertical;"></textarea></div>';
    html += '<div style="margin-top:10px;display:flex;gap:8px;">';
    html += '<button onclick="SAFETY.saveAsset()" style="background:#2b6cb0;color:#fff;border:none;padding:5px 16px;border-radius:4px;font-size:12px;cursor:pointer;">Save</button>';
    html += '<button onclick="SAFETY.loadAssets()" style="background:#4a5568;color:#e2e8f0;border:none;padding:5px 16px;border-radius:4px;font-size:12px;cursor:pointer;">Cancel</button>';
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

    var tplSelect = '<select id="si-template" onchange="SAFETY._changeTemplate(' + asset.id + ')" style="background:#2d3748;color:#e2e8f0;border:1px solid #4a5568;padding:4px;border-radius:4px;font-size:12px;">';
    templates.forEach(function(t) {{
        tplSelect += '<option value="' + t.id + '"' + (t.id === selectedTemplate.id ? ' selected' : '') + '>' + t.name + ' (' + t.tier + ')</option>';
    }});
    tplSelect += '</select>';

    var checklistHtml = '';
    items.forEach(function(item, idx) {{
        if (item.type === 'pass_fail') {{
            checklistHtml += '<div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid #2d3748;">';
            checklistHtml += '<span style="flex:1;font-size:12px;">' + item.label + (item.required ? ' *' : '') + '</span>';
            checklistHtml += '<select data-field="' + item.field + '" class="si-response" style="background:#2d3748;color:#e2e8f0;border:1px solid #4a5568;padding:3px 6px;border-radius:3px;font-size:11px;width:80px;">';
            checklistHtml += '<option value="">—</option><option value="pass">Pass</option><option value="fail">Fail</option>';
            checklistHtml += '</select></div>';
        }} else if (item.type === 'date') {{
            checklistHtml += '<div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid #2d3748;">';
            checklistHtml += '<span style="flex:1;font-size:12px;">' + item.label + '</span>';
            checklistHtml += '<input data-field="' + item.field + '" class="si-response" type="date" style="background:#2d3748;color:#e2e8f0;border:1px solid #4a5568;padding:3px 6px;border-radius:3px;font-size:11px;width:130px;" />';
            checklistHtml += '</div>';
        }}
    }});

    var html = '<div style="background:#1a202c;border-radius:6px;padding:12px;">';
    html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">';
    html += '<h4 style="margin:0;color:#f6ad55;">Inspect: ' + (asset.asset_tag || '') + '</h4>';
    html += '<button onclick="SAFETY.loadAssets()" style="background:#4a5568;color:#e2e8f0;border:none;padding:3px 10px;border-radius:3px;font-size:11px;cursor:pointer;">Cancel</button>';
    html += '</div>';
    html += '<div style="font-size:11px;color:#a0aec0;margin-bottom:8px;">' + (asset.type_name || '') + ' — ' + (asset.location_name || '') + '</div>';
    html += '<div style="margin-bottom:10px;">' + tplSelect + '</div>';
    html += '<div style="max-height:300px;overflow-y:auto;">' + checklistHtml + '</div>';
    html += '<div style="margin-top:10px;"><label style="font-size:11px;color:#a0aec0;">Inspector Name</label><input id="si-inspector" value="" style="width:100%;background:#2d3748;color:#e2e8f0;border:1px solid #4a5568;padding:4px;border-radius:4px;font-size:12px;" /></div>';
    html += '<div style="margin-top:6px;"><label style="font-size:11px;color:#a0aec0;">Notes</label><textarea id="si-notes" rows="2" style="width:100%;background:#2d3748;color:#e2e8f0;border:1px solid #4a5568;padding:4px;border-radius:4px;font-size:12px;resize:vertical;"></textarea></div>';
    html += '<div style="margin-top:10px;">';
    html += '<button onclick="SAFETY.submitInspection(' + asset.id + ')" style="background:#48bb78;color:#fff;border:none;padding:6px 20px;border-radius:4px;font-size:12px;cursor:pointer;font-weight:bold;">Submit Inspection</button>';
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
    document.getElementById('safety-insp-pending-btn').style.background = '#2b6cb0';
    document.getElementById('safety-insp-history-btn').style.background = '#4a5568';
    fetch('/api/safety/inspections/pending?days=30').then(function(r) {{ return r.json(); }}).then(function(data) {{
        if (!data.ok) return;
        var items = data.pending || [];
        var today = new Date().toISOString().slice(0, 10);
        var html = '<table style="width:100%;border-collapse:collapse;">';
        html += '<thead><tr style="background:#1a202c;">';
        html += '<th style="padding:4px 8px;text-align:left;font-size:11px;color:#718096;">Asset</th>';
        html += '<th style="padding:4px 8px;text-align:left;font-size:11px;color:#718096;">Type</th>';
        html += '<th style="padding:4px 8px;text-align:left;font-size:11px;color:#718096;">Location</th>';
        html += '<th style="padding:4px 8px;text-align:center;font-size:11px;color:#718096;">Due Date</th>';
        html += '<th style="padding:4px 8px;width:80px;"></th>';
        html += '</tr></thead><tbody>';
        if (items.length === 0) html += '<tr><td colspan="5" style="text-align:center;padding:16px;color:#888;">No pending inspections</td></tr>';
        items.forEach(function(a) {{
            var overdue = a.next_inspection_due && a.next_inspection_due < today;
            var rowStyle = overdue ? 'border-left:3px solid #e53e3e;background:rgba(229,62,62,0.05);' : 'border-left:3px solid #d69e2e;';
            html += '<tr style="' + rowStyle + '">';
            html += '<td style="padding:4px 8px;font-size:12px;font-weight:bold;">' + (a.asset_tag || '') + '</td>';
            html += '<td style="padding:4px 8px;font-size:12px;">' + (a.type_name || '') + '</td>';
            html += '<td style="padding:4px 8px;font-size:12px;">' + (a.location_name || '') + '</td>';
            html += '<td style="padding:4px 8px;text-align:center;font-size:11px;color:' + (overdue ? '#e53e3e' : '#d69e2e') + ';">' + (a.next_inspection_due || '') + (overdue ? ' OVERDUE' : '') + '</td>';
            html += '<td style="padding:4px 8px;"><button onclick="SAFETY.inspectAsset(' + a.id + ')" style="background:#2b6cb0;color:#fff;border:none;padding:2px 8px;border-radius:3px;font-size:10px;cursor:pointer;">Inspect</button></td>';
            html += '</tr>';
        }});
        html += '</tbody></table>';
        document.getElementById('safety-inspections-content').innerHTML = html;
    }});
}};

SAFETY.loadHistory = function() {{
    document.getElementById('safety-insp-history-btn').style.background = '#2b6cb0';
    document.getElementById('safety-insp-pending-btn').style.background = '#4a5568';
    fetch('/api/safety/inspections').then(function(r) {{ return r.json(); }}).then(function(data) {{
        if (!data.ok) return;
        var items = data.inspections || [];
        var html = '<table style="width:100%;border-collapse:collapse;">';
        html += '<thead><tr style="background:#1a202c;">';
        html += '<th style="padding:4px 8px;text-align:left;font-size:11px;color:#718096;">Date</th>';
        html += '<th style="padding:4px 8px;text-align:left;font-size:11px;color:#718096;">Asset</th>';
        html += '<th style="padding:4px 8px;text-align:left;font-size:11px;color:#718096;">Template</th>';
        html += '<th style="padding:4px 8px;text-align:center;font-size:11px;color:#718096;">Result</th>';
        html += '<th style="padding:4px 8px;text-align:left;font-size:11px;color:#718096;">Inspector</th>';
        html += '</tr></thead><tbody>';
        if (items.length === 0) html += '<tr><td colspan="5" style="text-align:center;padding:16px;color:#888;">No inspection records</td></tr>';
        items.forEach(function(i) {{
            var rColor = i.result === 'pass' ? '#48bb78' : (i.result === 'partial' ? '#ecc94b' : '#e53e3e');
            html += '<tr>';
            html += '<td style="padding:4px 8px;font-size:12px;">' + (i.inspection_date || '') + '</td>';
            html += '<td style="padding:4px 8px;font-size:12px;font-weight:bold;">' + (i.asset_tag || '') + '</td>';
            html += '<td style="padding:4px 8px;font-size:12px;">' + (i.template_name || '') + '</td>';
            html += '<td style="padding:4px 8px;text-align:center;font-size:11px;color:' + rColor + ';font-weight:bold;">' + (i.result || '').toUpperCase() + '</td>';
            html += '<td style="padding:4px 8px;font-size:12px;">' + (i.inspector_name || i.inspector_unit_id || '') + '</td>';
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
        var html = '<table style="width:100%;border-collapse:collapse;">';
        html += '<thead><tr style="background:#1a202c;">';
        html += '<th style="padding:4px 8px;text-align:left;font-size:11px;color:#718096;">Asset</th>';
        html += '<th style="padding:4px 8px;text-align:left;font-size:11px;color:#718096;">Description</th>';
        html += '<th style="padding:4px 8px;text-align:center;font-size:11px;color:#718096;">Severity</th>';
        html += '<th style="padding:4px 8px;text-align:center;font-size:11px;color:#718096;">Status</th>';
        html += '<th style="padding:4px 8px;text-align:left;font-size:11px;color:#718096;">Assigned</th>';
        html += '<th style="padding:4px 8px;width:120px;"></th>';
        html += '</tr></thead><tbody>';
        if (defs.length === 0) html += '<tr><td colspan="6" style="text-align:center;padding:16px;color:#888;">No deficiencies found</td></tr>';
        defs.forEach(function(d) {{
            var sColor = d.severity === 'critical' ? '#e53e3e' : (d.severity === 'major' ? '#ecc94b' : '#a0aec0');
            var stColor = d.status === 'open' ? '#e53e3e' : (d.status === 'in_progress' ? '#ecc94b' : '#48bb78');
            html += '<tr>';
            html += '<td style="padding:4px 8px;font-size:12px;font-weight:bold;">' + (d.asset_tag || '') + '</td>';
            html += '<td style="padding:4px 8px;font-size:12px;">' + (d.description || '') + '</td>';
            html += '<td style="padding:4px 8px;text-align:center;"><span style="font-size:10px;padding:2px 6px;border-radius:3px;color:' + sColor + ';">' + d.severity + '</span></td>';
            html += '<td style="padding:4px 8px;text-align:center;"><span style="font-size:10px;padding:2px 6px;border-radius:3px;color:' + stColor + ';">' + d.status + '</span></td>';
            html += '<td style="padding:4px 8px;font-size:12px;">' + (d.assigned_to || '—') + '</td>';
            html += '<td style="padding:4px 8px;">';
            if (d.status !== 'resolved') {{
                html += '<select onchange="SAFETY.updateDefStatus(' + d.id + ', this.value)" style="background:#2d3748;color:#e2e8f0;border:1px solid #4a5568;padding:2px 4px;border-radius:3px;font-size:10px;">';
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
    document.getElementById('safety-scan-result').innerHTML = '<div style="color:#a0aec0;font-size:12px;">Looking up...</div>';
    fetch('/api/safety/assets/scan/' + encodeURIComponent(qrCode)).then(function(r) {{ return r.json(); }}).then(function(data) {{
        if (!data.ok) {{
            document.getElementById('safety-scan-result').innerHTML = '<div style="color:#e53e3e;font-size:12px;">Asset not found for: ' + qrCode + '</div>';
            return;
        }}
        var a = data.asset;
        var html = '<div style="background:#1a202c;border-radius:6px;padding:12px;text-align:left;">';
        html += '<h4 style="margin:0 0 8px;color:#48bb78;">Found: ' + a.asset_tag + '</h4>';
        html += '<div style="font-size:12px;margin-bottom:4px;"><span style="color:#718096;">Type:</span> ' + (a.type_name || '') + '</div>';
        html += '<div style="font-size:12px;margin-bottom:4px;"><span style="color:#718096;">Location:</span> ' + (a.location_name || '') + '</div>';
        html += '<div style="font-size:12px;margin-bottom:4px;"><span style="color:#718096;">Status:</span> ' + (a.status || '') + '</div>';
        html += '<div style="font-size:12px;margin-bottom:8px;"><span style="color:#718096;">Next Due:</span> ' + (a.next_inspection_due || '—') + '</div>';
        html += '<button onclick="SAFETY.switchTab(\\x27assets\\x27);SAFETY.inspectAsset(' + a.id + ')" style="background:#48bb78;color:#fff;border:none;padding:6px 16px;border-radius:4px;font-size:12px;cursor:pointer;font-weight:bold;">Start Inspection</button> ';
        html += '<button onclick="SAFETY.switchTab(\\x27assets\\x27);SAFETY.viewAsset(' + a.id + ')" style="background:#4a5568;color:#e2e8f0;border:none;padding:6px 16px;border-radius:4px;font-size:12px;cursor:pointer;">View Details</button>';
        html += '</div>';
        document.getElementById('safety-scan-result').innerHTML = html;
    }}).catch(function() {{
        document.getElementById('safety-scan-result').innerHTML = '<div style="color:#e53e3e;font-size:12px;">Lookup failed</div>';
    }});
}};

/* ---- Locations ---- */
SAFETY.loadLocations = function() {{
    fetch('/api/safety/locations').then(function(r) {{ return r.json(); }}).then(function(data) {{
        if (!data.ok) return;
        var locs = data.locations || [];
        // Group by building
        var grouped = {{}};
        locs.forEach(function(l) {{
            var bldg = l.building || 'Unassigned';
            if (!grouped[bldg]) grouped[bldg] = [];
            grouped[bldg].push(l);
        }});
        var html = '';
        Object.keys(grouped).sort().forEach(function(bldg) {{
            html += '<div style="margin-bottom:12px;">';
            html += '<h5 style="margin:0 0 4px;font-size:12px;color:#f6ad55;border-bottom:1px solid #2d3748;padding-bottom:4px;">' + bldg + '</h5>';
            grouped[bldg].forEach(function(l) {{
                html += '<div style="display:flex;align-items:center;gap:8px;padding:4px 8px;">';
                html += '<span style="font-size:12px;flex:1;">' + l.name + '</span>';
                html += '<span style="font-size:11px;color:#718096;">' + (l.floor ? 'Floor ' + l.floor : '') + (l.area ? ' / ' + l.area : '') + '</span>';
                html += '<button onclick="SAFETY.deleteLocation(' + l.id + ')" style="background:none;color:#e53e3e;border:none;font-size:11px;cursor:pointer;">Del</button>';
                html += '</div>';
            }});
            html += '</div>';
        }});
        if (locs.length === 0) html = '<div style="text-align:center;color:#888;padding:16px;">No locations defined yet.</div>';
        document.getElementById('safety-locations-content').innerHTML = html;
    }});
}};

SAFETY.showAddLocation = function() {{
    var html = '<div style="background:#1a202c;border-radius:6px;padding:12px;">';
    html += '<h4 style="margin:0 0 10px;font-size:13px;color:#f6ad55;">Add Location</h4>';
    html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">';
    html += '<div><label style="font-size:11px;color:#a0aec0;">Name</label><input id="sl-name" style="width:100%;background:#2d3748;color:#e2e8f0;border:1px solid #4a5568;padding:4px;border-radius:4px;font-size:12px;" /></div>';
    html += '<div><label style="font-size:11px;color:#a0aec0;">Building</label><input id="sl-bldg" style="width:100%;background:#2d3748;color:#e2e8f0;border:1px solid #4a5568;padding:4px;border-radius:4px;font-size:12px;" /></div>';
    html += '<div><label style="font-size:11px;color:#a0aec0;">Floor</label><input id="sl-floor" style="width:100%;background:#2d3748;color:#e2e8f0;border:1px solid #4a5568;padding:4px;border-radius:4px;font-size:12px;" /></div>';
    html += '<div><label style="font-size:11px;color:#a0aec0;">Area</label><input id="sl-area" style="width:100%;background:#2d3748;color:#e2e8f0;border:1px solid #4a5568;padding:4px;border-radius:4px;font-size:12px;" /></div>';
    html += '</div>';
    html += '<div style="margin-top:8px;"><label style="font-size:11px;color:#a0aec0;">Notes</label><textarea id="sl-notes" rows="2" style="width:100%;background:#2d3748;color:#e2e8f0;border:1px solid #4a5568;padding:4px;border-radius:4px;font-size:12px;resize:vertical;"></textarea></div>';
    html += '<div style="margin-top:10px;display:flex;gap:8px;">';
    html += '<button onclick="SAFETY.saveLocation()" style="background:#2b6cb0;color:#fff;border:none;padding:5px 16px;border-radius:4px;font-size:12px;cursor:pointer;">Save</button>';
    html += '<button onclick="SAFETY.loadLocations()" style="background:#4a5568;color:#e2e8f0;border:none;padding:5px 16px;border-radius:4px;font-size:12px;cursor:pointer;">Cancel</button>';
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
        var html = '<table style="width:100%;border-collapse:collapse;">';
        html += '<thead><tr style="background:#1a202c;"><th style="padding:4px 8px;text-align:left;font-size:11px;color:#718096;">Name</th>';
        html += '<th style="padding:4px 8px;text-align:center;font-size:11px;color:#718096;">Code</th>';
        html += '<th style="padding:4px 8px;text-align:center;font-size:11px;color:#718096;">Interval</th>';
        html += '<th style="padding:4px 8px;text-align:left;font-size:11px;color:#718096;">Standard</th></tr></thead><tbody>';
        (data.types || []).forEach(function(t) {{
            html += '<tr><td style="padding:4px 8px;font-size:12px;">' + t.name + '</td>';
            html += '<td style="padding:4px 8px;text-align:center;font-size:11px;"><span style="background:#2d3748;padding:2px 6px;border-radius:3px;">' + t.code + '</span></td>';
            html += '<td style="padding:4px 8px;text-align:center;font-size:12px;">' + t.default_interval_days + ' days</td>';
            html += '<td style="padding:4px 8px;font-size:12px;color:#a0aec0;">' + (t.regulatory_standard || '') + '</td></tr>';
        }});
        html += '</tbody></table>';
        document.getElementById('safety-settings-types').innerHTML = html;
    }});

    fetch('/api/safety/templates').then(function(r) {{ return r.json(); }}).then(function(data) {{
        var html = '<table style="width:100%;border-collapse:collapse;">';
        html += '<thead><tr style="background:#1a202c;"><th style="padding:4px 8px;text-align:left;font-size:11px;color:#718096;">Template</th>';
        html += '<th style="padding:4px 8px;text-align:center;font-size:11px;color:#718096;">Tier</th>';
        html += '<th style="padding:4px 8px;text-align:center;font-size:11px;color:#718096;">Items</th>';
        html += '<th style="padding:4px 8px;text-align:left;font-size:11px;color:#718096;">Reference</th></tr></thead><tbody>';
        (data.templates || []).forEach(function(t) {{
            var items = [];
            try {{ items = JSON.parse(t.checklist_items || '[]'); }} catch(e) {{}}
            html += '<tr><td style="padding:4px 8px;font-size:12px;">' + t.name + '</td>';
            html += '<td style="padding:4px 8px;text-align:center;font-size:11px;"><span style="background:#2d3748;padding:2px 6px;border-radius:3px;">' + t.tier + '</span></td>';
            html += '<td style="padding:4px 8px;text-align:center;font-size:12px;">' + items.length + '</td>';
            html += '<td style="padding:4px 8px;font-size:12px;color:#a0aec0;">' + (t.regulatory_reference || '') + '</td></tr>';
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
