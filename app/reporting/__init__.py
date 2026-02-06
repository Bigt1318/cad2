# ============================================================================
# FORD CAD - State-of-the-Art Reporting System (v3)
# ============================================================================
# Enterprise-grade reporting module with:
#   - Multi-template report generation (blotter, incident, stats, etc.)
#   - Multi-format rendering (PDF, CSV, XLSX, HTML, TXT)
#   - Multi-channel delivery (Email, SMS, Signal, Webex, Webhook)
#   - Timezone-aware scheduling (APScheduler)
#   - Full audit logging + report history
#   - Signed download URLs for secure artifact access
# ============================================================================

from .config import ReportingConfig, get_config, set_config
from .scheduler import ReportScheduler, get_scheduler
from .engine import ReportEngine, get_engine
from .routes import register_reporting_routes

__version__ = "3.0.0"
__all__ = [
    "ReportingConfig",
    "get_config",
    "set_config",
    "ReportScheduler",
    "get_scheduler",
    "ReportEngine",
    "get_engine",
    "register_reporting_routes",
]
