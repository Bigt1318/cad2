# ============================================================================
# FORD CAD - State-of-the-Art Reporting System
# ============================================================================
# Enterprise-grade reporting module inspired by Tyler New World, Mark43,
# Hexagon, and ImageTrend CAD systems.
#
# Features:
#   - Timezone-aware scheduling (APScheduler)
#   - Multi-channel delivery (Email, SMS, Webhooks)
#   - Full audit logging
#   - Complete user control
#   - Database-backed configuration
# ============================================================================

from .config import ReportingConfig, get_config, set_config
from .scheduler import ReportScheduler, get_scheduler
from .engine import ReportEngine
from .routes import register_reporting_routes

__version__ = "2.0.0"
__all__ = [
    "ReportingConfig",
    "get_config",
    "set_config",
    "ReportScheduler",
    "get_scheduler",
    "ReportEngine",
    "register_reporting_routes",
]
