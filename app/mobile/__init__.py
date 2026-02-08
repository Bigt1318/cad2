"""
FORD-CAD Mobile Module
Extended mobile MDT with timeline, chat, and photo upload.
"""
from .routes import register_mobile_routes
from .models import init_mobile_schema

__all__ = [
    "register_mobile_routes",
    "init_mobile_schema",
]
