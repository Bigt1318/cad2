"""
FORD-CAD Playbooks — Condition Evaluators

Evaluates whether a playbook's conditions match a given event context.
"""
import json
import re
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


def evaluate_conditions(conditions_json: str, context: Dict) -> bool:
    """
    Evaluate all conditions against an event context.
    All conditions must match (AND logic).

    Context keys: event_type, incident_id, unit_id, category, severity,
                  summary, user, incident_type, location, etc.
    """
    try:
        conditions = json.loads(conditions_json) if isinstance(conditions_json, str) else conditions_json
    except (json.JSONDecodeError, TypeError):
        return False

    if not conditions:
        return True  # No conditions = always matches

    for cond in conditions:
        if not _evaluate_single(cond, context):
            return False
    return True


def _evaluate_single(condition: Dict, context: Dict) -> bool:
    """Evaluate a single condition against context."""
    field = condition.get("field", "")
    op = condition.get("op", "equals")
    value = condition.get("value", "")

    actual = context.get(field, "")
    if actual is None:
        actual = ""
    actual_str = str(actual).upper()
    value_str = str(value).upper()

    if op == "equals":
        return actual_str == value_str
    elif op == "not_equals":
        return actual_str != value_str
    elif op == "contains":
        return value_str in actual_str
    elif op == "not_contains":
        return value_str not in actual_str
    elif op == "starts_with":
        return actual_str.startswith(value_str)
    elif op == "ends_with":
        return actual_str.endswith(value_str)
    elif op == "regex":
        try:
            return bool(re.search(value, str(actual), re.IGNORECASE))
        except re.error:
            return False
    elif op == "gt":
        try:
            return float(actual) > float(value)
        except (ValueError, TypeError):
            return False
    elif op == "lt":
        try:
            return float(actual) < float(value)
        except (ValueError, TypeError):
            return False
    elif op == "in":
        # value is comma-separated list
        options = [v.strip().upper() for v in str(value).split(",")]
        return actual_str in options
    else:
        logger.warning(f"[Playbooks] Unknown condition op: {op}")
        return False
