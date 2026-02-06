# ============================================================================
# FORD CAD - Reporting Configuration Management
# ============================================================================
# Database-backed configuration with type casting and defaults.
# All times use Eastern timezone (America/New_York).
# ============================================================================

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import get_db, AuditRepository

EASTERN = ZoneInfo('America/New_York')

# Default configuration values
DEFAULT_CONFIG = {
    # Timezone
    "timezone": ("America/New_York", "string", "general"),

    # Scheduler state
    "scheduler_enabled": (False, "bool", "scheduler"),
    "scheduler_running": (False, "bool", "scheduler"),
    "scheduler_was_running": (False, "bool", "scheduler"),

    # Report times
    "day_shift_report_time": ("17:30", "string", "schedule"),
    "night_shift_report_time": ("05:30", "string", "schedule"),

    # Email configuration
    "email_provider": ("sendgrid", "string", "email"),
    "sendgrid_api_key": ("", "string", "email"),
    "smtp_host": ("smtp.gmail.com", "string", "email"),
    "smtp_port": (587, "int", "email"),
    "smtp_user": ("", "string", "email"),
    "smtp_pass": ("", "string", "email"),
    "from_email": ("cad@blueovalsk.com", "string", "email"),
    "from_name": ("FORD CAD System", "string", "email"),

    # Confirmation
    "require_confirmation": (False, "bool", "general"),
    "confirmation_timeout_seconds": (60, "int", "general"),

    # Features
    "sms_enabled": (False, "bool", "features"),
    "slack_enabled": (False, "bool", "features"),
    "pdf_export_enabled": (True, "bool", "features"),
}

# Battalion Chief defaults
BC_DEFAULTS = {
    "A": {"name": "Bill Mullins", "email": "", "phone": ""},
    "B": {"name": "Daniel Highbaugh", "email": "", "phone": ""},
    "C": {"name": "Kevin Jevning", "email": "", "phone": ""},
    "D": {"name": "Shane Carpenter", "email": "", "phone": ""},
}


class ReportingConfig:
    """
    Database-backed configuration manager for the reporting system.

    All configuration is stored in the ReportingConfig table with
    proper type handling and audit logging.
    """

    _cache: Dict[str, Any] = {}
    _cache_loaded: bool = False

    @classmethod
    def _load_cache(cls):
        """Load all config into memory cache."""
        if cls._cache_loaded:
            return

        # Start with defaults
        for key, (default, vtype, category) in DEFAULT_CONFIG.items():
            cls._cache[key] = default

        # Load from database
        conn = get_db()
        rows = conn.execute("SELECT key, value, value_type FROM ReportingConfig").fetchall()
        conn.close()

        for row in rows:
            cls._cache[row["key"]] = cls._cast_value(row["value"], row["value_type"])

        cls._cache_loaded = True

    @classmethod
    def _cast_value(cls, value: str, value_type: str) -> Any:
        """Cast string value to appropriate type."""
        if value is None:
            return None
        if value_type == "bool":
            return value.lower() in ("true", "1", "yes", "on")
        if value_type == "int":
            try:
                return int(value)
            except ValueError:
                return 0
        if value_type == "json":
            try:
                return json.loads(value)
            except:
                return {}
        return value

    @classmethod
    def _serialize_value(cls, value: Any, value_type: str) -> str:
        """Serialize value to string for storage."""
        if value is None:
            return ""
        if value_type == "bool":
            return "true" if value else "false"
        if value_type == "int":
            return str(value)
        if value_type == "json":
            return json.dumps(value)
        return str(value)

    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        cls._load_cache()
        return cls._cache.get(key, default)

    @classmethod
    def set(
        cls,
        key: str,
        value: Any,
        value_type: str = None,
        category: str = "general",
        user: str = None,
    ) -> bool:
        """Set a configuration value."""
        cls._load_cache()

        # Determine value type
        if value_type is None:
            if key in DEFAULT_CONFIG:
                _, value_type, category = DEFAULT_CONFIG[key]
            elif isinstance(value, bool):
                value_type = "bool"
            elif isinstance(value, int):
                value_type = "int"
            elif isinstance(value, dict):
                value_type = "json"
            else:
                value_type = "string"

        # Get old value for audit
        old_value = cls._cache.get(key)

        # Serialize and store
        serialized = cls._serialize_value(value, value_type)

        conn = get_db()
        conn.execute(
            """INSERT INTO ReportingConfig (key, value, value_type, category, updated_by)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET
               value = excluded.value,
               value_type = excluded.value_type,
               category = excluded.category,
               updated_at = CURRENT_TIMESTAMP,
               updated_by = excluded.updated_by""",
            (key, serialized, value_type, category, user),
        )
        conn.commit()
        conn.close()

        # Update cache
        cls._cache[key] = value

        # Audit log
        if old_value != value:
            AuditRepository.log(
                action="config_changed",
                category="config",
                user_name=user,
                old_value=str(old_value),
                new_value=str(value),
                details=f"Changed {key}",
            )

        return True

    @classmethod
    def get_all(cls, category: str = None) -> Dict[str, Any]:
        """Get all configuration values, optionally filtered by category."""
        cls._load_cache()

        if category is None:
            return dict(cls._cache)

        # Filter by category from defaults
        result = {}
        for key, (default, vtype, cat) in DEFAULT_CONFIG.items():
            if cat == category:
                result[key] = cls._cache.get(key, default)
        return result

    @classmethod
    def reset_cache(cls):
        """Reset the configuration cache."""
        cls._cache = {}
        cls._cache_loaded = False

    @classmethod
    def init_defaults(cls):
        """Initialize default configuration values in database if not present."""
        conn = get_db()

        for key, (default, value_type, category) in DEFAULT_CONFIG.items():
            existing = conn.execute(
                "SELECT key FROM ReportingConfig WHERE key = ?", (key,)
            ).fetchone()

            if not existing:
                serialized = cls._serialize_value(default, value_type)
                conn.execute(
                    """INSERT INTO ReportingConfig (key, value, value_type, category)
                       VALUES (?, ?, ?, ?)""",
                    (key, serialized, value_type, category),
                )

        conn.commit()
        conn.close()
        cls.reset_cache()


# Convenience functions
def get_config(key: str, default: Any = None) -> Any:
    """Get a configuration value."""
    return ReportingConfig.get(key, default)


def set_config(key: str, value: Any, user: str = None) -> bool:
    """Set a configuration value."""
    return ReportingConfig.set(key, value, user=user)


def get_all_config() -> Dict[str, Any]:
    """Get all configuration values."""
    return ReportingConfig.get_all()


# ============================================================================
# Timezone Helpers
# ============================================================================

def get_timezone():
    """Get the configured timezone object."""
    tz_name = get_config("timezone", "America/New_York")
    try:
        return ZoneInfo(tz_name)
    except:
        return EASTERN


def get_local_now():
    """Get current time in configured timezone."""
    return datetime.now(get_timezone())


def get_local_time():
    """Alias for get_local_now for compatibility."""
    return get_local_now()


def format_time_for_display(dt: datetime = None) -> str:
    """Format a datetime for display in local timezone."""
    if dt is None:
        dt = get_local_now()
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=EASTERN)
    else:
        dt = dt.astimezone(get_timezone())
    return dt.strftime("%Y-%m-%d %H:%M:%S %Z")


def format_time_short(dt: datetime = None) -> str:
    """Format time in short format."""
    if dt is None:
        dt = get_local_now()
    return dt.strftime("%H:%M %Z")


def parse_time_input(time_str: str) -> tuple:
    """Parse a time string like '17:30' into (hour, minute)."""
    try:
        parts = time_str.split(":")
        return (int(parts[0]), int(parts[1]))
    except:
        return (17, 30)


# ============================================================================
# Migration from old config
# ============================================================================

def migrate_from_json_config():
    """Migrate settings from old email_config.json to database."""
    config_path = Path("email_config.json")
    if not config_path.exists():
        return

    try:
        with open(config_path) as f:
            old_config = json.load(f)

        # Migrate settings
        migrations = {
            "sendgrid_api_key": "sendgrid_api_key",
            "from_email": "from_email",
            "timezone": "timezone",
            "auto_report_enabled": "scheduler_enabled",
            "day_report_time": "day_shift_report_time",
            "night_report_time": "night_shift_report_time",
        }

        for old_key, new_key in migrations.items():
            if old_key in old_config and old_config[old_key]:
                set_config(new_key, old_config[old_key], user="migration")

        # Migrate battalion chiefs
        if "battalion_chiefs" in old_config:
            from .models import RecipientRepository
            for shift, info in old_config["battalion_chiefs"].items():
                if info.get("email"):
                    RecipientRepository.upsert_battalion_chief(
                        shift=shift,
                        email=info["email"],
                        name=info.get("name", BC_DEFAULTS.get(shift, {}).get("name", "")),
                    )

        print("[REPORTING] Migrated config from email_config.json")

    except Exception as e:
        print(f"[REPORTING] Migration error: {e}")


# Initialize defaults on import
ReportingConfig.init_defaults()
