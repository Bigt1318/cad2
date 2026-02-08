"""
FORD-CAD Smart Reminders Module
Proactive notifications for on-scene timers, repeated alarms, and shift handoffs.
"""
from .routes import register_reminder_routes
from .scheduler_jobs import init_reminder_scheduler
from .models import init_reminder_schema

__all__ = [
    "register_reminder_routes",
    "init_reminder_scheduler",
    "init_reminder_schema",
]
