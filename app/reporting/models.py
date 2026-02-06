# ============================================================================
# FORD CAD - Reporting System Models & Database Schema
# ============================================================================

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field, asdict
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo('America/New_York')

# Database path
DB_PATH = Path("cad.db")


# ============================================================================
# Database Schema
# ============================================================================

SCHEMA_SQL = """
-- Reporting Configuration (key-value store)
CREATE TABLE IF NOT EXISTS ReportingConfig (
    id INTEGER PRIMARY KEY,
    key TEXT UNIQUE NOT NULL,
    value TEXT,
    value_type TEXT DEFAULT 'string',  -- string, bool, int, json
    category TEXT DEFAULT 'general',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT
);

-- Report Schedules
CREATE TABLE IF NOT EXISTS ReportSchedules (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    report_type TEXT NOT NULL,  -- 'shift_end', 'daily_summary', 'weekly', 'custom'
    schedule_type TEXT DEFAULT 'shift_based',  -- 'shift_based', 'cron', 'interval'
    cron_expression TEXT,
    day_time TEXT DEFAULT '17:30',
    night_time TEXT DEFAULT '05:30',
    timezone TEXT DEFAULT 'America/New_York',
    enabled INTEGER DEFAULT 0,
    last_run TIMESTAMP,
    next_run TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Report Recipients
CREATE TABLE IF NOT EXISTS ReportRecipients (
    id INTEGER PRIMARY KEY,
    schedule_id INTEGER REFERENCES ReportSchedules(id) ON DELETE CASCADE,
    recipient_type TEXT NOT NULL,  -- 'email', 'sms', 'webhook', 'slack'
    destination TEXT NOT NULL,
    name TEXT,
    role TEXT,  -- 'battalion_chief', 'admin', 'custom'
    shift TEXT,  -- A, B, C, D or NULL for all shifts
    enabled INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Report History
CREATE TABLE IF NOT EXISTS ReportHistory (
    id INTEGER PRIMARY KEY,
    schedule_id INTEGER,
    report_type TEXT,
    shift TEXT,
    status TEXT DEFAULT 'pending',  -- 'pending', 'sending', 'sent', 'partial', 'failed', 'cancelled'
    recipients_count INTEGER DEFAULT 0,
    successful_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    error_message TEXT,
    report_data TEXT,  -- JSON cached report content
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    triggered_by TEXT,  -- 'scheduler', 'manual', 'api'
    triggered_by_user TEXT
);

-- Report Delivery Log (per-recipient)
CREATE TABLE IF NOT EXISTS ReportDeliveryLog (
    id INTEGER PRIMARY KEY,
    history_id INTEGER REFERENCES ReportHistory(id) ON DELETE CASCADE,
    recipient TEXT NOT NULL,
    recipient_name TEXT,
    channel TEXT NOT NULL,  -- 'email', 'sms', 'webhook'
    status TEXT DEFAULT 'pending',  -- 'pending', 'sent', 'failed', 'bounced'
    error_message TEXT,
    sent_at TIMESTAMP,
    response_data TEXT
);

-- Audit Log for all reporting changes
CREATE TABLE IF NOT EXISTS ReportAuditLog (
    id INTEGER PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    action TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    user_id TEXT,
    user_name TEXT,
    old_value TEXT,
    new_value TEXT,
    details TEXT,
    ip_address TEXT
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_report_history_status ON ReportHistory(status);
CREATE INDEX IF NOT EXISTS idx_report_history_schedule ON ReportHistory(schedule_id);
CREATE INDEX IF NOT EXISTS idx_report_delivery_history ON ReportDeliveryLog(history_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON ReportAuditLog(action);
CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON ReportAuditLog(timestamp);
"""


def init_database():
    """Initialize the reporting database tables."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()
    print("[REPORTING] Database schema initialized")


def get_db():
    """Get database connection with row factory."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class Schedule:
    """Report schedule data class."""
    id: Optional[int] = None
    name: str = ""
    description: str = ""
    report_type: str = "shift_end"
    schedule_type: str = "shift_based"
    cron_expression: Optional[str] = None
    day_time: str = "17:30"
    night_time: str = "05:30"
    timezone: str = "America/New_York"
    enabled: bool = False
    last_run: Optional[str] = None
    next_run: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Schedule":
        return cls(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            report_type=row["report_type"],
            schedule_type=row["schedule_type"],
            cron_expression=row["cron_expression"],
            day_time=row["day_time"],
            night_time=row["night_time"],
            timezone=row["timezone"],
            enabled=bool(row["enabled"]),
            last_run=row["last_run"],
            next_run=row["next_run"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class Recipient:
    """Report recipient data class."""
    id: Optional[int] = None
    schedule_id: Optional[int] = None
    recipient_type: str = "email"
    destination: str = ""
    name: str = ""
    role: str = "custom"
    shift: Optional[str] = None
    enabled: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Recipient":
        return cls(
            id=row["id"],
            schedule_id=row["schedule_id"],
            recipient_type=row["recipient_type"],
            destination=row["destination"],
            name=row["name"],
            role=row["role"],
            shift=row["shift"],
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class ReportHistoryEntry:
    """Report history entry data class."""
    id: Optional[int] = None
    schedule_id: Optional[int] = None
    report_type: str = ""
    shift: str = ""
    status: str = "pending"
    recipients_count: int = 0
    successful_count: int = 0
    failed_count: int = 0
    error_message: Optional[str] = None
    report_data: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    triggered_by: str = "manual"
    triggered_by_user: Optional[str] = None

    def to_dict(self) -> Dict:
        d = asdict(self)
        # Parse report_data JSON if present
        if d.get("report_data"):
            try:
                d["report_data"] = json.loads(d["report_data"])
            except:
                pass
        return d

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "ReportHistoryEntry":
        return cls(
            id=row["id"],
            schedule_id=row["schedule_id"],
            report_type=row["report_type"],
            shift=row["shift"],
            status=row["status"],
            recipients_count=row["recipients_count"],
            successful_count=row["successful_count"],
            failed_count=row["failed_count"],
            error_message=row["error_message"],
            report_data=row["report_data"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            triggered_by=row["triggered_by"],
            triggered_by_user=row["triggered_by_user"],
        )


# ============================================================================
# CRUD Operations
# ============================================================================

class ScheduleRepository:
    """Repository for report schedules."""

    @staticmethod
    def get_all() -> List[Schedule]:
        conn = get_db()
        rows = conn.execute("SELECT * FROM ReportSchedules ORDER BY id").fetchall()
        conn.close()
        return [Schedule.from_row(r) for r in rows]

    @staticmethod
    def get_by_id(schedule_id: int) -> Optional[Schedule]:
        conn = get_db()
        row = conn.execute(
            "SELECT * FROM ReportSchedules WHERE id = ?", (schedule_id,)
        ).fetchone()
        conn.close()
        return Schedule.from_row(row) if row else None

    @staticmethod
    def get_enabled() -> List[Schedule]:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM ReportSchedules WHERE enabled = 1"
        ).fetchall()
        conn.close()
        return [Schedule.from_row(r) for r in rows]

    @staticmethod
    def create(schedule: Schedule) -> int:
        conn = get_db()
        cursor = conn.execute(
            """INSERT INTO ReportSchedules
               (name, description, report_type, schedule_type, cron_expression,
                day_time, night_time, timezone, enabled)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                schedule.name,
                schedule.description,
                schedule.report_type,
                schedule.schedule_type,
                schedule.cron_expression,
                schedule.day_time,
                schedule.night_time,
                schedule.timezone,
                1 if schedule.enabled else 0,
            ),
        )
        conn.commit()
        schedule_id = cursor.lastrowid
        conn.close()
        return schedule_id

    @staticmethod
    def update(schedule: Schedule) -> bool:
        conn = get_db()
        conn.execute(
            """UPDATE ReportSchedules SET
               name = ?, description = ?, report_type = ?, schedule_type = ?,
               cron_expression = ?, day_time = ?, night_time = ?, timezone = ?,
               enabled = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (
                schedule.name,
                schedule.description,
                schedule.report_type,
                schedule.schedule_type,
                schedule.cron_expression,
                schedule.day_time,
                schedule.night_time,
                schedule.timezone,
                1 if schedule.enabled else 0,
                schedule.id,
            ),
        )
        conn.commit()
        conn.close()
        return True

    @staticmethod
    def delete(schedule_id: int) -> bool:
        conn = get_db()
        conn.execute("DELETE FROM ReportSchedules WHERE id = ?", (schedule_id,))
        conn.commit()
        conn.close()
        return True

    @staticmethod
    def set_enabled(schedule_id: int, enabled: bool) -> bool:
        conn = get_db()
        conn.execute(
            "UPDATE ReportSchedules SET enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (1 if enabled else 0, schedule_id),
        )
        conn.commit()
        conn.close()
        return True

    @staticmethod
    def update_last_run(schedule_id: int, next_run: str = None):
        conn = get_db()
        now = datetime.now(EASTERN).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE ReportSchedules SET last_run = ?, next_run = ? WHERE id = ?",
            (now, next_run, schedule_id),
        )
        conn.commit()
        conn.close()


class RecipientRepository:
    """Repository for report recipients."""

    @staticmethod
    def get_all(schedule_id: int = None) -> List[Recipient]:
        conn = get_db()
        if schedule_id:
            rows = conn.execute(
                "SELECT * FROM ReportRecipients WHERE schedule_id = ? ORDER BY id",
                (schedule_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM ReportRecipients ORDER BY id"
            ).fetchall()
        conn.close()
        return [Recipient.from_row(r) for r in rows]

    @staticmethod
    def get_by_id(recipient_id: int) -> Optional[Recipient]:
        conn = get_db()
        row = conn.execute(
            "SELECT * FROM ReportRecipients WHERE id = ?", (recipient_id,)
        ).fetchone()
        conn.close()
        return Recipient.from_row(row) if row else None

    @staticmethod
    def get_by_role(role: str) -> List[Recipient]:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM ReportRecipients WHERE role = ? AND enabled = 1",
            (role,),
        ).fetchall()
        conn.close()
        return [Recipient.from_row(r) for r in rows]

    @staticmethod
    def get_by_shift(shift: str) -> List[Recipient]:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM ReportRecipients WHERE (shift = ? OR shift IS NULL) AND enabled = 1",
            (shift,),
        ).fetchall()
        conn.close()
        return [Recipient.from_row(r) for r in rows]

    @staticmethod
    def get_battalion_chiefs() -> Dict[str, Recipient]:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM ReportRecipients WHERE role = 'battalion_chief'"
        ).fetchall()
        conn.close()
        result = {}
        for row in rows:
            r = Recipient.from_row(row)
            if r.shift:
                result[r.shift] = r
        return result

    @staticmethod
    def create(recipient: Recipient) -> int:
        conn = get_db()
        cursor = conn.execute(
            """INSERT INTO ReportRecipients
               (schedule_id, recipient_type, destination, name, role, shift, enabled)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                recipient.schedule_id,
                recipient.recipient_type,
                recipient.destination,
                recipient.name,
                recipient.role,
                recipient.shift,
                1 if recipient.enabled else 0,
            ),
        )
        conn.commit()
        recipient_id = cursor.lastrowid
        conn.close()
        return recipient_id

    @staticmethod
    def update(recipient: Recipient) -> bool:
        conn = get_db()
        conn.execute(
            """UPDATE ReportRecipients SET
               schedule_id = ?, recipient_type = ?, destination = ?, name = ?,
               role = ?, shift = ?, enabled = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (
                recipient.schedule_id,
                recipient.recipient_type,
                recipient.destination,
                recipient.name,
                recipient.role,
                recipient.shift,
                1 if recipient.enabled else 0,
                recipient.id,
            ),
        )
        conn.commit()
        conn.close()
        return True

    @staticmethod
    def delete(recipient_id: int) -> bool:
        conn = get_db()
        conn.execute("DELETE FROM ReportRecipients WHERE id = ?", (recipient_id,))
        conn.commit()
        conn.close()
        return True

    @staticmethod
    def upsert_battalion_chief(shift: str, email: str, name: str = None, phone: str = None):
        """Update or insert battalion chief for a shift."""
        conn = get_db()
        existing = conn.execute(
            "SELECT id FROM ReportRecipients WHERE role = 'battalion_chief' AND shift = ?",
            (shift,),
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE ReportRecipients SET
                   destination = ?, name = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (email, name, existing["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO ReportRecipients
                   (recipient_type, destination, name, role, shift, enabled)
                   VALUES ('email', ?, ?, 'battalion_chief', ?, 1)""",
                (email, name, shift),
            )
        conn.commit()
        conn.close()


class HistoryRepository:
    """Repository for report history."""

    @staticmethod
    def get_recent(limit: int = 50) -> List[ReportHistoryEntry]:
        conn = get_db()
        rows = conn.execute(
            """SELECT * FROM ReportHistory
               ORDER BY started_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        conn.close()
        return [ReportHistoryEntry.from_row(r) for r in rows]

    @staticmethod
    def get_by_id(history_id: int) -> Optional[ReportHistoryEntry]:
        conn = get_db()
        row = conn.execute(
            "SELECT * FROM ReportHistory WHERE id = ?", (history_id,)
        ).fetchone()
        conn.close()
        return ReportHistoryEntry.from_row(row) if row else None

    @staticmethod
    def create(entry: ReportHistoryEntry) -> int:
        conn = get_db()
        now = datetime.now(EASTERN).strftime("%Y-%m-%d %H:%M:%S")
        cursor = conn.execute(
            """INSERT INTO ReportHistory
               (schedule_id, report_type, shift, status, recipients_count,
                triggered_by, triggered_by_user, started_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.schedule_id,
                entry.report_type,
                entry.shift,
                entry.status,
                entry.recipients_count,
                entry.triggered_by,
                entry.triggered_by_user,
                now,
            ),
        )
        conn.commit()
        history_id = cursor.lastrowid
        conn.close()
        return history_id

    @staticmethod
    def update_status(
        history_id: int,
        status: str,
        successful: int = 0,
        failed: int = 0,
        error: str = None,
    ):
        conn = get_db()
        now = datetime.now(EASTERN).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """UPDATE ReportHistory SET
               status = ?, successful_count = ?, failed_count = ?,
               error_message = ?, completed_at = ?
               WHERE id = ?""",
            (status, successful, failed, error, now, history_id),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def save_report_data(history_id: int, report_data: dict):
        conn = get_db()
        conn.execute(
            "UPDATE ReportHistory SET report_data = ? WHERE id = ?",
            (json.dumps(report_data), history_id),
        )
        conn.commit()
        conn.close()


class DeliveryLogRepository:
    """Repository for delivery logs."""

    @staticmethod
    def create(history_id: int, recipient: str, name: str, channel: str) -> int:
        conn = get_db()
        cursor = conn.execute(
            """INSERT INTO ReportDeliveryLog
               (history_id, recipient, recipient_name, channel, status)
               VALUES (?, ?, ?, ?, 'pending')""",
            (history_id, recipient, name, channel),
        )
        conn.commit()
        log_id = cursor.lastrowid
        conn.close()
        return log_id

    @staticmethod
    def update_status(log_id: int, status: str, error: str = None, response: str = None):
        conn = get_db()
        now = datetime.now(EASTERN).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """UPDATE ReportDeliveryLog SET
               status = ?, error_message = ?, response_data = ?, sent_at = ?
               WHERE id = ?""",
            (status, error, response, now, log_id),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def get_for_history(history_id: int) -> List[Dict]:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM ReportDeliveryLog WHERE history_id = ?",
            (history_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


class AuditRepository:
    """Repository for audit logs."""

    @staticmethod
    def log(
        action: str,
        category: str = "general",
        user_id: str = None,
        user_name: str = None,
        old_value: str = None,
        new_value: str = None,
        details: str = None,
        ip_address: str = None,
    ):
        conn = get_db()
        conn.execute(
            """INSERT INTO ReportAuditLog
               (action, category, user_id, user_name, old_value, new_value, details, ip_address)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (action, category, user_id, user_name, old_value, new_value, details, ip_address),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def get_recent(limit: int = 100, category: str = None) -> List[Dict]:
        conn = get_db()
        if category:
            rows = conn.execute(
                """SELECT * FROM ReportAuditLog
                   WHERE category = ? ORDER BY timestamp DESC LIMIT ?""",
                (category, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM ReportAuditLog ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def create_default_schedules():
    """Create default schedules if none exist."""
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM ReportSchedules").fetchone()[0]

    if count == 0:
        # Create default shift-end schedule
        conn.execute(
            """INSERT INTO ReportSchedules
               (name, description, report_type, schedule_type, day_time, night_time, timezone, enabled)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "Shift End Report",
                "Automatic shift-end report sent to battalion chiefs",
                "shift_end",
                "shift_based",
                "17:30",
                "05:30",
                "America/New_York",
                False,  # Disabled by default - user must enable
            ),
        )
        conn.commit()
        print("[REPORTING] Created default shift-end schedule")

    conn.close()


# Initialize database on module import
init_database()
create_default_schedules()
