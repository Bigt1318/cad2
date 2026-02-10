"""
FORD-CAD Safety Inspection & Maintenance Tracking Module
Track inspections of fire extinguishers, AEDs, exit signs, emergency lighting,
fire alarms, sprinkler systems, eyewash stations, and other safety equipment.
"""
from .routes import register_safety_routes
from .models import init_safety_schema

__all__ = [
    "register_safety_routes",
    "init_safety_schema",
]
