"""
FORD-CAD Playbooks — Action Executors

Executes playbook actions: notifications, suggestions, auto-dispatch hints.
"""
import json
import asyncio
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def execute_actions(actions_json: str, context: Dict, playbook_name: str = "") -> List[str]:
    """
    Execute all actions for a matched playbook.
    Returns list of action descriptions taken.
    """
    try:
        actions = json.loads(actions_json) if isinstance(actions_json, str) else actions_json
    except (json.JSONDecodeError, TypeError):
        return []

    results = []
    for action in actions:
        desc = _execute_single(action, context, playbook_name)
        if desc:
            results.append(desc)

    return results


def _execute_single(action: Dict, context: Dict, playbook_name: str) -> Optional[str]:
    """Execute a single action."""
    action_type = action.get("action", "")
    message = action.get("message", "")
    incident_id = context.get("incident_id")
    unit_id = context.get("unit_id")

    if action_type == "notify":
        _send_notification(message, incident_id, unit_id, playbook_name)
        return f"Notified: {message}"

    elif action_type == "suggest_dispatch":
        unit_pattern = action.get("unit_pattern", "")
        _send_suggestion(message or f"Suggest dispatch: {unit_pattern}", incident_id, playbook_name)
        return f"Suggested dispatch: {unit_pattern}"

    elif action_type == "auto_notify_supervisor":
        _send_notification(
            message or f"Playbook '{playbook_name}' triggered for incident #{incident_id}",
            incident_id, unit_id, playbook_name,
            targets=action.get("targets", ["battalion"])
        )
        return f"Supervisor notified: {message}"

    elif action_type == "add_narrative":
        _add_narrative(incident_id, message or f"[AUTO] Playbook: {playbook_name}", context.get("user", "SYSTEM"))
        return f"Narrative added: {message}"

    elif action_type == "set_priority":
        # Emit as event; actual priority change is a UI concern
        _send_notification(f"Priority change suggested: {action.get('priority', 'HIGH')}", incident_id, unit_id, playbook_name)
        return f"Priority suggestion: {action.get('priority')}"

    else:
        logger.warning(f"[Playbooks] Unknown action type: {action_type}")
        return None


def _send_notification(message: str, incident_id: Optional[int], unit_id: Optional[str],
                       playbook_name: str, targets: List[str] = None):
    """Send notification via WebSocket broadcast."""
    try:
        from app.messaging.websocket import get_broadcaster
        broadcaster = get_broadcaster()
        payload = {
            "message": message,
            "playbook": playbook_name,
            "incident_id": incident_id,
            "unit_id": unit_id,
            "targets": targets or [],
        }
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(broadcaster.broadcast("playbook_notification", payload))
        except RuntimeError:
            pass
    except Exception as e:
        logger.debug(f"[Playbooks] notification broadcast skipped: {e}")


def _send_suggestion(message: str, incident_id: Optional[int], playbook_name: str):
    """Send a suggestion toast via WebSocket."""
    try:
        from app.messaging.websocket import get_broadcaster
        broadcaster = get_broadcaster()
        payload = {
            "type": "suggestion",
            "message": message,
            "playbook": playbook_name,
            "incident_id": incident_id,
        }
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(broadcaster.broadcast("playbook_suggestion", payload))
        except RuntimeError:
            pass
    except Exception:
        pass


def _add_narrative(incident_id: Optional[int], text: str, user: str):
    """Add a narrative entry via the existing add_narrative system."""
    if not incident_id:
        return
    try:
        import sqlite3
        conn = sqlite3.connect("cad.db", timeout=30, check_same_thread=False)
        c = conn.cursor()
        import datetime
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("""
            INSERT INTO Narrative (incident_id, timestamp, entry_type, text, user)
            VALUES (?, ?, 'AUTO', ?, ?)
        """, (incident_id, ts, text, user))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.debug(f"[Playbooks] auto-narrative failed: {e}")
