"""
FORD-CAD Reminders — API Routes
"""
import json
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .models import (
    init_reminder_schema, get_rules, get_rule, create_rule,
    update_rule, delete_rule, get_active_reminders, acknowledge_reminder,
)


def register_reminder_routes(app: FastAPI):
    """Register all reminder endpoints."""

    init_reminder_schema()

    @app.get("/api/reminders/rules")
    async def api_get_rules(request: Request):
        rules = get_rules()
        return {"ok": True, "rules": rules}

    @app.post("/api/reminders/rules")
    async def api_create_rule(request: Request):
        data = await request.json()
        user = request.session.get("user", "admin")
        rule_id = create_rule(
            name=data.get("name", "Untitled"),
            rule_type=data.get("rule_type", "custom"),
            config=data.get("config", {}),
            notify_targets=data.get("notify_targets", []),
            created_by=user,
        )
        return {"ok": True, "rule_id": rule_id}

    @app.put("/api/reminders/rules/{rule_id}")
    async def api_update_rule(rule_id: int, request: Request):
        data = await request.json()
        update_rule(rule_id, **data)
        return {"ok": True}

    @app.delete("/api/reminders/rules/{rule_id}")
    async def api_delete_rule(rule_id: int, request: Request):
        delete_rule(rule_id)
        return {"ok": True}

    @app.get("/api/reminders/active")
    async def api_active_reminders(request: Request):
        reminders = get_active_reminders()
        return {"ok": True, "reminders": reminders}

    @app.post("/api/reminders/{reminder_id}/acknowledge")
    async def api_acknowledge_reminder(reminder_id: int, request: Request):
        user = request.session.get("user", "Dispatcher")
        acknowledge_reminder(reminder_id, user)
        return {"ok": True}

    @app.get("/modals/reminders", response_class=HTMLResponse)
    async def modal_reminders(request: Request):
        rules = get_rules()
        active = get_active_reminders()
        return _render_reminder_modal(rules, active)


def _render_reminder_modal(rules, active) -> str:
    """Render the admin reminder configuration modal."""
    rules_rows = ""
    for r in rules:
        enabled_badge = '<span style="color:#48bb78;">ON</span>' if r.get("enabled") else '<span style="color:#e53e3e;">OFF</span>'
        rules_rows += f"""<tr>
            <td style="padding:6px 8px;">{r['id']}</td>
            <td style="padding:6px 8px;">{r['name']}</td>
            <td style="padding:6px 8px;"><span style="background:#2d3748;padding:2px 6px;border-radius:3px;font-size:11px;">{r['rule_type']}</span></td>
            <td style="padding:6px 8px;text-align:center;">{enabled_badge}</td>
            <td style="padding:6px 8px;">
                <button onclick="REMINDERS.toggleRule({r['id']}, {1 if not r.get('enabled') else 0})"
                        style="background:#4a5568;color:#e2e8f0;border:none;padding:3px 8px;border-radius:3px;cursor:pointer;font-size:11px;">
                    {'Enable' if not r.get('enabled') else 'Disable'}
                </button>
                <button onclick="REMINDERS.deleteRule({r['id']})"
                        style="background:#742a2a;color:#feb2b2;border:none;padding:3px 8px;border-radius:3px;cursor:pointer;font-size:11px;margin-left:4px;">
                    Del
                </button>
            </td>
        </tr>"""

    active_rows = ""
    if not active:
        active_rows = '<tr><td colspan="5" style="text-align:center;color:#888;padding:16px;">No active reminders</td></tr>'
    else:
        for a in active:
            active_rows += f"""<tr style="border-left:3px solid #d69e2e;">
                <td style="padding:4px 8px;font-size:11px;color:#999;">{a.get('timestamp','')}</td>
                <td style="padding:4px 8px;font-size:11px;">{a.get('rule_name','') or a.get('rule_type','')}</td>
                <td style="padding:4px 8px;font-size:11px;">{a.get('message','')}</td>
                <td style="padding:4px 8px;">
                    <button onclick="REMINDERS.ack({a['id']})"
                            style="background:#2b6cb0;color:#fff;border:none;padding:2px 8px;border-radius:3px;cursor:pointer;font-size:11px;">
                        ACK
                    </button>
                </td>
            </tr>"""

    return f"""
<div style="font-family:'Segoe UI',system-ui,sans-serif;color:#e2e8f0;max-height:80vh;display:flex;flex-direction:column;">
    <div style="padding:12px 16px;border-bottom:1px solid #2d3748;">
        <h3 style="margin:0;font-size:16px;color:#f6ad55;">Smart Reminders</h3>
        <p style="margin:4px 0 0;font-size:12px;color:#888;">On-scene timers, repeated alarms, shift handoff</p>
    </div>

    <!-- Active Reminders -->
    <div style="padding:8px 16px;">
        <h4 style="margin:0 0 6px;font-size:13px;color:#f6ad55;">Active Reminders</h4>
        <div style="max-height:200px;overflow-y:auto;">
            <table style="width:100%;border-collapse:collapse;">
                <thead><tr style="background:#1a202c;">
                    <th style="padding:4px 8px;text-align:left;font-size:11px;color:#a0aec0;">Time</th>
                    <th style="padding:4px 8px;text-align:left;font-size:11px;color:#a0aec0;">Rule</th>
                    <th style="padding:4px 8px;text-align:left;font-size:11px;color:#a0aec0;">Message</th>
                    <th style="padding:4px 8px;width:50px;"></th>
                </tr></thead>
                <tbody id="reminder-active-body">{active_rows}</tbody>
            </table>
        </div>
    </div>

    <!-- Rules Config -->
    <div style="padding:8px 16px;flex:1;overflow-y:auto;">
        <h4 style="margin:0 0 6px;font-size:13px;color:#a0aec0;">Reminder Rules</h4>
        <table style="width:100%;border-collapse:collapse;">
            <thead><tr style="background:#1a202c;">
                <th style="padding:4px 8px;text-align:left;font-size:11px;color:#a0aec0;width:30px;">ID</th>
                <th style="padding:4px 8px;text-align:left;font-size:11px;color:#a0aec0;">Name</th>
                <th style="padding:4px 8px;text-align:left;font-size:11px;color:#a0aec0;">Type</th>
                <th style="padding:4px 8px;text-align:center;font-size:11px;color:#a0aec0;width:40px;">Status</th>
                <th style="padding:4px 8px;width:120px;"></th>
            </tr></thead>
            <tbody>{rules_rows}</tbody>
        </table>
    </div>
</div>

<script>
window.REMINDERS = window.REMINDERS || {{}};
REMINDERS.toggleRule = function(id, enabled) {{
    fetch('/api/reminders/rules/' + id, {{
        method: 'PUT',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{enabled: enabled}})
    }}).then(function() {{ CAD_MODAL.open('/modals/reminders'); }});
}};
REMINDERS.deleteRule = function(id) {{
    if (!confirm('Delete this rule?')) return;
    fetch('/api/reminders/rules/' + id, {{method: 'DELETE'}})
        .then(function() {{ CAD_MODAL.open('/modals/reminders'); }});
}};
REMINDERS.ack = function(id) {{
    fetch('/api/reminders/' + id + '/acknowledge', {{method: 'POST'}})
        .then(function() {{ CAD_MODAL.open('/modals/reminders'); }});
}};
</script>
"""
