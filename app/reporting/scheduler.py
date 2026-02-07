# ============================================================================
# FORD CAD - Report Scheduler v3 (APScheduler-based)
# ============================================================================
# Robust, timezone-aware scheduling using APScheduler.
# Supports: shift_change, daily, weekly, monthly, once schedule types.
# Works with the v3 template engine (run_report + deliver_report).
# ============================================================================

import json
import logging
import time
import traceback
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
import threading
from zoneinfo import ZoneInfo

# Try to import APScheduler, provide fallback if not available
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.date import DateTrigger
    from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
    APSCHEDULER_AVAILABLE = True
except ImportError:
    APSCHEDULER_AVAILABLE = False
    print("[REPORTING] APScheduler not installed. Install with: pip install apscheduler")

from .config import get_config, set_config, get_timezone, get_local_now, format_time_for_display
from .models import (
    NewScheduleRepository,
    ReportScheduleNew,
    AuditRepository,
    get_db,
)

# Import shift logic
try:
    from shift_logic import get_current_shift
except ImportError:
    def get_current_shift(dt=None):
        """Fallback shift calculation."""
        if dt is None:
            dt = datetime.now()
        hour = dt.hour
        if 6 <= hour < 18:
            return "A"  # Day shift
        return "B"  # Night shift


logger = logging.getLogger("reporting.scheduler")
EASTERN = ZoneInfo('America/New_York')


class ReportScheduler:
    """
    v3 Report Scheduler using APScheduler.

    Supports multiple concurrent scheduled reports with different frequencies:
    - shift_change: fires at day/night shift change times
    - daily: fires once per day at a specified time
    - weekly: fires on specified days of the week
    - monthly: fires on a specified day of the month
    - once: fires once at a specific datetime

    Each schedule references a v3 template_key and uses engine.run_report()
    + engine.deliver_report() for execution and delivery.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self._scheduler: Optional[BackgroundScheduler] = None
        # schedule_id -> list of APScheduler job IDs
        self._jobs: Dict[int, List[str]] = {}
        self._running = False

        if APSCHEDULER_AVAILABLE:
            self._init_scheduler()
        else:
            logger.warning("APScheduler not available, scheduler will be a no-op")

    def _init_scheduler(self):
        """Initialize the APScheduler instance."""
        tz = get_timezone()

        self._scheduler = BackgroundScheduler(
            timezone=tz,
            job_defaults={
                "coalesce": True,       # Combine missed runs
                "max_instances": 1,     # Only one instance per job at a time
                "misfire_grace_time": 300,  # 5 minute grace period
            },
        )

        # Add event listeners
        self._scheduler.add_listener(
            self._on_job_executed,
            EVENT_JOB_EXECUTED,
        )
        self._scheduler.add_listener(
            self._on_job_error,
            EVENT_JOB_ERROR,
        )

    def _on_job_executed(self, event):
        """Handle successful job execution."""
        logger.info(f"Job {event.job_id} executed successfully")

    def _on_job_error(self, event):
        """Handle job execution error."""
        logger.error(f"Job {event.job_id} failed: {event.exception}")
        AuditRepository.log(
            action="scheduler_job_error",
            category="scheduler",
            details=f"Job {event.job_id} failed: {event.exception}",
        )

    # ------------------------------------------------------------------
    # Lifecycle: start / stop / restart
    # ------------------------------------------------------------------

    def start(self, user: str = None) -> bool:
        """Start the scheduler. Returns True if started successfully."""
        if not get_config("scheduler_enabled", False):
            logger.warning("Cannot start scheduler: scheduler_enabled is False")
            return False

        if self._running:
            logger.info("Scheduler already running")
            return True

        if not APSCHEDULER_AVAILABLE:
            logger.error("APScheduler not available")
            return False

        try:
            # Load all enabled schedules from database
            self._load_schedules()

            # Start or resume APScheduler
            if self._scheduler.running:
                self._scheduler.resume()
            else:
                self._scheduler.start()

            self._running = True
            set_config("scheduler_running", True, user=user)
            set_config("scheduler_was_running", True, user=user)

            logger.info(f"Scheduler started at {format_time_for_display()} with {len(self._jobs)} schedules")
            AuditRepository.log(
                action="scheduler_started",
                category="scheduler",
                user_name=user,
                details=f"Scheduler started with {len(self._jobs)} schedules",
            )

            return True

        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}", exc_info=True)
            return False

    def stop(self, user: str = None) -> bool:
        """Stop the scheduler."""
        if not self._running:
            logger.info("Scheduler already stopped")
            return True

        try:
            if self._scheduler and self._scheduler.running:
                self._scheduler.pause()

            self._running = False
            set_config("scheduler_running", False, user=user)
            set_config("scheduler_was_running", False, user=user)

            logger.info(f"Scheduler stopped at {format_time_for_display()}")
            AuditRepository.log(
                action="scheduler_stopped",
                category="scheduler",
                user_name=user,
            )

            return True

        except Exception as e:
            logger.error(f"Failed to stop scheduler: {e}")
            return False

    def restart(self, user: str = None) -> bool:
        """Restart the scheduler."""
        self.stop(user=user)
        return self.start(user=user)

    def is_running(self) -> bool:
        """Check if scheduler is currently running."""
        return self._running and (
            self._scheduler is not None and self._scheduler.running
        )

    # ------------------------------------------------------------------
    # Schedule loading
    # ------------------------------------------------------------------

    def _load_schedules(self):
        """Load all enabled schedules from the database."""
        schedules = NewScheduleRepository.get_enabled()

        for schedule in schedules:
            try:
                self._add_schedule_jobs(schedule)
            except Exception as e:
                logger.error(f"Failed to load schedule {schedule.id} ({schedule.name}): {e}")

        logger.info(f"Loaded {len(self._jobs)} enabled schedules")

    def _add_schedule_jobs(self, schedule: ReportScheduleNew):
        """Add APScheduler jobs for a schedule based on its type."""
        if not self._scheduler:
            return

        # Remove existing jobs for this schedule first
        self._remove_schedule_jobs(schedule.id)

        job_ids = []
        triggers = self._build_triggers(schedule)

        for suffix, trigger, kwargs in triggers:
            job_id = f"sched_{schedule.id}_{suffix}"
            self._scheduler.add_job(
                self._execute_scheduled_job,
                trigger=trigger,
                id=job_id,
                args=[schedule.id],
                kwargs=kwargs,
                replace_existing=True,
            )
            job_ids.append(job_id)
            logger.info(
                f"Added job {job_id} for schedule {schedule.id} ({schedule.name})"
            )

        if job_ids:
            self._jobs[schedule.id] = job_ids

    def _remove_schedule_jobs(self, schedule_id: int):
        """Remove all APScheduler jobs for a schedule."""
        if not self._scheduler:
            return

        job_ids = self._jobs.pop(schedule_id, [])
        for job_id in job_ids:
            try:
                self._scheduler.remove_job(job_id)
            except Exception:
                pass  # Job may already have been removed

    # ------------------------------------------------------------------
    # Trigger builder
    # ------------------------------------------------------------------

    def _build_triggers(self, schedule: ReportScheduleNew) -> List[tuple]:
        """Build APScheduler triggers for a schedule.

        Returns list of (suffix, trigger, extra_kwargs) tuples.
        One schedule can produce multiple triggers (e.g., shift_change -> day + night).

        schedule_type | rrule_or_cron example         | Result
        ------------- | ----------------------------- | ------
        shift_change  | "shift_change"                | Two CronTriggers at day/night times
        daily         | "daily" or "daily:08:00"      | CronTrigger(hour, minute)
        weekly        | "weekly:mon,wed,fri" or       | CronTrigger(day_of_week, hour, minute)
                      | "weekly:mon,wed,fri:09:00"    |
        monthly       | "monthly:15" or               | CronTrigger(day, hour, minute)
                      | "monthly:15:08:00"            |
        once          | "once:2026-02-10T09:00"       | DateTrigger(run_date)
        cron          | "0 17 * * *"                  | CronTrigger.from_crontab()
        """
        tz = get_timezone()
        stype = schedule.schedule_type
        rrule = schedule.rrule_or_cron or ""

        if stype == "shift_change":
            return self._build_shift_change_triggers(tz)

        elif stype == "daily":
            return self._build_daily_trigger(rrule, tz)

        elif stype == "weekly":
            return self._build_weekly_trigger(rrule, tz)

        elif stype == "monthly":
            return self._build_monthly_trigger(rrule, tz)

        elif stype == "once":
            return self._build_once_trigger(rrule, tz)

        elif stype == "cron":
            # Raw crontab expression
            if rrule:
                trigger = CronTrigger.from_crontab(rrule, timezone=tz)
                return [("cron", trigger, {})]
            else:
                logger.warning(f"Cron schedule {schedule.id} has no cron expression")
                return []

        else:
            logger.warning(f"Unknown schedule_type '{stype}' for schedule {schedule.id}")
            return []

    def _build_shift_change_triggers(self, tz) -> List[tuple]:
        """Build two triggers for shift change: day report + night report."""
        day_time_str = get_config("day_shift_report_time", "17:30")
        night_time_str = get_config("night_shift_report_time", "05:30")

        day_parts = day_time_str.split(":")
        night_parts = night_time_str.split(":")

        day_trigger = CronTrigger(
            hour=int(day_parts[0]),
            minute=int(day_parts[1]),
            timezone=tz,
        )
        night_trigger = CronTrigger(
            hour=int(night_parts[0]),
            minute=int(night_parts[1]),
            timezone=tz,
        )

        return [
            ("day", day_trigger, {"shift_hint": "day"}),
            ("night", night_trigger, {"shift_hint": "night"}),
        ]

    def _build_daily_trigger(self, rrule: str, tz) -> List[tuple]:
        """Build a daily trigger. Format: 'daily' or 'daily:HH:MM'."""
        hour, minute = 8, 0  # default 08:00
        if ":" in rrule:
            parts = rrule.split(":")
            # "daily:08:00" -> parts = ["daily", "08", "00"]
            if len(parts) >= 3:
                hour, minute = int(parts[1]), int(parts[2])
            elif len(parts) == 2 and parts[1].isdigit():
                hour = int(parts[1])

        trigger = CronTrigger(hour=hour, minute=minute, timezone=tz)
        return [("daily", trigger, {})]

    def _build_weekly_trigger(self, rrule: str, tz) -> List[tuple]:
        """Build a weekly trigger. Format: 'weekly:mon,wed,fri' or 'weekly:mon,wed,fri:09:00'."""
        hour, minute = 8, 0
        days = "mon"  # default

        if ":" in rrule:
            parts = rrule.split(":")
            # "weekly:mon,wed,fri:09:00"
            if len(parts) >= 2:
                days = parts[1]
            if len(parts) >= 4:
                hour, minute = int(parts[2]), int(parts[3])
            elif len(parts) == 3:
                # Could be "weekly:mon,wed:09" or just "weekly:mon:09"
                try:
                    hour = int(parts[2])
                except ValueError:
                    pass

        trigger = CronTrigger(day_of_week=days, hour=hour, minute=minute, timezone=tz)
        return [("weekly", trigger, {})]

    def _build_monthly_trigger(self, rrule: str, tz) -> List[tuple]:
        """Build a monthly trigger. Format: 'monthly:15' or 'monthly:15:08:00'."""
        day = 1
        hour, minute = 8, 0

        if ":" in rrule:
            parts = rrule.split(":")
            if len(parts) >= 2:
                day = int(parts[1])
            if len(parts) >= 4:
                hour, minute = int(parts[2]), int(parts[3])
            elif len(parts) == 3:
                try:
                    hour = int(parts[2])
                except ValueError:
                    pass

        trigger = CronTrigger(day=day, hour=hour, minute=minute, timezone=tz)
        return [("monthly", trigger, {})]

    def _build_once_trigger(self, rrule: str, tz) -> List[tuple]:
        """Build a one-time trigger. Format: 'once:2026-02-10T09:00'."""
        if ":" in rrule:
            datestr = rrule.split(":", 1)[1]  # everything after "once:"
        else:
            datestr = rrule

        try:
            run_date = datetime.fromisoformat(datestr)
            if run_date.tzinfo is None:
                run_date = run_date.replace(tzinfo=tz)
        except (ValueError, TypeError):
            logger.error(f"Invalid once date: {datestr}")
            return []

        trigger = DateTrigger(run_date=run_date, timezone=tz)
        return [("once", trigger, {})]

    # ------------------------------------------------------------------
    # Job execution
    # ------------------------------------------------------------------

    def _execute_scheduled_job(self, schedule_id: int, shift_hint: str = None):
        """Execute a scheduled report job.

        1. Reload schedule from DB (gets latest config)
        2. Skip if disabled/deleted
        3. Parse filters/formats/channels from JSON fields
        4. Inject shift into filters for shift_change type
        5. Call engine.run_report(template_key, filters, formats)
        6. Call engine.deliver_report(run_id, channels) with retry
        7. Update last_run_at / next_run_at
        8. Audit log
        """
        logger.info(f"Executing scheduled job: schedule_id={schedule_id}, shift_hint={shift_hint}")

        # 1. Reload from DB
        schedule = NewScheduleRepository.get_by_id(schedule_id)
        if not schedule:
            logger.warning(f"Schedule {schedule_id} not found, skipping")
            return

        # 2. Skip if disabled
        if not schedule.enabled:
            logger.info(f"Schedule {schedule_id} is disabled, skipping")
            return

        # 3. Parse JSON fields
        try:
            filters = json.loads(schedule.filters_json) if schedule.filters_json else {}
        except (json.JSONDecodeError, TypeError):
            filters = {}

        try:
            formats = json.loads(schedule.formats_json) if schedule.formats_json else ["html"]
        except (json.JSONDecodeError, TypeError):
            formats = ["html"]

        try:
            channels = json.loads(schedule.delivery_json) if schedule.delivery_json else []
        except (json.JSONDecodeError, TypeError):
            channels = []

        # 4. Inject shift for shift_change schedules
        if schedule.schedule_type == "shift_change" and shift_hint:
            current_shift = get_current_shift(get_local_now())
            filters["shift"] = current_shift

        # 5. Run the report via the v3 engine
        try:
            from .engine import get_engine
            engine = get_engine()

            result = engine.run_report(
                template_key=schedule.template_key,
                filters=filters,
                formats=formats,
                created_by=f"scheduler:{schedule.name}",
                title=f"Scheduled: {schedule.name}",
            )

            if not result.get("ok"):
                logger.error(
                    f"Schedule {schedule_id} run_report failed: {result.get('error', 'unknown')}"
                )
                AuditRepository.log(
                    action="scheduled_report_failed",
                    category="scheduler",
                    details=f"Schedule {schedule_id} ({schedule.name}) run failed: {result.get('error')}",
                )
                self._update_run_times(schedule_id)
                return

            run_id = result["run_id"]
            logger.info(f"Schedule {schedule_id} generated run_id={run_id}")

            # 6. Deliver with retry
            if channels:
                self._deliver_with_retry(engine, run_id, channels, schedule)

            # 7. Update last_run_at / next_run_at
            self._update_run_times(schedule_id)

            # 8. Audit log
            AuditRepository.log(
                action="scheduled_report_completed",
                category="scheduler",
                details=(
                    f"Schedule {schedule_id} ({schedule.name}) completed: "
                    f"run_id={run_id}, template={schedule.template_key}, "
                    f"formats={formats}, channels={len(channels)}"
                ),
            )

        except Exception as e:
            logger.error(f"Schedule {schedule_id} execution failed: {e}\n{traceback.format_exc()}")
            AuditRepository.log(
                action="scheduled_report_error",
                category="scheduler",
                details=f"Schedule {schedule_id} ({schedule.name}) error: {e}",
            )
            self._update_run_times(schedule_id)

    def _deliver_with_retry(
        self,
        engine,
        run_id: int,
        channels: List[Dict[str, str]],
        schedule: ReportScheduleNew,
        max_retries: int = 2,
        retry_delay: float = 30.0,
    ):
        """Deliver a report with retry logic.

        Retries only the channels that failed, up to max_retries times.
        """
        remaining_channels = list(channels)

        for attempt in range(max_retries + 1):
            if not remaining_channels:
                break

            if attempt > 0:
                logger.info(
                    f"Delivery retry {attempt}/{max_retries} for run {run_id}, "
                    f"{len(remaining_channels)} channels remaining"
                )
                time.sleep(retry_delay)

            try:
                result = engine.deliver_report(
                    run_id=run_id,
                    channels=remaining_channels,
                    triggered_by=f"scheduler:{schedule.name}",
                )

                # Check which channels failed
                failed = []
                for delivery in result.get("deliveries", []):
                    if delivery.get("status") == "failed":
                        # Find the original channel config
                        for ch in remaining_channels:
                            if ch.get("destination") == delivery.get("destination"):
                                failed.append(ch)
                                break

                if not failed:
                    logger.info(f"All deliveries succeeded for run {run_id}")
                    return

                remaining_channels = failed

            except Exception as e:
                logger.error(f"Delivery attempt {attempt} failed for run {run_id}: {e}")

        if remaining_channels:
            logger.error(
                f"Delivery exhausted retries for run {run_id}: "
                f"{len(remaining_channels)} channels still failed"
            )

    def _update_run_times(self, schedule_id: int):
        """Update last_run_at and next_run_at in the database."""
        next_run = self._calculate_next_run(schedule_id)
        NewScheduleRepository.update_last_run(schedule_id, next_run)

    def _calculate_next_run(self, schedule_id: int) -> Optional[str]:
        """Calculate the next run time for a schedule from APScheduler."""
        job_ids = self._jobs.get(schedule_id, [])
        if not job_ids or not self._scheduler:
            return None

        next_times = []
        for job_id in job_ids:
            try:
                job = self._scheduler.get_job(job_id)
                if job and job.next_run_time:
                    next_times.append(job.next_run_time)
            except Exception:
                pass

        if next_times:
            # Return the soonest next run
            soonest = min(next_times)
            return format_time_for_display(soonest)

        return None

    # ------------------------------------------------------------------
    # Granular sync (called by routes after CRUD)
    # ------------------------------------------------------------------

    def sync_schedule(self, schedule_id: int):
        """Sync a single schedule with APScheduler after a CRUD operation.

        Reloads the schedule from the DB. If enabled, adds/updates jobs.
        If disabled or deleted, removes jobs.
        """
        if not self._scheduler or not self._running:
            return

        schedule = NewScheduleRepository.get_by_id(schedule_id)

        if not schedule or not schedule.enabled:
            # Schedule deleted or disabled — remove jobs
            self._remove_schedule_jobs(schedule_id)
            logger.info(f"Removed jobs for schedule {schedule_id}")
        else:
            # Schedule exists and is enabled — add/update jobs
            try:
                self._add_schedule_jobs(schedule)
                # Update next_run_at in DB
                next_run = self._calculate_next_run(schedule_id)
                if next_run:
                    NewScheduleRepository.update_last_run(schedule_id, next_run)
                logger.info(f"Synced schedule {schedule_id} ({schedule.name})")
            except Exception as e:
                logger.error(f"Failed to sync schedule {schedule_id}: {e}")

    def remove_schedule(self, schedule_id: int):
        """Remove all jobs for a deleted schedule."""
        self._remove_schedule_jobs(schedule_id)
        logger.info(f"Removed jobs for deleted schedule {schedule_id}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh_schedules(self):
        """Reload all schedules from database (full refresh)."""
        if not self._scheduler:
            return

        # Remove all current jobs
        for schedule_id in list(self._jobs.keys()):
            self._remove_schedule_jobs(schedule_id)

        # Reload enabled schedules
        self._load_schedules()

    def run_now(self, schedule_id: int, user: str = None) -> Dict[str, Any]:
        """Manually trigger a report for a schedule immediately.

        Runs synchronously and returns the result.
        """
        logger.info(f"Manual report trigger: schedule={schedule_id}, user={user}")

        schedule = NewScheduleRepository.get_by_id(schedule_id)
        if not schedule:
            return {"ok": False, "error": f"Schedule {schedule_id} not found"}

        AuditRepository.log(
            action="report_manual_trigger",
            category="scheduler",
            user_name=user,
            details=f"Manual trigger for schedule {schedule_id} ({schedule.name})",
        )

        # Parse the schedule fields
        try:
            filters = json.loads(schedule.filters_json) if schedule.filters_json else {}
        except (json.JSONDecodeError, TypeError):
            filters = {}

        try:
            formats = json.loads(schedule.formats_json) if schedule.formats_json else ["html"]
        except (json.JSONDecodeError, TypeError):
            formats = ["html"]

        try:
            channels = json.loads(schedule.delivery_json) if schedule.delivery_json else []
        except (json.JSONDecodeError, TypeError):
            channels = []

        # Inject shift for shift_change type
        if schedule.schedule_type == "shift_change":
            current_shift = get_current_shift(get_local_now())
            filters["shift"] = current_shift

        try:
            from .engine import get_engine
            engine = get_engine()

            result = engine.run_report(
                template_key=schedule.template_key,
                filters=filters,
                formats=formats,
                created_by=user or f"manual:{schedule.name}",
                title=f"Manual: {schedule.name}",
            )

            if result.get("ok") and channels:
                engine.deliver_report(
                    run_id=result["run_id"],
                    channels=channels,
                    triggered_by=f"manual:{user or 'unknown'}",
                )

            return result

        except Exception as e:
            logger.error(f"Manual report failed: {e}")
            return {"ok": False, "error": str(e)}

    def get_status(self) -> Dict:
        """Get comprehensive scheduler status."""
        now = get_local_now()

        status = {
            "enabled": get_config("scheduler_enabled", False),
            "running": self.is_running(),
            "current_time": format_time_for_display(now),
            "timezone": str(get_timezone()),
            "current_shift": get_current_shift(now),
            "schedules_count": len(self._jobs),
            "jobs_count": sum(len(ids) for ids in self._jobs.values()),
            "schedules": [],
            "next_reports": [],
        }

        # Get all schedules with their APScheduler status
        all_schedules = NewScheduleRepository.get_all()
        for sched in all_schedules:
            sched_info = sched.to_dict()
            job_ids = self._jobs.get(sched.id, [])
            sched_info["active_jobs"] = len(job_ids)

            # Get next run from APScheduler
            if self._scheduler and job_ids:
                next_times = []
                for jid in job_ids:
                    try:
                        job = self._scheduler.get_job(jid)
                        if job and job.next_run_time:
                            next_times.append(job.next_run_time)
                    except Exception:
                        pass
                if next_times:
                    soonest = min(next_times)
                    sched_info["next_run_live"] = format_time_for_display(soonest)
                    sched_info["next_run_iso"] = soonest.isoformat()

            status["schedules"].append(sched_info)

        # Get upcoming jobs
        if self._scheduler and self.is_running():
            jobs = self._scheduler.get_jobs()
            for job in jobs:
                if job.next_run_time:
                    status["next_reports"].append({
                        "job_id": job.id,
                        "next_run": format_time_for_display(job.next_run_time),
                        "next_run_iso": job.next_run_time.isoformat(),
                    })

            status["next_reports"].sort(key=lambda x: x["next_run_iso"])

        # Get the soonest next report
        if status["next_reports"]:
            status["next_report"] = status["next_reports"][0]["next_run"]
        else:
            status["next_report"] = None

        return status

    def get_next_report_time(self) -> Optional[str]:
        """Get the next scheduled report time."""
        status = self.get_status()
        return status.get("next_report")


# ============================================================================
# Singleton access + initialization
# ============================================================================

_scheduler_instance: Optional[ReportScheduler] = None


def get_scheduler() -> ReportScheduler:
    """Get the global scheduler instance."""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = ReportScheduler()
    return _scheduler_instance


def init_scheduler():
    """Initialize the scheduler on application startup."""
    scheduler = get_scheduler()

    # Check if scheduler should auto-start
    enabled = get_config("scheduler_enabled", False)
    was_running = get_config("scheduler_was_running", False)

    if enabled and was_running:
        logger.info("Auto-starting scheduler (was running before shutdown)")
        scheduler.start(user="system")
    elif enabled:
        logger.info("Scheduler enabled but was not running - not auto-starting")
    else:
        logger.info("Scheduler disabled - not starting")

    return scheduler
