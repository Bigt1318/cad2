"""
FORD-CAD Reminders — Scheduler Jobs

Uses its own APScheduler BackgroundScheduler instance (not the reporting scheduler).
"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler

from .engine import check_on_scene_timers, check_repeated_alarms, generate_shift_handoff_summary

logger = logging.getLogger(__name__)

_scheduler = None


def get_reminder_scheduler() -> BackgroundScheduler:
    """Get or create the singleton reminder scheduler."""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 120}
        )
    return _scheduler


def init_reminder_scheduler():
    """Register and start reminder scheduler jobs."""
    scheduler = get_reminder_scheduler()

    if scheduler.running:
        return

    # On-Scene Timer: check every 60 seconds
    scheduler.add_job(
        check_on_scene_timers,
        "interval",
        seconds=60,
        id="reminder_on_scene_timer",
        replace_existing=True,
    )

    # Repeated Alarm Detector: check every 5 minutes
    scheduler.add_job(
        check_repeated_alarms,
        "interval",
        minutes=5,
        id="reminder_repeated_alarm",
        replace_existing=True,
    )

    # Shift Handoff Summary: run at shift change times
    # Ford shifts: A=0700, B=1500, C=2300
    for hour in (7, 15, 23):
        scheduler.add_job(
            _post_shift_handoff,
            "cron",
            hour=hour,
            minute=0,
            id=f"reminder_shift_handoff_{hour:02d}",
            replace_existing=True,
        )

    scheduler.start()
    logger.info("[Reminders] Scheduler started with on-scene, repeated-alarm, and shift-handoff jobs")


def _post_shift_handoff():
    """Generate and broadcast shift handoff summary."""
    try:
        summary = generate_shift_handoff_summary()
        if not summary:
            return

        # Broadcast via WebSocket
        try:
            from app.messaging.websocket import get_broadcaster
            import asyncio
            broadcaster = get_broadcaster()
            payload = {
                "message": summary,
                "severity": "info",
                "type": "shift_handoff",
            }
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(broadcaster.broadcast("reminder", payload))
            except RuntimeError:
                pass
        except Exception:
            pass

        # Emit to event stream
        try:
            from app.eventstream.emitter import emit_event
            emit_event("SHIFT_HANDOFF", summary=summary[:200], category="system")
        except Exception:
            pass

        logger.info("[Reminders] Shift handoff summary posted")

    except Exception as e:
        logger.error(f"[Reminders] Shift handoff failed: {e}")
