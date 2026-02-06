# ============================================================================
# FORD CAD - Reporting System Models & Database Schema (v3)
# ============================================================================
# Full schema per reporting-tool-prompt: report_templates, report_runs,
# report_deliveries, report_schedules, plus legacy tables preserved.
# ============================================================================

import sqlite3
import json
import uuid
import hmac
import hashlib
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field, asdict
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo('America/New_York')
DB_PATH = Path("cad.db")
ARTIFACT_DIR = Path("artifacts/reports")

# Secret for signing download tokens
_DOWNLOAD_SECRET = "ford-cad-report-download-2026"


# ============================================================================
# Database Schema  (additive — never drops existing tables)
# ============================================================================

SCHEMA_SQL = """
-- Legacy tables (preserved) ------------------------------------------------
CREATE TABLE IF NOT EXISTS ReportingConfig (
    id INTEGER PRIMARY KEY,
    key TEXT UNIQUE NOT NULL,
    value TEXT,
    value_type TEXT DEFAULT 'string',
    category TEXT DEFAULT 'general',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT
);

CREATE TABLE IF NOT EXISTS ReportRecipients (
    id INTEGER PRIMARY KEY,
    schedule_id INTEGER,
    recipient_type TEXT NOT NULL,
    destination TEXT NOT NULL,
    name TEXT,
    role TEXT,
    shift TEXT,
    enabled INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

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

-- NEW tables per prompt spec -----------------------------------------------

CREATE TABLE IF NOT EXISTS report_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    template_key TEXT UNIQUE NOT NULL,
    description TEXT,
    default_config_json TEXT DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS report_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_key TEXT NOT NULL,
    title TEXT,
    filters_json TEXT DEFAULT '{}',
    format_json TEXT DEFAULT '["html"]',
    created_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'pending',
    summary_text TEXT,
    artifact_paths_json TEXT DEFAULT '{}',
    error_text TEXT
);

CREATE TABLE IF NOT EXISTS report_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_run_id INTEGER REFERENCES report_runs(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    destination TEXT NOT NULL,
    payload_json TEXT,
    status TEXT DEFAULT 'pending',
    provider_message_id TEXT,
    error_text TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS report_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    template_key TEXT NOT NULL,
    filters_json TEXT DEFAULT '{}',
    formats_json TEXT DEFAULT '["pdf","html"]',
    delivery_json TEXT DEFAULT '[]',
    rrule_or_cron TEXT,
    schedule_type TEXT DEFAULT 'cron',
    enabled INTEGER DEFAULT 0,
    created_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_run_at TIMESTAMP,
    next_run_at TIMESTAMP
);

-- Legacy schedule table (kept for backward compat) -------------------------
CREATE TABLE IF NOT EXISTS ReportSchedules (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    report_type TEXT NOT NULL,
    schedule_type TEXT DEFAULT 'shift_based',
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

-- Legacy history / delivery (kept) -----------------------------------------
CREATE TABLE IF NOT EXISTS ReportHistory (
    id INTEGER PRIMARY KEY,
    schedule_id INTEGER,
    report_type TEXT,
    shift TEXT,
    status TEXT DEFAULT 'pending',
    recipients_count INTEGER DEFAULT 0,
    successful_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    error_message TEXT,
    report_data TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    triggered_by TEXT,
    triggered_by_user TEXT
);

CREATE TABLE IF NOT EXISTS ReportDeliveryLog (
    id INTEGER PRIMARY KEY,
    history_id INTEGER,
    recipient TEXT NOT NULL,
    recipient_name TEXT,
    channel TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    error_message TEXT,
    sent_at TIMESTAMP,
    response_data TEXT
);

-- Indexes ------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_report_runs_status ON report_runs(status);
CREATE INDEX IF NOT EXISTS idx_report_runs_template ON report_runs(template_key);
CREATE INDEX IF NOT EXISTS idx_report_runs_created ON report_runs(created_at);
CREATE INDEX IF NOT EXISTS idx_report_deliveries_run ON report_deliveries(report_run_id);
CREATE INDEX IF NOT EXISTS idx_report_schedules_enabled ON report_schedules(enabled);
CREATE INDEX IF NOT EXISTS idx_report_templates_key ON report_templates(template_key);
CREATE INDEX IF NOT EXISTS idx_report_history_status ON ReportHistory(status);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON ReportAuditLog(action);
CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON ReportAuditLog(timestamp);
"""


def init_database():
    """Initialize the reporting database tables."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()


def get_db():
    """Get database connection with row factory."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def ensure_artifact_dir(run_id: int) -> Path:
    """Create and return artifact directory for a report run."""
    d = ARTIFACT_DIR / str(run_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


# ============================================================================
# Signed-URL helpers
# ============================================================================

def make_download_token(run_id: int, kind: str, ttl: int = 3600) -> str:
    """Create a time-limited signed token for downloading a report artifact."""
    expires = int(time.time()) + ttl
    payload = f"{run_id}:{kind}:{expires}"
    sig = hmac.new(_DOWNLOAD_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{payload}:{sig}"


def verify_download_token(token: str) -> Optional[Dict]:
    """Verify a download token.  Returns {run_id, kind} or None."""
    try:
        parts = token.split(":")
        if len(parts) != 4:
            return None
        run_id, kind, expires_str, sig = parts
        expires = int(expires_str)
        if time.time() > expires:
            return None
        payload = f"{run_id}:{kind}:{expires_str}"
        expected = hmac.new(_DOWNLOAD_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(sig, expected):
            return None
        return {"run_id": int(run_id), "kind": kind}
    except Exception:
        return None


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class ReportTemplate:
    id: Optional[int] = None
    name: str = ""
    template_key: str = ""
    description: str = ""
    default_config_json: str = "{}"
    created_at: Optional[str] = None

    def to_dict(self):
        d = asdict(self)
        try:
            d["default_config"] = json.loads(d.pop("default_config_json"))
        except Exception:
            d["default_config"] = {}
        return d


@dataclass
class ReportRun:
    id: Optional[int] = None
    template_key: str = ""
    title: str = ""
    filters_json: str = "{}"
    format_json: str = '["html"]'
    created_by: str = ""
    created_at: Optional[str] = None
    status: str = "pending"
    summary_text: str = ""
    artifact_paths_json: str = "{}"
    error_text: Optional[str] = None

    def to_dict(self):
        d = asdict(self)
        for jf in ("filters_json", "format_json", "artifact_paths_json"):
            key = jf.replace("_json", "")
            try:
                d[key] = json.loads(d.pop(jf))
            except Exception:
                d[key] = {}
        return d


@dataclass
class ReportDelivery:
    id: Optional[int] = None
    report_run_id: Optional[int] = None
    channel: str = ""
    destination: str = ""
    payload_json: str = "{}"
    status: str = "pending"
    provider_message_id: Optional[str] = None
    error_text: Optional[str] = None
    created_at: Optional[str] = None

    def to_dict(self):
        d = asdict(self)
        try:
            d["payload"] = json.loads(d.pop("payload_json"))
        except Exception:
            d["payload"] = {}
        return d


@dataclass
class ReportScheduleNew:
    """New-style schedule matching the prompt spec."""
    id: Optional[int] = None
    name: str = ""
    template_key: str = ""
    filters_json: str = "{}"
    formats_json: str = '["pdf","html"]'
    delivery_json: str = "[]"
    rrule_or_cron: Optional[str] = None
    schedule_type: str = "cron"
    enabled: bool = False
    created_by: str = ""
    created_at: Optional[str] = None
    last_run_at: Optional[str] = None
    next_run_at: Optional[str] = None

    def to_dict(self):
        d = asdict(self)
        for jf in ("filters_json", "formats_json", "delivery_json"):
            key = jf.replace("_json", "")
            try:
                d[key] = json.loads(d.pop(jf))
            except Exception:
                d[key] = [] if "delivery" in jf or "formats" in jf else {}
        return d


# Keep legacy classes for backward compat
@dataclass
class Schedule:
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

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_row(cls, row):
        return cls(**{k: row[k] for k in row.keys()})


@dataclass
class Recipient:
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

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_row(cls, row):
        d = dict(row)
        d["enabled"] = bool(d.get("enabled", 1))
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ReportHistoryEntry:
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

    def to_dict(self):
        d = asdict(self)
        if d.get("report_data"):
            try:
                d["report_data"] = json.loads(d["report_data"])
            except Exception:
                pass
        return d

    @classmethod
    def from_row(cls, row):
        return cls(**{k: row[k] for k in row.keys()})


# ============================================================================
# Repositories — NEW tables
# ============================================================================

class TemplateRepository:
    @staticmethod
    def get_all() -> List[ReportTemplate]:
        conn = get_db()
        rows = conn.execute("SELECT * FROM report_templates ORDER BY name").fetchall()
        conn.close()
        return [ReportTemplate(**dict(r)) for r in rows]

    @staticmethod
    def get_by_key(key: str) -> Optional[ReportTemplate]:
        conn = get_db()
        row = conn.execute("SELECT * FROM report_templates WHERE template_key = ?", (key,)).fetchone()
        conn.close()
        return ReportTemplate(**dict(row)) if row else None

    @staticmethod
    def upsert(t: ReportTemplate) -> int:
        conn = get_db()
        conn.execute(
            """INSERT INTO report_templates (name, template_key, description, default_config_json)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(template_key) DO UPDATE SET
               name=excluded.name, description=excluded.description,
               default_config_json=excluded.default_config_json""",
            (t.name, t.template_key, t.description, t.default_config_json),
        )
        conn.commit()
        row = conn.execute("SELECT id FROM report_templates WHERE template_key = ?", (t.template_key,)).fetchone()
        conn.close()
        return row[0] if row else 0

    @staticmethod
    def delete(key: str):
        conn = get_db()
        conn.execute("DELETE FROM report_templates WHERE template_key = ?", (key,))
        conn.commit()
        conn.close()


class RunRepository:
    @staticmethod
    def create(run: ReportRun) -> int:
        conn = get_db()
        cur = conn.execute(
            """INSERT INTO report_runs
               (template_key, title, filters_json, format_json, created_by, status, summary_text)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (run.template_key, run.title, run.filters_json, run.format_json,
             run.created_by, run.status, run.summary_text),
        )
        conn.commit()
        rid = cur.lastrowid
        conn.close()
        return rid

    @staticmethod
    def get_by_id(run_id: int) -> Optional[ReportRun]:
        conn = get_db()
        row = conn.execute("SELECT * FROM report_runs WHERE id = ?", (run_id,)).fetchone()
        conn.close()
        return ReportRun(**dict(row)) if row else None

    @staticmethod
    def get_recent(limit: int = 50, template_key: str = None) -> List[ReportRun]:
        conn = get_db()
        if template_key:
            rows = conn.execute(
                "SELECT * FROM report_runs WHERE template_key = ? ORDER BY created_at DESC LIMIT ?",
                (template_key, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM report_runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        conn.close()
        return [ReportRun(**dict(r)) for r in rows]

    @staticmethod
    def update_status(run_id: int, status: str, error: str = None):
        conn = get_db()
        conn.execute("UPDATE report_runs SET status = ?, error_text = ? WHERE id = ?",
                      (status, error, run_id))
        conn.commit()
        conn.close()

    @staticmethod
    def save_artifacts(run_id: int, paths: Dict[str, str]):
        conn = get_db()
        conn.execute("UPDATE report_runs SET artifact_paths_json = ? WHERE id = ?",
                      (json.dumps(paths), run_id))
        conn.commit()
        conn.close()

    @staticmethod
    def save_summary(run_id: int, summary: str):
        conn = get_db()
        conn.execute("UPDATE report_runs SET summary_text = ? WHERE id = ?", (summary, run_id))
        conn.commit()
        conn.close()


class DeliveryRepository:
    @staticmethod
    def create(d: ReportDelivery) -> int:
        conn = get_db()
        cur = conn.execute(
            """INSERT INTO report_deliveries
               (report_run_id, channel, destination, payload_json, status)
               VALUES (?, ?, ?, ?, ?)""",
            (d.report_run_id, d.channel, d.destination, d.payload_json, d.status),
        )
        conn.commit()
        did = cur.lastrowid
        conn.close()
        return did

    @staticmethod
    def update_status(delivery_id: int, status: str, error: str = None, msg_id: str = None):
        conn = get_db()
        conn.execute(
            "UPDATE report_deliveries SET status = ?, error_text = ?, provider_message_id = ? WHERE id = ?",
            (status, error, msg_id, delivery_id))
        conn.commit()
        conn.close()

    @staticmethod
    def get_for_run(run_id: int) -> List[ReportDelivery]:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM report_deliveries WHERE report_run_id = ? ORDER BY id", (run_id,)).fetchall()
        conn.close()
        return [ReportDelivery(**dict(r)) for r in rows]


class NewScheduleRepository:
    @staticmethod
    def get_all() -> List[ReportScheduleNew]:
        conn = get_db()
        rows = conn.execute("SELECT * FROM report_schedules ORDER BY id").fetchall()
        conn.close()
        return [ReportScheduleNew(**dict(r)) for r in rows]

    @staticmethod
    def get_enabled() -> List[ReportScheduleNew]:
        conn = get_db()
        rows = conn.execute("SELECT * FROM report_schedules WHERE enabled = 1").fetchall()
        conn.close()
        return [ReportScheduleNew(**dict(r)) for r in rows]

    @staticmethod
    def get_by_id(sid: int) -> Optional[ReportScheduleNew]:
        conn = get_db()
        row = conn.execute("SELECT * FROM report_schedules WHERE id = ?", (sid,)).fetchone()
        conn.close()
        return ReportScheduleNew(**dict(row)) if row else None

    @staticmethod
    def create(s: ReportScheduleNew) -> int:
        conn = get_db()
        cur = conn.execute(
            """INSERT INTO report_schedules
               (name, template_key, filters_json, formats_json, delivery_json,
                rrule_or_cron, schedule_type, enabled, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (s.name, s.template_key, s.filters_json, s.formats_json,
             s.delivery_json, s.rrule_or_cron, s.schedule_type,
             1 if s.enabled else 0, s.created_by),
        )
        conn.commit()
        sid = cur.lastrowid
        conn.close()
        return sid

    @staticmethod
    def update(s: ReportScheduleNew):
        conn = get_db()
        conn.execute(
            """UPDATE report_schedules SET
               name=?, template_key=?, filters_json=?, formats_json=?,
               delivery_json=?, rrule_or_cron=?, schedule_type=?, enabled=?
               WHERE id=?""",
            (s.name, s.template_key, s.filters_json, s.formats_json,
             s.delivery_json, s.rrule_or_cron, s.schedule_type,
             1 if s.enabled else 0, s.id),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def toggle(sid: int, enabled: bool):
        conn = get_db()
        conn.execute("UPDATE report_schedules SET enabled = ? WHERE id = ?",
                      (1 if enabled else 0, sid))
        conn.commit()
        conn.close()

    @staticmethod
    def update_last_run(sid: int, next_run: str = None):
        conn = get_db()
        now = datetime.now(EASTERN).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE report_schedules SET last_run_at = ?, next_run_at = ? WHERE id = ?",
                      (now, next_run, sid))
        conn.commit()
        conn.close()

    @staticmethod
    def delete(sid: int):
        conn = get_db()
        conn.execute("DELETE FROM report_schedules WHERE id = ?", (sid,))
        conn.commit()
        conn.close()


# ============================================================================
# Legacy Repositories (preserved for backward compat)
# ============================================================================

class ScheduleRepository:
    @staticmethod
    def get_all():
        conn = get_db()
        rows = conn.execute("SELECT * FROM ReportSchedules ORDER BY id").fetchall()
        conn.close()
        return [Schedule.from_row(r) for r in rows]

    @staticmethod
    def get_by_id(sid):
        conn = get_db()
        row = conn.execute("SELECT * FROM ReportSchedules WHERE id = ?", (sid,)).fetchone()
        conn.close()
        return Schedule.from_row(row) if row else None

    @staticmethod
    def get_enabled():
        conn = get_db()
        rows = conn.execute("SELECT * FROM ReportSchedules WHERE enabled = 1").fetchall()
        conn.close()
        return [Schedule.from_row(r) for r in rows]

    @staticmethod
    def create(schedule):
        conn = get_db()
        cur = conn.execute(
            """INSERT INTO ReportSchedules
               (name, description, report_type, schedule_type, cron_expression,
                day_time, night_time, timezone, enabled)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (schedule.name, schedule.description, schedule.report_type,
             schedule.schedule_type, schedule.cron_expression,
             schedule.day_time, schedule.night_time, schedule.timezone,
             1 if schedule.enabled else 0),
        )
        conn.commit()
        sid = cur.lastrowid
        conn.close()
        return sid

    @staticmethod
    def update(schedule):
        conn = get_db()
        conn.execute(
            """UPDATE ReportSchedules SET name=?, description=?, report_type=?,
               schedule_type=?, cron_expression=?, day_time=?, night_time=?,
               timezone=?, enabled=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (schedule.name, schedule.description, schedule.report_type,
             schedule.schedule_type, schedule.cron_expression,
             schedule.day_time, schedule.night_time, schedule.timezone,
             1 if schedule.enabled else 0, schedule.id),
        )
        conn.commit()
        conn.close()
        return True

    @staticmethod
    def delete(sid):
        conn = get_db()
        conn.execute("DELETE FROM ReportSchedules WHERE id = ?", (sid,))
        conn.commit()
        conn.close()
        return True

    @staticmethod
    def set_enabled(sid, enabled):
        conn = get_db()
        conn.execute("UPDATE ReportSchedules SET enabled=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                      (1 if enabled else 0, sid))
        conn.commit()
        conn.close()
        return True

    @staticmethod
    def update_last_run(sid, next_run=None):
        conn = get_db()
        now = datetime.now(EASTERN).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE ReportSchedules SET last_run=?, next_run=? WHERE id=?",
                      (now, next_run, sid))
        conn.commit()
        conn.close()


class RecipientRepository:
    @staticmethod
    def get_all(schedule_id=None):
        conn = get_db()
        if schedule_id:
            rows = conn.execute("SELECT * FROM ReportRecipients WHERE schedule_id = ? ORDER BY id",
                                (schedule_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM ReportRecipients ORDER BY id").fetchall()
        conn.close()
        return [Recipient.from_row(r) for r in rows]

    @staticmethod
    def get_by_id(rid):
        conn = get_db()
        row = conn.execute("SELECT * FROM ReportRecipients WHERE id = ?", (rid,)).fetchone()
        conn.close()
        return Recipient.from_row(row) if row else None

    @staticmethod
    def get_by_shift(shift):
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM ReportRecipients WHERE (shift = ? OR shift IS NULL) AND enabled = 1",
            (shift,)).fetchall()
        conn.close()
        return [Recipient.from_row(r) for r in rows]

    @staticmethod
    def get_battalion_chiefs():
        conn = get_db()
        rows = conn.execute("SELECT * FROM ReportRecipients WHERE role = 'battalion_chief'").fetchall()
        conn.close()
        result = {}
        for row in rows:
            r = Recipient.from_row(row)
            if r.shift:
                result[r.shift] = r
        return result

    @staticmethod
    def create(r):
        conn = get_db()
        cur = conn.execute(
            """INSERT INTO ReportRecipients
               (schedule_id, recipient_type, destination, name, role, shift, enabled)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (r.schedule_id, r.recipient_type, r.destination, r.name, r.role, r.shift,
             1 if r.enabled else 0),
        )
        conn.commit()
        rid = cur.lastrowid
        conn.close()
        return rid

    @staticmethod
    def update(r):
        conn = get_db()
        conn.execute(
            """UPDATE ReportRecipients SET schedule_id=?, recipient_type=?, destination=?,
               name=?, role=?, shift=?, enabled=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (r.schedule_id, r.recipient_type, r.destination, r.name, r.role, r.shift,
             1 if r.enabled else 0, r.id),
        )
        conn.commit()
        conn.close()
        return True

    @staticmethod
    def delete(rid):
        conn = get_db()
        conn.execute("DELETE FROM ReportRecipients WHERE id = ?", (rid,))
        conn.commit()
        conn.close()
        return True

    @staticmethod
    def upsert_battalion_chief(shift, email, name=None, phone=None):
        conn = get_db()
        existing = conn.execute(
            "SELECT id FROM ReportRecipients WHERE role = 'battalion_chief' AND shift = ?",
            (shift,)).fetchone()
        if existing:
            conn.execute("UPDATE ReportRecipients SET destination=?, name=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                          (email, name, existing["id"]))
        else:
            conn.execute(
                """INSERT INTO ReportRecipients
                   (recipient_type, destination, name, role, shift, enabled)
                   VALUES ('email', ?, ?, 'battalion_chief', ?, 1)""",
                (email, name, shift))
        conn.commit()
        conn.close()


class HistoryRepository:
    @staticmethod
    def get_recent(limit=50):
        conn = get_db()
        rows = conn.execute("SELECT * FROM ReportHistory ORDER BY started_at DESC LIMIT ?",
                             (limit,)).fetchall()
        conn.close()
        return [ReportHistoryEntry.from_row(r) for r in rows]

    @staticmethod
    def get_by_id(hid):
        conn = get_db()
        row = conn.execute("SELECT * FROM ReportHistory WHERE id = ?", (hid,)).fetchone()
        conn.close()
        return ReportHistoryEntry.from_row(row) if row else None

    @staticmethod
    def create(entry):
        conn = get_db()
        now = datetime.now(EASTERN).strftime("%Y-%m-%d %H:%M:%S")
        cur = conn.execute(
            """INSERT INTO ReportHistory
               (schedule_id, report_type, shift, status, recipients_count,
                triggered_by, triggered_by_user, started_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (entry.schedule_id, entry.report_type, entry.shift, entry.status,
             entry.recipients_count, entry.triggered_by, entry.triggered_by_user, now),
        )
        conn.commit()
        hid = cur.lastrowid
        conn.close()
        return hid

    @staticmethod
    def update_status(hid, status, successful=0, failed=0, error=None):
        conn = get_db()
        now = datetime.now(EASTERN).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """UPDATE ReportHistory SET status=?, successful_count=?, failed_count=?,
               error_message=?, completed_at=? WHERE id=?""",
            (status, successful, failed, error, now, hid))
        conn.commit()
        conn.close()

    @staticmethod
    def save_report_data(hid, data):
        conn = get_db()
        conn.execute("UPDATE ReportHistory SET report_data = ? WHERE id = ?",
                      (json.dumps(data), hid))
        conn.commit()
        conn.close()


class DeliveryLogRepository:
    @staticmethod
    def create(history_id, recipient, name, channel):
        conn = get_db()
        cur = conn.execute(
            """INSERT INTO ReportDeliveryLog
               (history_id, recipient, recipient_name, channel, status)
               VALUES (?, ?, ?, ?, 'pending')""",
            (history_id, recipient, name, channel))
        conn.commit()
        lid = cur.lastrowid
        conn.close()
        return lid

    @staticmethod
    def update_status(lid, status, error=None, response=None):
        conn = get_db()
        now = datetime.now(EASTERN).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE ReportDeliveryLog SET status=?, error_message=?, response_data=?, sent_at=? WHERE id=?",
            (status, error, response, now, lid))
        conn.commit()
        conn.close()

    @staticmethod
    def get_for_history(hid):
        conn = get_db()
        rows = conn.execute("SELECT * FROM ReportDeliveryLog WHERE history_id = ?", (hid,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]


class AuditRepository:
    @staticmethod
    def log(action, category="general", user_id=None, user_name=None,
            old_value=None, new_value=None, details=None, ip_address=None):
        conn = get_db()
        conn.execute(
            """INSERT INTO ReportAuditLog
               (action, category, user_id, user_name, old_value, new_value, details, ip_address)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (action, category, user_id, user_name, old_value, new_value, details, ip_address))
        conn.commit()
        conn.close()

    @staticmethod
    def get_recent(limit=100, category=None):
        conn = get_db()
        if category:
            rows = conn.execute(
                "SELECT * FROM ReportAuditLog WHERE category = ? ORDER BY timestamp DESC LIMIT ?",
                (category, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM ReportAuditLog ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def seed_builtin_templates():
    """Seed the report_templates table with built-in template definitions."""
    builtins = [
        ReportTemplate(
            name="Blotter / Daily Log",
            template_key="blotter",
            description="Chronological list of events (daily logs + related remarks). Filters by date range, shift, event type, unit, calltaker, status.",
            default_config_json=json.dumps({"mode": "detailed"}),
        ),
        ReportTemplate(
            name="Incident Summary",
            template_key="incident_summary",
            description="One or many incidents with full details: type, location, timestamps, dispositions, narrative, units, timeline.",
            default_config_json=json.dumps({}),
        ),
        ReportTemplate(
            name="Unit Response Stats",
            template_key="unit_response_stats",
            description="Response time metrics per unit: time-to-dispatch, enroute, arrive, on-scene, utilization, counts.",
            default_config_json=json.dumps({"group_by": "unit"}),
        ),
        ReportTemplate(
            name="Calltaker Stats",
            template_key="calltaker_stats",
            description="Call counts, time to dispatch, dispositions, remarks per calltaker.",
            default_config_json=json.dumps({"group_by": "calltaker"}),
        ),
        ReportTemplate(
            name="Shift Workload Summary",
            template_key="shift_workload",
            description="Workload distribution across shifts: incident counts, daily log activity, resource usage.",
            default_config_json=json.dumps({}),
        ),
        ReportTemplate(
            name="Response-Time Compliance",
            template_key="response_compliance",
            description="Pass/fail analysis against response time thresholds per incident type.",
            default_config_json=json.dumps({"threshold_minutes": 5}),
        ),
    ]
    for t in builtins:
        TemplateRepository.upsert(t)


# Initialize on import
init_database()
seed_builtin_templates()
