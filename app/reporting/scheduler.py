# ============================================================================
# FORD CAD - Report Scheduler (APScheduler-based)
# ============================================================================
# Robust, timezone-aware scheduling using APScheduler.
# Supports shift-based scheduling and cron expressions.
# ============================================================================

import logging
from datetime import datetime, timedelta
from typing import Optional, Callable, Dict, List
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
    ScheduleRepository,
    Schedule,
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
    Enterprise-grade report scheduler using APScheduler.

    Features:
    - Timezone-aware scheduling (default: America/New_York)
    - Shift-based scheduling (17:30 day, 05:30 night)
    - Cron expression support
    - Proper start/stop control
    - Audit logging
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
        self._jobs: Dict[int, str] = {}  # schedule_id -> job_id
        self._running = False
        self._report_callback: Optional[Callable] = None

        if APSCHEDULER_AVAILABLE:
            self._init_scheduler()
        else:
            logger.warning("APScheduler not available, using fallback scheduler")

    def _init_scheduler(self):
        """Initialize the APScheduler instance."""
        tz = get_timezone()

        self._scheduler = BackgroundScheduler(
            timezone=tz,
            job_defaults={
                "coalesce": True,  # Combine missed runs
                "max_instances": 1,  # Only one instance at a time
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

    def set_report_callback(self, callback: Callable):
        """Set the callback function for report generation."""
        self._report_callback = callback

    def start(self, user: str = None) -> bool:
        """
        Start the scheduler.

        Returns True if started successfully, False if already running or disabled.
        """
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
            # Load schedules from database
            self._load_schedules()

            # Start the scheduler
            if not self._scheduler.running:
                self._scheduler.start()

            self._running = True
            set_config("scheduler_running", True, user=user)
            set_config("scheduler_was_running", True, user=user)

            logger.info(f"Scheduler started at {format_time_for_display()}")
            AuditRepository.log(
                action="scheduler_started",
                category="scheduler",
                user_name=user,
                details=f"Scheduler started with {len(self._jobs)} jobs",
            )

            return True

        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}")
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

    def _load_schedules(self):
        """Load all enabled schedules from database."""
        schedules = ScheduleRepository.get_enabled()

        for schedule in schedules:
            self._add_schedule_job(schedule)

        logger.info(f"Loaded {len(schedules)} enabled schedules")

    def _add_schedule_job(self, schedule: Schedule):
        """Add a job for a schedule."""
        if not self._scheduler:
            return

        # Remove existing job if any
        if schedule.id in self._jobs:
            self._remove_schedule_job(schedule.id)

        job_id = f"schedule_{schedule.id}"

        if schedule.schedule_type == "shift_based":
            # Add two jobs: one for day shift, one for night shift
            day_time = schedule.day_time.split(":")
            night_time = schedule.night_time.split(":")

            # Day shift report job
            day_trigger = CronTrigger(
                hour=int(day_time[0]),
                minute=int(day_time[1]),
                timezone=get_timezone(),
            )
            self._scheduler.add_job(
                self._run_shift_report,
                trigger=day_trigger,
                id=f"{job_id}_day",
                args=[schedule.id, "day"],
                replace_existing=True,
            )

            # Night shift report job
            night_trigger = CronTrigger(
                hour=int(night_time[0]),
                minute=int(night_time[1]),
                timezone=get_timezone(),
            )
            self._scheduler.add_job(
                self._run_shift_report,
                trigger=night_trigger,
                id=f"{job_id}_night",
                args=[schedule.id, "night"],
                replace_existing=True,
            )

            self._jobs[schedule.id] = job_id
            logger.info(
                f"Added shift-based schedule {schedule.id}: "
                f"day@{schedule.day_time}, night@{schedule.night_time}"
            )

        elif schedule.schedule_type == "cron" and schedule.cron_expression:
            trigger = CronTrigger.from_crontab(
                schedule.cron_expression,
                timezone=get_timezone(),
            )
            self._scheduler.add_job(
                self._run_scheduled_report,
                trigger=trigger,
                id=job_id,
                args=[schedule.id],
                replace_existing=True,
            )
            self._jobs[schedule.id] = job_id
            logger.info(f"Added cron schedule {schedule.id}: {schedule.cron_expression}")

    def _remove_schedule_job(self, schedule_id: int):
        """Remove jobs for a schedule."""
        if not self._scheduler:
            return

        job_id = self._jobs.get(schedule_id)
        if not job_id:
            return

        try:
            # Remove both day and night jobs for shift-based
            self._scheduler.remove_job(f"{job_id}_day")
        except:
            pass

        try:
            self._scheduler.remove_job(f"{job_id}_night")
        except:
            pass

        try:
            self._scheduler.remove_job(job_id)
        except:
            pass

        del self._jobs[schedule_id]

    def _run_shift_report(self, schedule_id: int, shift_type: str):
        """Execute a shift-based report."""
        now = get_local_now()
        current_shift = get_current_shift(now)

        logger.info(
            f"Shift report triggered: schedule={schedule_id}, "
            f"shift_type={shift_type}, current_shift={current_shift}"
        )

        if self._report_callback:
            try:
                self._report_callback(
                    schedule_id=schedule_id,
                    shift=current_shift,
                    triggered_by="scheduler",
                )
            except Exception as e:
                logger.error(f"Report callback failed: {e}")

        # Update last run time
        next_run = self._calculate_next_run(schedule_id)
        ScheduleRepository.update_last_run(schedule_id, next_run)

    def _run_scheduled_report(self, schedule_id: int):
        """Execute a scheduled report."""
        logger.info(f"Scheduled report triggered: schedule={schedule_id}")

        if self._report_callback:
            try:
                self._report_callback(
                    schedule_id=schedule_id,
                    triggered_by="scheduler",
                )
            except Exception as e:
                logger.error(f"Report callback failed: {e}")

        # Update last run time
        next_run = self._calculate_next_run(schedule_id)
        ScheduleRepository.update_last_run(schedule_id, next_run)

    def _calculate_next_run(self, schedule_id: int) -> Optional[str]:
        """Calculate the next run time for a schedule."""
        job_id = self._jobs.get(schedule_id)
        if not job_id or not self._scheduler:
            return None

        # Try to get next run from day job
        try:
            job = self._scheduler.get_job(f"{job_id}_day")
            if job and job.next_run_time:
                return format_time_for_display(job.next_run_time)
        except:
            pass

        # Try night job
        try:
            job = self._scheduler.get_job(f"{job_id}_night")
            if job and job.next_run_time:
                return format_time_for_display(job.next_run_time)
        except:
            pass

        return None

    def get_status(self) -> Dict:
        """Get comprehensive scheduler status."""
        now = get_local_now()

        status = {
            "enabled": get_config("scheduler_enabled", False),
            "running": self.is_running(),
            "current_time": format_time_for_display(now),
            "timezone": str(get_timezone()),
            "current_shift": get_current_shift(now),
            "jobs_count": len(self._jobs),
            "next_reports": [],
        }

        # Get next scheduled reports
        if self._scheduler and self.is_running():
            jobs = self._scheduler.get_jobs()
            for job in jobs:
                if job.next_run_time:
                    status["next_reports"].append({
                        "job_id": job.id,
                        "next_run": format_time_for_display(job.next_run_time),
                        "next_run_iso": job.next_run_time.isoformat(),
                    })

            # Sort by next run time
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

    def run_now(self, schedule_id: int, user: str = None) -> bool:
        """Manually trigger a report for testing."""
        logger.info(f"Manual report trigger: schedule={schedule_id}, user={user}")

        AuditRepository.log(
            action="report_manual_trigger",
            category="scheduler",
            user_name=user,
            details=f"Manual trigger for schedule {schedule_id}",
        )

        if self._report_callback:
            try:
                current_shift = get_current_shift(get_local_now())
                self._report_callback(
                    schedule_id=schedule_id,
                    shift=current_shift,
                    triggered_by="manual",
                    triggered_by_user=user,
                )
                return True
            except Exception as e:
                logger.error(f"Manual report failed: {e}")
                return False

        return False

    def refresh_schedules(self):
        """Reload schedules from database."""
        if not self._scheduler:
            return

        # Remove all current jobs
        for schedule_id in list(self._jobs.keys()):
            self._remove_schedule_job(schedule_id)

        # Reload enabled schedules
        self._load_schedules()


# Singleton instance
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
