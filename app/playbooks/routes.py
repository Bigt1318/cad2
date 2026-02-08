"""
FORD-CAD Playbooks — API Routes
"""
import json
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .models import (
    init_playbook_schema, get_playbooks, get_playbook,
    create_playbook, update_playbook, delete_playbook,
    get_executions,
)
from .engine import execute_playbook_suggestion, dismiss_playbook_suggestion


def register_playbook_routes(app: FastAPI):
    """Register all playbook endpoints."""

    init_playbook_schema()

    @app.get("/api/playbooks")
    async def api_get_playbooks(request: Request):
        playbooks = get_playbooks()
        return {"ok": True, "playbooks": playbooks}

    @app.post("/api/playbooks")
    async def api_create_playbook(request: Request):
        data = await request.json()
        data["created_by"] = request.session.get("user", "admin")
        pb_id = create_playbook(data)
        return {"ok": True, "playbook_id": pb_id}

    @app.put("/api/playbooks/{pb_id}")
    async def api_update_playbook(pb_id: int, request: Request):
        data = await request.json()
        update_playbook(pb_id, data)
        return {"ok": True}

    @app.delete("/api/playbooks/{pb_id}")
    async def api_delete_playbook(pb_id: int, request: Request):
        delete_playbook(pb_id)
        return {"ok": True}

    @app.get("/api/playbooks/executions")
    async def api_get_executions(request: Request):
        pb_id = request.query_params.get("playbook_id")
        inc_id = request.query_params.get("incident_id")
        execs = get_executions(
            playbook_id=int(pb_id) if pb_id else None,
            incident_id=int(inc_id) if inc_id else None,
        )
        return {"ok": True, "executions": execs}

    @app.post("/api/playbooks/executions/{exec_id}/accept")
    async def api_accept_suggestion(exec_id: int, request: Request):
        user = request.session.get("user", "Dispatcher")
        ok = execute_playbook_suggestion(exec_id, user)
        return {"ok": ok}

    @app.post("/api/playbooks/executions/{exec_id}/dismiss")
    async def api_dismiss_suggestion(exec_id: int, request: Request):
        user = request.session.get("user", "Dispatcher")
        ok = dismiss_playbook_suggestion(exec_id, user)
        return {"ok": ok}

    @app.get("/modals/playbooks", response_class=HTMLResponse)
    async def modal_playbooks(request: Request):
        playbooks = get_playbooks()
        execs = get_executions(limit=20)
        return _render_playbook_modal(playbooks, execs)


def _render_playbook_modal(playbooks, executions) -> str:
    """Render the admin playbook builder modal."""
    pb_rows = ""
    for pb in playbooks:
        enabled_badge = '<span style="color:#48bb78;">ON</span>' if pb.get("enabled") else '<span style="color:#e53e3e;">OFF</span>'
        mode_color = "#48bb78" if pb.get("execution_mode") == "auto" else "#63b3ed"
        mode_label = pb.get("execution_mode", "suggest").upper()
        pb_rows += f"""<tr>
            <td style="padding:6px 8px;">{pb['id']}</td>
            <td style="padding:6px 8px;">{pb['name']}</td>
            <td style="padding:6px 8px;"><span style="background:#2d3748;padding:2px 6px;border-radius:3px;font-size:11px;">{pb['trigger_type']}</span></td>
            <td style="padding:6px 8px;"><span style="color:{mode_color};font-size:11px;font-weight:600;">{mode_label}</span></td>
            <td style="padding:6px 8px;text-align:center;">{enabled_badge}</td>
            <td style="padding:6px 8px;">
                <button onclick="PLAYBOOKS.toggle({pb['id']}, {1 if not pb.get('enabled') else 0})"
                        style="background:#4a5568;color:#e2e8f0;border:none;padding:3px 8px;border-radius:3px;cursor:pointer;font-size:11px;">
                    {'Enable' if not pb.get('enabled') else 'Disable'}
                </button>
                <button onclick="PLAYBOOKS.del({pb['id']})"
                        style="background:#742a2a;color:#feb2b2;border:none;padding:3px 8px;border-radius:3px;cursor:pointer;font-size:11px;margin-left:4px;">
                    Del
                </button>
            </td>
        </tr>"""

    exec_rows = ""
    if not executions:
        exec_rows = '<tr><td colspan="6" style="text-align:center;color:#888;padding:16px;">No executions yet</td></tr>'
    else:
        for ex in executions:
            result_color = {"executed": "#48bb78", "suggested": "#63b3ed", "dismissed": "#a0aec0", "error": "#e53e3e"}.get(ex.get("result",""), "#888")
            exec_rows += f"""<tr>
                <td style="padding:4px 8px;font-size:11px;">{ex.get('timestamp','')[-8:]}</td>
                <td style="padding:4px 8px;font-size:11px;">{ex.get('playbook_name','')}</td>
                <td style="padding:4px 8px;font-size:11px;">{ex.get('incident_id','') or ''}</td>
                <td style="padding:4px 8px;font-size:11px;color:{result_color};font-weight:600;">{ex.get('result','')}</td>
                <td style="padding:4px 8px;font-size:11px;">{ex.get('executed_by','')}</td>
                <td style="padding:4px 8px;font-size:11px;">{ex.get('details','')[:60]}</td>
            </tr>"""

    return f"""
<div style="font-family:'Segoe UI',system-ui,sans-serif;color:#e2e8f0;max-height:80vh;display:flex;flex-direction:column;">
    <div style="padding:12px 16px;border-bottom:1px solid #2d3748;">
        <h3 style="margin:0;font-size:16px;color:#9f7aea;">Playbooks (Workflow Automation)</h3>
        <p style="margin:4px 0 0;font-size:12px;color:#888;">Trigger-condition-action rules for automated workflows</p>
    </div>

    <!-- Playbooks -->
    <div style="padding:8px 16px;">
        <h4 style="margin:0 0 6px;font-size:13px;color:#9f7aea;">Active Playbooks</h4>
        <table style="width:100%;border-collapse:collapse;">
            <thead><tr style="background:#1a202c;">
                <th style="padding:4px 8px;text-align:left;font-size:11px;color:#a0aec0;width:30px;">ID</th>
                <th style="padding:4px 8px;text-align:left;font-size:11px;color:#a0aec0;">Name</th>
                <th style="padding:4px 8px;text-align:left;font-size:11px;color:#a0aec0;">Trigger</th>
                <th style="padding:4px 8px;text-align:left;font-size:11px;color:#a0aec0;">Mode</th>
                <th style="padding:4px 8px;text-align:center;font-size:11px;color:#a0aec0;width:40px;">Status</th>
                <th style="padding:4px 8px;width:130px;"></th>
            </tr></thead>
            <tbody>{pb_rows}</tbody>
        </table>
    </div>

    <!-- Recent Executions -->
    <div style="padding:8px 16px;flex:1;overflow-y:auto;">
        <h4 style="margin:0 0 6px;font-size:13px;color:#a0aec0;">Recent Executions</h4>
        <table style="width:100%;border-collapse:collapse;">
            <thead><tr style="background:#1a202c;">
                <th style="padding:4px 8px;text-align:left;font-size:11px;color:#a0aec0;width:70px;">Time</th>
                <th style="padding:4px 8px;text-align:left;font-size:11px;color:#a0aec0;">Playbook</th>
                <th style="padding:4px 8px;text-align:left;font-size:11px;color:#a0aec0;width:50px;">Inc</th>
                <th style="padding:4px 8px;text-align:left;font-size:11px;color:#a0aec0;width:70px;">Result</th>
                <th style="padding:4px 8px;text-align:left;font-size:11px;color:#a0aec0;width:70px;">By</th>
                <th style="padding:4px 8px;text-align:left;font-size:11px;color:#a0aec0;">Details</th>
            </tr></thead>
            <tbody>{exec_rows}</tbody>
        </table>
    </div>
</div>

<script>
window.PLAYBOOKS = window.PLAYBOOKS || {{}};
PLAYBOOKS.toggle = function(id, enabled) {{
    fetch('/api/playbooks/' + id, {{
        method: 'PUT',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{enabled: enabled}})
    }}).then(function() {{ CAD_MODAL.open('/modals/playbooks'); }});
}};
PLAYBOOKS.del = function(id) {{
    if (!confirm('Delete this playbook?')) return;
    fetch('/api/playbooks/' + id, {{method: 'DELETE'}})
        .then(function() {{ CAD_MODAL.open('/modals/playbooks'); }});
}};
</script>
"""
