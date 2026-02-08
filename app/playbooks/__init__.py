"""
FORD-CAD Playbooks Module
Admin-defined trigger-condition-action workflow automation.
"""
from .routes import register_playbook_routes
from .engine import evaluate_playbooks
from .models import init_playbook_schema

__all__ = [
    "register_playbook_routes",
    "evaluate_playbooks",
    "init_playbook_schema",
]
