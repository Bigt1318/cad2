"""
FORD-CAD Playbooks — Rule Evaluation Engine

Hooked into Phase 1's emit_event() — after DB write, evaluates matching playbooks.
"""
import json
import logging
from typing import Dict, Optional

from .models import get_playbooks, log_execution, count_fires_for_incident
from .conditions import evaluate_conditions
from .actions import execute_actions

logger = logging.getLogger(__name__)


def evaluate_playbooks(event_type: str, context: Dict) -> None:
    """
    Evaluate all enabled playbooks against an event.
    Called from emit_event() after writing to event_stream.

    context keys: event_type, incident_id, unit_id, category, severity,
                  summary, user, shift
    """
    try:
        playbooks = get_playbooks(enabled_only=True)
        context["event_type"] = event_type

        for pb in playbooks:
            # Check trigger type matches
            if pb["trigger_type"] != event_type and pb["trigger_type"] != "*":
                continue

            # Check max fires per incident
            incident_id = context.get("incident_id")
            if incident_id and pb.get("max_fires_per_incident", 1) > 0:
                fires = count_fires_for_incident(pb["id"], incident_id)
                if fires >= pb["max_fires_per_incident"]:
                    continue

            # Evaluate conditions
            if not evaluate_conditions(pb["conditions_json"], context):
                continue

            # Matched! Execute or suggest based on mode
            mode = pb.get("execution_mode", "suggest")

            if mode == "auto":
                actions_taken = execute_actions(pb["actions_json"], context, pb["name"])
                log_execution(
                    playbook_id=pb["id"],
                    incident_id=incident_id,
                    unit_id=context.get("unit_id"),
                    result="executed",
                    actions_taken=json.dumps(actions_taken),
                    executed_by="system",
                    details=f"Auto-executed: {pb['name']}"
                )
                logger.info(f"[Playbooks] Auto-executed: {pb['name']} for {event_type}")

            elif mode == "suggest":
                # Send suggestion to dispatchers
                _send_playbook_suggestion(pb, context)
                log_execution(
                    playbook_id=pb["id"],
                    incident_id=incident_id,
                    unit_id=context.get("unit_id"),
                    result="suggested",
                    actions_taken=pb["actions_json"],
                    executed_by="system",
                    details=f"Suggested: {pb['name']}"
                )
                logger.info(f"[Playbooks] Suggested: {pb['name']} for {event_type}")

    except Exception as e:
        logger.error(f"[Playbooks] evaluation error: {e}")


def execute_playbook_suggestion(execution_id: int, user: str) -> bool:
    """Execute a previously suggested playbook action (user accepted)."""
    try:
        from .models import _get_conn
        conn = _get_conn()
        row = conn.execute("SELECT * FROM playbook_executions WHERE id = ?", (execution_id,)).fetchone()
        if not row:
            conn.close()
            return False

        context = {
            "incident_id": row["incident_id"],
            "unit_id": row["unit_id"],
        }

        pb = conn.execute("SELECT * FROM playbooks WHERE id = ?", (row["playbook_id"],)).fetchone()
        conn.close()

        if pb:
            execute_actions(pb["actions_json"], context, pb["name"])

        # Update execution log
        conn = _get_conn()
        conn.execute("""
            UPDATE playbook_executions SET result = 'executed', executed_by = ? WHERE id = ?
        """, (user, execution_id))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"[Playbooks] execute suggestion failed: {e}")
        return False


def dismiss_playbook_suggestion(execution_id: int, user: str) -> bool:
    """Dismiss a playbook suggestion."""
    try:
        from .models import _get_conn
        conn = _get_conn()
        conn.execute("""
            UPDATE playbook_executions SET result = 'dismissed', executed_by = ? WHERE id = ?
        """, (user, execution_id))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def _send_playbook_suggestion(playbook: Dict, context: Dict):
    """Broadcast a playbook suggestion to dispatchers."""
    try:
        import asyncio
        from app.messaging.websocket import get_broadcaster
        broadcaster = get_broadcaster()

        actions = json.loads(playbook["actions_json"]) if isinstance(playbook["actions_json"], str) else playbook["actions_json"]
        message = actions[0].get("message", playbook["name"]) if actions else playbook["name"]

        payload = {
            "type": "playbook_suggestion",
            "playbook_id": playbook["id"],
            "playbook_name": playbook["name"],
            "message": message,
            "incident_id": context.get("incident_id"),
            "unit_id": context.get("unit_id"),
        }

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(broadcaster.broadcast("playbook_suggestion", payload))
        except RuntimeError:
            pass
    except Exception:
        pass
