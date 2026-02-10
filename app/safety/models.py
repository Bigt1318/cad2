"""
FORD-CAD Safety Inspection — Database Models & Query Helpers
"""
import sqlite3
import json
import uuid
import datetime
from typing import Optional, List, Dict

DB_PATH = "cad.db"


def _get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _ts() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d")


# ================================================================
# SCHEMA INITIALIZATION
# ================================================================

def init_safety_schema():
    """Create all safety tables and seed default data."""
    conn = _get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS safety_asset_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            code TEXT UNIQUE NOT NULL,
            icon TEXT,
            inspection_fields TEXT,
            default_interval_days INTEGER DEFAULT 30,
            regulatory_standard TEXT,
            is_active INTEGER DEFAULT 1
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS safety_locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            building TEXT,
            floor TEXT,
            area TEXT,
            gis_lat REAL,
            gis_lon REAL,
            gis_floor_id TEXT,
            notes TEXT,
            is_active INTEGER DEFAULT 1
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS safety_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_type_id INTEGER REFERENCES safety_asset_types(id),
            location_id INTEGER REFERENCES safety_locations(id),
            asset_tag TEXT UNIQUE,
            qr_code TEXT UNIQUE,
            serial_number TEXT,
            manufacturer TEXT,
            model TEXT,
            install_date TEXT,
            expiration_date TEXT,
            last_inspection_date TEXT,
            next_inspection_due TEXT,
            status TEXT DEFAULT 'active',
            type_data TEXT,
            photo_url TEXT,
            notes TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS inspection_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_type_id INTEGER REFERENCES safety_asset_types(id),
            name TEXT NOT NULL,
            tier TEXT DEFAULT 'monthly',
            checklist_items TEXT,
            regulatory_reference TEXT,
            is_active INTEGER DEFAULT 1
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS inspection_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id INTEGER REFERENCES safety_assets(id),
            template_id INTEGER REFERENCES inspection_templates(id),
            inspector_unit_id TEXT,
            inspector_name TEXT,
            inspection_date TEXT,
            result TEXT DEFAULT 'pass',
            responses TEXT,
            deficiency_count INTEGER DEFAULT 0,
            notes TEXT,
            photo_urls TEXT,
            signature_url TEXT,
            duration_seconds INTEGER,
            gps_lat REAL,
            gps_lon REAL,
            created_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS deficiencies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inspection_id INTEGER REFERENCES inspection_records(id),
            asset_id INTEGER REFERENCES safety_assets(id),
            field_name TEXT,
            description TEXT,
            severity TEXT DEFAULT 'minor',
            status TEXT DEFAULT 'open',
            assigned_to TEXT,
            due_date TEXT,
            resolved_date TEXT,
            resolved_by TEXT,
            resolution_notes TEXT,
            photo_urls TEXT,
            created_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS inspection_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_type_id INTEGER REFERENCES safety_asset_types(id),
            location_id INTEGER REFERENCES safety_locations(id),
            template_id INTEGER REFERENCES inspection_templates(id),
            frequency TEXT DEFAULT 'monthly',
            day_of_week INTEGER,
            day_of_month INTEGER,
            assigned_to TEXT,
            is_active INTEGER DEFAULT 1,
            last_run TEXT,
            next_run TEXT
        )
    """)

    # Indexes
    for idx in [
        "CREATE INDEX IF NOT EXISTS idx_sa_type ON safety_assets (asset_type_id)",
        "CREATE INDEX IF NOT EXISTS idx_sa_loc ON safety_assets (location_id)",
        "CREATE INDEX IF NOT EXISTS idx_sa_status ON safety_assets (status)",
        "CREATE INDEX IF NOT EXISTS idx_sa_qr ON safety_assets (qr_code)",
        "CREATE INDEX IF NOT EXISTS idx_sa_next ON safety_assets (next_inspection_due)",
        "CREATE INDEX IF NOT EXISTS idx_ir_asset ON inspection_records (asset_id)",
        "CREATE INDEX IF NOT EXISTS idx_ir_date ON inspection_records (inspection_date)",
        "CREATE INDEX IF NOT EXISTS idx_def_asset ON deficiencies (asset_id)",
        "CREATE INDEX IF NOT EXISTS idx_def_status ON deficiencies (status)",
    ]:
        try:
            c.execute(idx)
        except Exception:
            pass

    conn.commit()

    # Seed defaults
    count = c.execute("SELECT COUNT(*) FROM safety_asset_types").fetchone()[0]
    if count == 0:
        _seed_asset_types(c)
        conn.commit()

    tpl_count = c.execute("SELECT COUNT(*) FROM inspection_templates").fetchone()[0]
    if tpl_count == 0:
        _seed_inspection_templates(c)
        conn.commit()

    # Migration: insert any new asset types that don't exist yet
    _migrate_new_types(c)
    conn.commit()

    conn.close()


# ================================================================
# MIGRATION — add new types/templates to existing DB
# ================================================================

def _migrate_new_types(cursor):
    """Insert any asset types that don't exist yet + their templates."""
    new_types = [
        ("Sprinkler Riser", "RISER", "arrow-up-circle", 30, "NFPA 25"),
        ("Standpipe", "STPIPE", "git-commit", 30, "NFPA 14"),
        ("PIV (Post Indicator Valve)", "PIV", "disc", 7, "NFPA 25"),
        ("Pumphouse", "PUMP", "activity", 7, "NFPA 20"),
    ]
    inserted_codes = []
    for name, code, icon, interval, standard in new_types:
        exists = cursor.execute(
            "SELECT id FROM safety_asset_types WHERE code = ?", (code,)
        ).fetchone()
        if not exists:
            cursor.execute("""
                INSERT INTO safety_asset_types (name, code, icon, default_interval_days, regulatory_standard, is_active)
                VALUES (?, ?, ?, ?, ?, 1)
            """, (name, code, icon, interval, standard))
            inserted_codes.append(code)

    # Seed templates for any newly-inserted types
    if inserted_codes:
        _seed_new_type_templates(cursor, inserted_codes)


def _seed_new_type_templates(cursor, codes):
    """Seed inspection templates only for the given type codes."""
    all_new = _get_new_type_templates()
    for tpl in all_new:
        if tpl["asset_type_code"] not in codes:
            continue
        row = cursor.execute(
            "SELECT id FROM safety_asset_types WHERE code = ?",
            (tpl["asset_type_code"],)
        ).fetchone()
        if not row:
            continue
        # Check template doesn't already exist
        existing = cursor.execute(
            "SELECT id FROM inspection_templates WHERE asset_type_id = ? AND name = ?",
            (row[0], tpl["name"])
        ).fetchone()
        if existing:
            continue
        cursor.execute("""
            INSERT INTO inspection_templates (asset_type_id, name, tier, checklist_items, regulatory_reference, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
        """, (row[0], tpl["name"], tpl["tier"], tpl["checklist_items"], tpl["regulatory_reference"]))


def _get_new_type_templates():
    """Templates for newer asset types (RISER, STPIPE, PIV, PUMP)."""
    return [
        # Sprinkler Riser — Monthly Visual (NFPA 25)
        {
            "asset_type_code": "RISER",
            "name": "Sprinkler Riser — Monthly Visual",
            "tier": "monthly",
            "regulatory_reference": "NFPA 25 §5.3",
            "checklist_items": json.dumps([
                {"field": "gauges_normal", "label": "System/riser gauges in normal range", "type": "pass_fail", "required": True},
                {"field": "main_valve_open", "label": "Main control valve open & sealed/locked", "type": "pass_fail", "required": True},
                {"field": "no_leaks", "label": "No visible leaks at riser or connections", "type": "pass_fail", "required": True},
                {"field": "fdc_condition", "label": "FDC caps in place / no damage", "type": "pass_fail", "required": True},
                {"field": "fdc_accessible", "label": "FDC accessible (not blocked)", "type": "pass_fail", "required": True},
                {"field": "trim_condition", "label": "Riser trim (alarm valve, retard, drains) OK", "type": "pass_fail", "required": True},
                {"field": "signage", "label": "Riser room signage visible", "type": "pass_fail", "required": True},
                {"field": "room_clear", "label": "Riser room clear of storage/obstructions", "type": "pass_fail", "required": True},
            ]),
        },
        # Standpipe — Semi-Annual (NFPA 14)
        {
            "asset_type_code": "STPIPE",
            "name": "Standpipe — Semi-Annual Inspection",
            "tier": "semi_annual",
            "regulatory_reference": "NFPA 14 §6.3",
            "checklist_items": json.dumps([
                {"field": "hose_connections", "label": "Hose connections accessible & caps in place", "type": "pass_fail", "required": True},
                {"field": "valve_condition", "label": "Hose valves operate freely", "type": "pass_fail", "required": True},
                {"field": "no_obstructions", "label": "Standpipe cabinets unobstructed", "type": "pass_fail", "required": True},
                {"field": "hose_condition", "label": "Hose condition OK (if equipped)", "type": "pass_fail", "required": False},
                {"field": "nozzle_condition", "label": "Nozzle present and functional", "type": "pass_fail", "required": False},
                {"field": "pressure_gauge", "label": "Pressure gauge in normal range", "type": "pass_fail", "required": True},
                {"field": "signage", "label": "Standpipe signage visible", "type": "pass_fail", "required": True},
                {"field": "no_damage", "label": "No visible damage or corrosion", "type": "pass_fail", "required": True},
            ]),
        },
        # PIV — Weekly (NFPA 25)
        {
            "asset_type_code": "PIV",
            "name": "PIV — Weekly Valve Check",
            "tier": "weekly",
            "regulatory_reference": "NFPA 25 §13.5",
            "checklist_items": json.dumps([
                {"field": "valve_open", "label": "PIV in full OPEN position", "type": "pass_fail", "required": True},
                {"field": "accessible", "label": "PIV accessible / not blocked", "type": "pass_fail", "required": True},
                {"field": "wrench_available", "label": "Operating wrench available", "type": "pass_fail", "required": True},
                {"field": "tamper_switch", "label": "Tamper switch functional (if installed)", "type": "pass_fail", "required": False},
                {"field": "no_damage", "label": "No visible damage to valve/post", "type": "pass_fail", "required": True},
                {"field": "signage", "label": "PIV signage visible", "type": "pass_fail", "required": True},
            ]),
        },
        # Pumphouse — Weekly (NFPA 20)
        {
            "asset_type_code": "PUMP",
            "name": "Pumphouse — Weekly Inspection",
            "tier": "weekly",
            "regulatory_reference": "NFPA 20 §8.3",
            "checklist_items": json.dumps([
                {"field": "pump_running", "label": "Pump starts and runs (no-flow test)", "type": "pass_fail", "required": True},
                {"field": "suction_pressure", "label": "Suction pressure reading normal", "type": "pass_fail", "required": True},
                {"field": "discharge_pressure", "label": "Discharge pressure reading normal", "type": "pass_fail", "required": True},
                {"field": "power_available", "label": "Power supply available (normal/emergency)", "type": "pass_fail", "required": True},
                {"field": "room_temp", "label": "Pump room temperature above 40°F", "type": "pass_fail", "required": True},
                {"field": "no_leaks", "label": "No visible leaks (packing, piping)", "type": "pass_fail", "required": True},
                {"field": "controller_normal", "label": "Controller in AUTO position, no alarms", "type": "pass_fail", "required": True},
                {"field": "ventilation", "label": "Ventilation/louvers functioning", "type": "pass_fail", "required": True},
                {"field": "fuel_level", "label": "Diesel fuel level adequate (if diesel)", "type": "pass_fail", "required": False},
                {"field": "battery_charger", "label": "Battery charger operational (if diesel)", "type": "pass_fail", "required": False},
            ]),
        },
    ]


# ================================================================
# SEED DATA
# ================================================================

def _seed_asset_types(cursor):
    """Insert default asset types."""
    types = [
        ("Fire Extinguisher", "FE", "fire-extinguisher", 30, "NFPA 10"),
        ("AED", "AED", "heart-pulse", 30, "AHA/local EMS"),
        ("Exit Sign", "EXIT", "door-open", 30, "NFPA 101"),
        ("Emergency Light", "ELIGHT", "lightbulb", 30, "NFPA 101"),
        ("Fire Alarm Pull Station", "PULL", "bell", 180, "NFPA 72"),
        ("Sprinkler System", "SPRK", "droplet", 30, "NFPA 25"),
        ("Eyewash Station", "EYE", "eye", 7, "ANSI Z358.1"),
        ("First Aid Kit", "FAK", "briefcase-medical", 30, "OSHA 1910.151"),
        ("Fire Door", "DOOR", "door-closed", 30, "NFPA 80"),
        ("Emergency Shower", "SHOWER", "shower", 7, "ANSI Z358.1"),
        ("Sprinkler Riser", "RISER", "arrow-up-circle", 30, "NFPA 25"),
        ("Standpipe", "STPIPE", "git-commit", 30, "NFPA 14"),
        ("PIV (Post Indicator Valve)", "PIV", "disc", 7, "NFPA 25"),
        ("Pumphouse", "PUMP", "activity", 7, "NFPA 20"),
    ]
    for name, code, icon, interval, standard in types:
        cursor.execute("""
            INSERT INTO safety_asset_types (name, code, icon, default_interval_days, regulatory_standard, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
        """, (name, code, icon, interval, standard))


def _seed_inspection_templates(cursor):
    """Insert default inspection templates per NFPA/OSHA standards."""
    templates = [
        # Fire Extinguisher — Monthly Visual (NFPA 10 §7.2.1)
        {
            "asset_type_code": "FE",
            "name": "Fire Extinguisher — Monthly Visual",
            "tier": "monthly",
            "regulatory_reference": "NFPA 10 §7.2.1",
            "checklist_items": json.dumps([
                {"field": "accessible", "label": "Accessible / not blocked", "type": "pass_fail", "required": True},
                {"field": "instructions_visible", "label": "Operating instructions visible", "type": "pass_fail", "required": True},
                {"field": "seal_intact", "label": "Tamper seal intact", "type": "pass_fail", "required": True},
                {"field": "pressure_gauge", "label": "Pressure gauge in green zone", "type": "pass_fail", "required": True},
                {"field": "no_damage", "label": "No visible damage or corrosion", "type": "pass_fail", "required": True},
                {"field": "fullness", "label": "Fullness verified by heft", "type": "pass_fail", "required": True},
                {"field": "bracket_secure", "label": "Mounting bracket secure", "type": "pass_fail", "required": True},
                {"field": "safety_pin", "label": "Safety pin in place", "type": "pass_fail", "required": True},
                {"field": "tag_current", "label": "Inspection tag current", "type": "pass_fail", "required": True},
            ]),
        },
        # Fire Extinguisher — Annual (NFPA 10 §7.3)
        {
            "asset_type_code": "FE",
            "name": "Fire Extinguisher — Annual",
            "tier": "annual",
            "regulatory_reference": "NFPA 10 §7.3",
            "checklist_items": json.dumps([
                {"field": "accessible", "label": "Accessible / not blocked", "type": "pass_fail", "required": True},
                {"field": "instructions_visible", "label": "Operating instructions visible", "type": "pass_fail", "required": True},
                {"field": "seal_intact", "label": "Tamper seal intact", "type": "pass_fail", "required": True},
                {"field": "pressure_gauge", "label": "Pressure gauge in green zone", "type": "pass_fail", "required": True},
                {"field": "no_damage", "label": "No visible damage or corrosion", "type": "pass_fail", "required": True},
                {"field": "fullness", "label": "Fullness verified by heft", "type": "pass_fail", "required": True},
                {"field": "bracket_secure", "label": "Mounting bracket secure", "type": "pass_fail", "required": True},
                {"field": "safety_pin", "label": "Safety pin in place", "type": "pass_fail", "required": True},
                {"field": "hose_nozzle", "label": "Hose/nozzle condition OK", "type": "pass_fail", "required": True},
                {"field": "cylinder_condition", "label": "Cylinder condition OK", "type": "pass_fail", "required": True},
                {"field": "hydrostatic_date", "label": "Hydrostatic test date (12yr)", "type": "date", "required": False},
                {"field": "internal_exam_date", "label": "Internal exam date (6yr)", "type": "date", "required": False},
                {"field": "weight_tolerance", "label": "Weight within tolerance", "type": "pass_fail", "required": True},
                {"field": "orings_gaskets", "label": "O-rings/gaskets condition OK", "type": "pass_fail", "required": True},
            ]),
        },
        # AED — Monthly Visual
        {
            "asset_type_code": "AED",
            "name": "AED — Monthly Visual",
            "tier": "monthly",
            "regulatory_reference": "AHA Guidelines",
            "checklist_items": json.dumps([
                {"field": "unit_present", "label": "AED unit present", "type": "pass_fail", "required": True},
                {"field": "status_indicator", "label": "Status indicator green/ready", "type": "pass_fail", "required": True},
                {"field": "cabinet_ok", "label": "Cabinet/case condition OK", "type": "pass_fail", "required": True},
                {"field": "pads_in_date", "label": "Electrode pads in-date", "type": "pass_fail", "required": True},
                {"field": "battery_ok", "label": "Battery status OK", "type": "pass_fail", "required": True},
                {"field": "rescue_kit", "label": "Rescue kit present", "type": "pass_fail", "required": True},
                {"field": "signage_visible", "label": "AED signage visible", "type": "pass_fail", "required": True},
            ]),
        },
        # Exit Sign — Monthly (NFPA 101)
        {
            "asset_type_code": "EXIT",
            "name": "Exit Sign — Monthly Visual",
            "tier": "monthly",
            "regulatory_reference": "NFPA 101 §7.10",
            "checklist_items": json.dumps([
                {"field": "illuminated", "label": "Sign illuminated", "type": "pass_fail", "required": True},
                {"field": "no_damage", "label": "No physical damage", "type": "pass_fail", "required": True},
                {"field": "unobstructed", "label": "Sign unobstructed / visible", "type": "pass_fail", "required": True},
                {"field": "battery_test_30s", "label": "30-second battery test passed", "type": "pass_fail", "required": True},
            ]),
        },
        # Exit Sign/Emergency Light — Annual (NFPA 101 §7.9.3)
        {
            "asset_type_code": "ELIGHT",
            "name": "Emergency Light — Annual 90-min Test",
            "tier": "annual",
            "regulatory_reference": "NFPA 101 §7.9.3",
            "checklist_items": json.dumps([
                {"field": "battery_test_90min", "label": "90-minute battery test passed", "type": "pass_fail", "required": True},
                {"field": "all_lamps_working", "label": "All lamps functional", "type": "pass_fail", "required": True},
                {"field": "charging_system", "label": "Charging system operational", "type": "pass_fail", "required": True},
                {"field": "physical_condition", "label": "Physical condition OK", "type": "pass_fail", "required": True},
            ]),
        },
        # Eyewash Station — Weekly (ANSI Z358.1)
        {
            "asset_type_code": "EYE",
            "name": "Eyewash Station — Weekly Flush",
            "tier": "weekly",
            "regulatory_reference": "ANSI Z358.1",
            "checklist_items": json.dumps([
                {"field": "flush_3min", "label": "3-minute flush test completed", "type": "pass_fail", "required": True},
                {"field": "both_nozzles", "label": "Both nozzles flowing", "type": "pass_fail", "required": True},
                {"field": "water_clear", "label": "Water runs clear", "type": "pass_fail", "required": True},
                {"field": "area_clear", "label": "Area clear 3ft radius", "type": "pass_fail", "required": True},
                {"field": "signage", "label": "Signage visible", "type": "pass_fail", "required": True},
                {"field": "dust_covers", "label": "Dust covers in place", "type": "pass_fail", "required": True},
            ]),
        },
        # Fire Alarm Pull Station — Semi-Annual (NFPA 72)
        {
            "asset_type_code": "PULL",
            "name": "Fire Alarm Pull Station — Semi-Annual",
            "tier": "semi_annual",
            "regulatory_reference": "NFPA 72 §14.4.5",
            "checklist_items": json.dumps([
                {"field": "physical_condition", "label": "Physical condition OK", "type": "pass_fail", "required": True},
                {"field": "functional_test", "label": "Functional test passed", "type": "pass_fail", "required": True},
                {"field": "resets_properly", "label": "Resets properly after activation", "type": "pass_fail", "required": True},
                {"field": "signage", "label": "Signage visible", "type": "pass_fail", "required": True},
            ]),
        },
        # Sprinkler — Monthly Visual (NFPA 25)
        {
            "asset_type_code": "SPRK",
            "name": "Sprinkler System — Monthly Visual",
            "tier": "monthly",
            "regulatory_reference": "NFPA 25 §5.2",
            "checklist_items": json.dumps([
                {"field": "gauges_normal", "label": "Gauges in normal range", "type": "pass_fail", "required": True},
                {"field": "valves_open", "label": "Control valves open and sealed", "type": "pass_fail", "required": True},
                {"field": "no_leaks", "label": "No visible leaks", "type": "pass_fail", "required": True},
                {"field": "heads_unobstructed", "label": "Heads unobstructed (18\" clearance)", "type": "pass_fail", "required": True},
                {"field": "no_painted_heads", "label": "No painted/loaded heads", "type": "pass_fail", "required": True},
                {"field": "spare_cabinet", "label": "Spare head cabinet stocked", "type": "pass_fail", "required": True},
            ]),
        },
        # Emergency Shower — Weekly (ANSI Z358.1)
        {
            "asset_type_code": "SHOWER",
            "name": "Emergency Shower — Weekly Test",
            "tier": "weekly",
            "regulatory_reference": "ANSI Z358.1",
            "checklist_items": json.dumps([
                {"field": "flow_test", "label": "Flow test completed", "type": "pass_fail", "required": True},
                {"field": "water_clear", "label": "Water runs clear", "type": "pass_fail", "required": True},
                {"field": "area_clear", "label": "Area clear / accessible", "type": "pass_fail", "required": True},
                {"field": "signage", "label": "Signage visible", "type": "pass_fail", "required": True},
                {"field": "drain_ok", "label": "Drain functioning", "type": "pass_fail", "required": True},
            ]),
        },
        # First Aid Kit — Monthly
        {
            "asset_type_code": "FAK",
            "name": "First Aid Kit — Monthly Check",
            "tier": "monthly",
            "regulatory_reference": "OSHA 1910.151",
            "checklist_items": json.dumps([
                {"field": "kit_present", "label": "Kit present and accessible", "type": "pass_fail", "required": True},
                {"field": "sealed", "label": "Seal intact or contents checked", "type": "pass_fail", "required": True},
                {"field": "supplies_stocked", "label": "Supplies adequately stocked", "type": "pass_fail", "required": True},
                {"field": "no_expired", "label": "No expired items", "type": "pass_fail", "required": True},
                {"field": "signage", "label": "Signage visible", "type": "pass_fail", "required": True},
            ]),
        },
        # Fire Door — Monthly
        {
            "asset_type_code": "DOOR",
            "name": "Fire Door — Monthly Visual",
            "tier": "monthly",
            "regulatory_reference": "NFPA 80 §5.2",
            "checklist_items": json.dumps([
                {"field": "closes_fully", "label": "Door closes and latches fully", "type": "pass_fail", "required": True},
                {"field": "no_obstructions", "label": "No obstructions / wedges", "type": "pass_fail", "required": True},
                {"field": "no_damage", "label": "No visible damage", "type": "pass_fail", "required": True},
                {"field": "hardware_ok", "label": "Hardware functioning", "type": "pass_fail", "required": True},
                {"field": "gaps_ok", "label": "Door gaps within tolerance", "type": "pass_fail", "required": True},
                {"field": "signage", "label": "Fire door signage present", "type": "pass_fail", "required": True},
            ]),
        },
    ] + _get_new_type_templates()

    for tpl in templates:
        # Look up asset_type_id by code
        row = cursor.execute(
            "SELECT id FROM safety_asset_types WHERE code = ?",
            (tpl["asset_type_code"],)
        ).fetchone()
        if not row:
            continue
        type_id = row[0]
        cursor.execute("""
            INSERT INTO inspection_templates (asset_type_id, name, tier, checklist_items, regulatory_reference, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
        """, (type_id, tpl["name"], tpl["tier"], tpl["checklist_items"], tpl["regulatory_reference"]))


# ================================================================
# ASSET TYPES CRUD
# ================================================================

def get_asset_types(active_only: bool = True) -> List[Dict]:
    conn = _get_conn()
    sql = "SELECT * FROM safety_asset_types"
    if active_only:
        sql += " WHERE is_active = 1"
    sql += " ORDER BY name"
    rows = conn.execute(sql).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_asset_type(type_id: int) -> Optional[Dict]:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM safety_asset_types WHERE id = ?", (type_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_asset_type(data: dict) -> int:
    conn = _get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO safety_asset_types (name, code, icon, inspection_fields, default_interval_days, regulatory_standard, is_active)
        VALUES (?, ?, ?, ?, ?, ?, 1)
    """, (data["name"], data["code"], data.get("icon"), data.get("inspection_fields"),
          data.get("default_interval_days", 30), data.get("regulatory_standard")))
    tid = c.lastrowid
    conn.commit()
    conn.close()
    return tid


# ================================================================
# LOCATIONS CRUD
# ================================================================

def get_locations(active_only: bool = True, building: str = None, floor: str = None) -> List[Dict]:
    conn = _get_conn()
    sql = "SELECT * FROM safety_locations WHERE 1=1"
    params = []
    if active_only:
        sql += " AND is_active = 1"
    if building:
        sql += " AND building = ?"
        params.append(building)
    if floor:
        sql += " AND floor = ?"
        params.append(floor)
    sql += " ORDER BY building, floor, area, name"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_location(loc_id: int) -> Optional[Dict]:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM safety_locations WHERE id = ?", (loc_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_location(data: dict) -> int:
    conn = _get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO safety_locations (name, building, floor, area, gis_lat, gis_lon, gis_floor_id, notes, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
    """, (data["name"], data.get("building"), data.get("floor"), data.get("area"),
          data.get("gis_lat"), data.get("gis_lon"), data.get("gis_floor_id"), data.get("notes")))
    lid = c.lastrowid
    conn.commit()
    conn.close()
    return lid


def update_location(loc_id: int, data: dict) -> bool:
    conn = _get_conn()
    sets, params = [], []
    for key in ("name", "building", "floor", "area", "gis_lat", "gis_lon", "gis_floor_id", "notes"):
        if key in data:
            sets.append(f"{key} = ?")
            params.append(data[key])
    if not sets:
        conn.close()
        return False
    params.append(loc_id)
    conn.execute(f"UPDATE safety_locations SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()
    conn.close()
    return True


def delete_location(loc_id: int) -> bool:
    conn = _get_conn()
    conn.execute("UPDATE safety_locations SET is_active = 0 WHERE id = ?", (loc_id,))
    conn.commit()
    conn.close()
    return True


# ================================================================
# ASSETS CRUD
# ================================================================

def get_assets(
    asset_type_id: int = None, location_id: int = None,
    status: str = None, overdue: bool = False,
    search: str = None, limit: int = 500
) -> List[Dict]:
    conn = _get_conn()
    sql = """
        SELECT a.*, t.name as type_name, t.code as type_code, t.icon as type_icon,
               l.name as location_name, l.building, l.floor, l.area
        FROM safety_assets a
        LEFT JOIN safety_asset_types t ON a.asset_type_id = t.id
        LEFT JOIN safety_locations l ON a.location_id = l.id
        WHERE a.status != 'retired'
    """
    params = []
    if asset_type_id:
        sql += " AND a.asset_type_id = ?"
        params.append(asset_type_id)
    if location_id:
        sql += " AND a.location_id = ?"
        params.append(location_id)
    if status:
        sql += " AND a.status = ?"
        params.append(status)
    if overdue:
        sql += " AND a.next_inspection_due < ? AND a.status != 'retired'"
        params.append(_today())
    if search:
        sql += " AND (a.asset_tag LIKE ? OR a.serial_number LIKE ? OR t.name LIKE ?)"
        s = f"%{search}%"
        params.extend([s, s, s])
    sql += " ORDER BY a.next_inspection_due ASC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_asset(asset_id: int) -> Optional[Dict]:
    conn = _get_conn()
    row = conn.execute("""
        SELECT a.*, t.name as type_name, t.code as type_code, t.icon as type_icon,
               t.default_interval_days,
               l.name as location_name, l.building, l.floor, l.area
        FROM safety_assets a
        LEFT JOIN safety_asset_types t ON a.asset_type_id = t.id
        LEFT JOIN safety_locations l ON a.location_id = l.id
        WHERE a.id = ?
    """, (asset_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_asset_by_qr(qr_code: str) -> Optional[Dict]:
    conn = _get_conn()
    row = conn.execute("""
        SELECT a.*, t.name as type_name, t.code as type_code, t.icon as type_icon,
               t.default_interval_days,
               l.name as location_name, l.building, l.floor, l.area
        FROM safety_assets a
        LEFT JOIN safety_asset_types t ON a.asset_type_id = t.id
        LEFT JOIN safety_locations l ON a.location_id = l.id
        WHERE a.qr_code = ?
    """, (qr_code,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_asset(data: dict) -> int:
    conn = _get_conn()
    c = conn.cursor()
    ts = _ts()
    qr = data.get("qr_code") or str(uuid.uuid4())

    # Auto-generate asset tag if not provided
    asset_tag = data.get("asset_tag")
    if not asset_tag:
        type_row = c.execute("SELECT code FROM safety_asset_types WHERE id = ?",
                             (data["asset_type_id"],)).fetchone()
        code = type_row[0] if type_row else "XX"
        count = c.execute("SELECT COUNT(*) FROM safety_assets WHERE asset_type_id = ?",
                          (data["asset_type_id"],)).fetchone()[0]
        asset_tag = f"{code}-{count + 1:03d}"

    # Calculate next_inspection_due
    next_due = data.get("next_inspection_due")
    if not next_due:
        type_row = c.execute("SELECT default_interval_days FROM safety_asset_types WHERE id = ?",
                             (data["asset_type_id"],)).fetchone()
        interval = type_row[0] if type_row else 30
        next_due = (datetime.datetime.now() + datetime.timedelta(days=interval)).strftime("%Y-%m-%d")

    c.execute("""
        INSERT INTO safety_assets
        (asset_type_id, location_id, asset_tag, qr_code, serial_number, manufacturer, model,
         install_date, expiration_date, last_inspection_date, next_inspection_due, status,
         type_data, photo_url, notes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data["asset_type_id"], data.get("location_id"), asset_tag, qr,
        data.get("serial_number"), data.get("manufacturer"), data.get("model"),
        data.get("install_date"), data.get("expiration_date"),
        data.get("last_inspection_date"), next_due,
        data.get("status", "active"),
        json.dumps(data["type_data"]) if data.get("type_data") else None,
        data.get("photo_url"), data.get("notes"), ts, ts
    ))
    aid = c.lastrowid
    conn.commit()
    conn.close()
    return aid


def update_asset(asset_id: int, data: dict) -> bool:
    conn = _get_conn()
    sets, params = [], []
    for key in ("asset_type_id", "location_id", "asset_tag", "serial_number",
                "manufacturer", "model", "install_date", "expiration_date",
                "last_inspection_date", "next_inspection_due", "status",
                "photo_url", "notes"):
        if key in data:
            sets.append(f"{key} = ?")
            params.append(data[key])
    if "type_data" in data:
        sets.append("type_data = ?")
        params.append(json.dumps(data["type_data"]) if data["type_data"] else None)
    sets.append("updated_at = ?")
    params.append(_ts())
    params.append(asset_id)
    conn.execute(f"UPDATE safety_assets SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()
    conn.close()
    return True


def delete_asset(asset_id: int) -> bool:
    """Soft-delete: set status to retired."""
    conn = _get_conn()
    conn.execute("UPDATE safety_assets SET status = 'retired', updated_at = ? WHERE id = ?",
                 (_ts(), asset_id))
    conn.commit()
    conn.close()
    return True


# ================================================================
# INSPECTION TEMPLATES
# ================================================================

def get_templates(asset_type_id: int = None, active_only: bool = True) -> List[Dict]:
    conn = _get_conn()
    sql = "SELECT * FROM inspection_templates WHERE 1=1"
    params = []
    if active_only:
        sql += " AND is_active = 1"
    if asset_type_id:
        sql += " AND asset_type_id = ?"
        params.append(asset_type_id)
    sql += " ORDER BY asset_type_id, tier"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_template(tpl_id: int) -> Optional[Dict]:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM inspection_templates WHERE id = ?", (tpl_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ================================================================
# INSPECTION RECORDS
# ================================================================

def get_inspections(
    asset_id: int = None, inspector: str = None,
    result: str = None, date_from: str = None, date_to: str = None,
    limit: int = 200
) -> List[Dict]:
    conn = _get_conn()
    sql = """
        SELECT r.*, a.asset_tag, t.name as template_name,
               at.name as type_name, l.name as location_name
        FROM inspection_records r
        LEFT JOIN safety_assets a ON r.asset_id = a.id
        LEFT JOIN inspection_templates t ON r.template_id = t.id
        LEFT JOIN safety_asset_types at ON a.asset_type_id = at.id
        LEFT JOIN safety_locations l ON a.location_id = l.id
        WHERE 1=1
    """
    params = []
    if asset_id:
        sql += " AND r.asset_id = ?"
        params.append(asset_id)
    if inspector:
        sql += " AND (r.inspector_unit_id = ? OR r.inspector_name LIKE ?)"
        params.extend([inspector, f"%{inspector}%"])
    if result:
        sql += " AND r.result = ?"
        params.append(result)
    if date_from:
        sql += " AND r.inspection_date >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND r.inspection_date <= ?"
        params.append(date_to)
    sql += " ORDER BY r.inspection_date DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_inspection(insp_id: int) -> Optional[Dict]:
    conn = _get_conn()
    row = conn.execute("""
        SELECT r.*, a.asset_tag, t.name as template_name,
               at.name as type_name, l.name as location_name
        FROM inspection_records r
        LEFT JOIN safety_assets a ON r.asset_id = a.id
        LEFT JOIN inspection_templates t ON r.template_id = t.id
        LEFT JOIN safety_asset_types at ON a.asset_type_id = at.id
        LEFT JOIN safety_locations l ON a.location_id = l.id
        WHERE r.id = ?
    """, (insp_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_inspection(data: dict) -> int:
    """Submit an inspection. Auto-updates asset dates and creates deficiencies for failures."""
    conn = _get_conn()
    c = conn.cursor()
    ts = _ts()
    today = _today()

    # Parse responses to count deficiencies
    responses = data.get("responses", {})
    if isinstance(responses, str):
        responses = json.loads(responses)

    deficiency_count = 0
    failed_fields = []
    for field, value in responses.items():
        if value in ("fail", "no", False, 0, "0"):
            deficiency_count += 1
            failed_fields.append(field)

    result = data.get("result")
    if not result:
        if deficiency_count == 0:
            result = "pass"
        elif deficiency_count <= 2:
            result = "partial"
        else:
            result = "fail"

    c.execute("""
        INSERT INTO inspection_records
        (asset_id, template_id, inspector_unit_id, inspector_name, inspection_date,
         result, responses, deficiency_count, notes, photo_urls, signature_url,
         duration_seconds, gps_lat, gps_lon, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data["asset_id"], data.get("template_id"),
        data.get("inspector_unit_id"), data.get("inspector_name"),
        data.get("inspection_date", today), result,
        json.dumps(responses), deficiency_count,
        data.get("notes"),
        json.dumps(data["photo_urls"]) if data.get("photo_urls") else None,
        data.get("signature_url"), data.get("duration_seconds"),
        data.get("gps_lat"), data.get("gps_lon"), ts
    ))
    insp_id = c.lastrowid

    # Update asset's last/next inspection dates
    asset = c.execute("SELECT asset_type_id FROM safety_assets WHERE id = ?",
                      (data["asset_id"],)).fetchone()
    if asset:
        type_row = c.execute("SELECT default_interval_days FROM safety_asset_types WHERE id = ?",
                             (asset[0],)).fetchone()
        interval = type_row[0] if type_row else 30
        next_due = (datetime.datetime.now() + datetime.timedelta(days=interval)).strftime("%Y-%m-%d")

        new_status = "active" if result == "pass" else "deficient"
        c.execute("""
            UPDATE safety_assets
            SET last_inspection_date = ?, next_inspection_due = ?, status = ?, updated_at = ?
            WHERE id = ?
        """, (today, next_due, new_status, ts, data["asset_id"]))

    # Auto-create deficiencies for failed fields
    if failed_fields:
        # Get template checklist for labels
        labels = {}
        if data.get("template_id"):
            tpl = c.execute("SELECT checklist_items FROM inspection_templates WHERE id = ?",
                            (data["template_id"],)).fetchone()
            if tpl and tpl[0]:
                items = json.loads(tpl[0])
                labels = {item["field"]: item["label"] for item in items}

        for field in failed_fields:
            label = labels.get(field, field)
            c.execute("""
                INSERT INTO deficiencies
                (inspection_id, asset_id, field_name, description, severity, status, created_at)
                VALUES (?, ?, ?, ?, 'minor', 'open', ?)
            """, (insp_id, data["asset_id"], field, f"Failed: {label}", ts))

    conn.commit()
    conn.close()
    return insp_id


def get_pending_inspections(days_ahead: int = 7) -> List[Dict]:
    """Get assets due or overdue for inspection."""
    conn = _get_conn()
    cutoff = (datetime.datetime.now() + datetime.timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    rows = conn.execute("""
        SELECT a.*, t.name as type_name, t.code as type_code,
               l.name as location_name, l.building, l.floor
        FROM safety_assets a
        LEFT JOIN safety_asset_types t ON a.asset_type_id = t.id
        LEFT JOIN safety_locations l ON a.location_id = l.id
        WHERE a.status != 'retired'
          AND a.next_inspection_due <= ?
        ORDER BY a.next_inspection_due ASC
    """, (cutoff,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ================================================================
# DEFICIENCIES
# ================================================================

def get_deficiencies(
    status: str = None, severity: str = None,
    asset_id: int = None, limit: int = 200
) -> List[Dict]:
    conn = _get_conn()
    sql = """
        SELECT d.*, a.asset_tag, at.name as type_name, l.name as location_name
        FROM deficiencies d
        LEFT JOIN safety_assets a ON d.asset_id = a.id
        LEFT JOIN safety_asset_types at ON a.asset_type_id = at.id
        LEFT JOIN safety_locations l ON a.location_id = l.id
        WHERE 1=1
    """
    params = []
    if status:
        sql += " AND d.status = ?"
        params.append(status)
    if severity:
        sql += " AND d.severity = ?"
        params.append(severity)
    if asset_id:
        sql += " AND d.asset_id = ?"
        params.append(asset_id)
    sql += " ORDER BY d.created_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_deficiency(def_id: int) -> Optional[Dict]:
    conn = _get_conn()
    row = conn.execute("""
        SELECT d.*, a.asset_tag, at.name as type_name, l.name as location_name
        FROM deficiencies d
        LEFT JOIN safety_assets a ON d.asset_id = a.id
        LEFT JOIN safety_asset_types at ON a.asset_type_id = at.id
        LEFT JOIN safety_locations l ON a.location_id = l.id
        WHERE d.id = ?
    """, (def_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_deficiency(def_id: int, data: dict) -> bool:
    conn = _get_conn()
    sets, params = [], []
    for key in ("severity", "status", "assigned_to", "due_date",
                "resolved_date", "resolved_by", "resolution_notes", "description"):
        if key in data:
            sets.append(f"{key} = ?")
            params.append(data[key])
    if "photo_urls" in data:
        sets.append("photo_urls = ?")
        params.append(json.dumps(data["photo_urls"]) if data["photo_urls"] else None)
    if not sets:
        conn.close()
        return False
    params.append(def_id)
    conn.execute(f"UPDATE deficiencies SET {', '.join(sets)} WHERE id = ?", params)

    # If resolved, check if all deficiencies for that asset are resolved
    if data.get("status") == "resolved":
        row = conn.execute("SELECT asset_id FROM deficiencies WHERE id = ?", (def_id,)).fetchone()
        if row:
            open_count = conn.execute(
                "SELECT COUNT(*) FROM deficiencies WHERE asset_id = ? AND status IN ('open','in_progress')",
                (row[0],)
            ).fetchone()[0]
            if open_count == 0:
                conn.execute("UPDATE safety_assets SET status = 'active', updated_at = ? WHERE id = ?",
                             (_ts(), row[0]))

    conn.commit()
    conn.close()
    return True


def get_deficiency_dashboard() -> Dict:
    """Summary counts by severity and status."""
    conn = _get_conn()
    result = {"by_severity": {}, "by_status": {}, "total_open": 0}

    for sev in ("critical", "major", "minor"):
        count = conn.execute(
            "SELECT COUNT(*) FROM deficiencies WHERE severity = ? AND status IN ('open','in_progress')",
            (sev,)
        ).fetchone()[0]
        result["by_severity"][sev] = count

    for st in ("open", "in_progress", "resolved", "deferred"):
        count = conn.execute(
            "SELECT COUNT(*) FROM deficiencies WHERE status = ?", (st,)
        ).fetchone()[0]
        result["by_status"][st] = count

    result["total_open"] = conn.execute(
        "SELECT COUNT(*) FROM deficiencies WHERE status IN ('open','in_progress')"
    ).fetchone()[0]
    conn.close()
    return result


# ================================================================
# DASHBOARD / COMPLIANCE
# ================================================================

def get_dashboard_stats() -> Dict:
    """Compliance overview statistics."""
    conn = _get_conn()
    today = _today()

    total = conn.execute(
        "SELECT COUNT(*) FROM safety_assets WHERE status != 'retired'"
    ).fetchone()[0]

    overdue = conn.execute(
        "SELECT COUNT(*) FROM safety_assets WHERE status != 'retired' AND next_inspection_due < ?",
        (today,)
    ).fetchone()[0]

    compliant = total - overdue if total > 0 else 0
    pct = round((compliant / total) * 100, 1) if total > 0 else 100.0

    open_deficiencies = conn.execute(
        "SELECT COUNT(*) FROM deficiencies WHERE status IN ('open','in_progress')"
    ).fetchone()[0]

    critical_deficiencies = conn.execute(
        "SELECT COUNT(*) FROM deficiencies WHERE severity = 'critical' AND status IN ('open','in_progress')"
    ).fetchone()[0]

    inspections_30d = conn.execute(
        "SELECT COUNT(*) FROM inspection_records WHERE inspection_date >= date('now', '-30 days')"
    ).fetchone()[0]

    # By type
    by_type = []
    type_rows = conn.execute("""
        SELECT t.name, t.code, COUNT(a.id) as total,
               SUM(CASE WHEN a.next_inspection_due < ? THEN 1 ELSE 0 END) as overdue_count
        FROM safety_asset_types t
        LEFT JOIN safety_assets a ON a.asset_type_id = t.id AND a.status != 'retired'
        WHERE t.is_active = 1
        GROUP BY t.id
        ORDER BY t.name
    """, (today,)).fetchall()
    for r in type_rows:
        row = dict(r)
        row["compliant_count"] = row["total"] - row["overdue_count"]
        row["pct"] = round((row["compliant_count"] / row["total"]) * 100, 1) if row["total"] > 0 else 100.0
        by_type.append(row)

    conn.close()
    return {
        "total_assets": total,
        "compliant": compliant,
        "compliant_pct": pct,
        "overdue": overdue,
        "open_deficiencies": open_deficiencies,
        "critical_deficiencies": critical_deficiencies,
        "inspections_30d": inspections_30d,
        "by_type": by_type,
    }


def get_compliance_report(group_by: str = "type") -> List[Dict]:
    """Compliance breakdown by type or location."""
    conn = _get_conn()
    today = _today()

    if group_by == "location":
        rows = conn.execute("""
            SELECT l.name as group_name, l.building, COUNT(a.id) as total,
                   SUM(CASE WHEN a.next_inspection_due < ? THEN 1 ELSE 0 END) as overdue
            FROM safety_locations l
            LEFT JOIN safety_assets a ON a.location_id = l.id AND a.status != 'retired'
            WHERE l.is_active = 1
            GROUP BY l.id ORDER BY l.building, l.name
        """, (today,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT t.name as group_name, t.code, COUNT(a.id) as total,
                   SUM(CASE WHEN a.next_inspection_due < ? THEN 1 ELSE 0 END) as overdue
            FROM safety_asset_types t
            LEFT JOIN safety_assets a ON a.asset_type_id = t.id AND a.status != 'retired'
            WHERE t.is_active = 1
            GROUP BY t.id ORDER BY t.name
        """, (today,)).fetchall()

    result = []
    for r in rows:
        d = dict(r)
        d["compliant"] = d["total"] - d["overdue"]
        d["pct"] = round((d["compliant"] / d["total"]) * 100, 1) if d["total"] > 0 else 100.0
        result.append(d)
    conn.close()
    return result


# ================================================================
# SCHEDULES
# ================================================================

def get_schedules() -> List[Dict]:
    conn = _get_conn()
    rows = conn.execute("""
        SELECT s.*, t.name as type_name, l.name as location_name, tpl.name as template_name
        FROM inspection_schedules s
        LEFT JOIN safety_asset_types t ON s.asset_type_id = t.id
        LEFT JOIN safety_locations l ON s.location_id = l.id
        LEFT JOIN inspection_templates tpl ON s.template_id = tpl.id
        ORDER BY s.id
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_schedule(data: dict) -> int:
    conn = _get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO inspection_schedules
        (asset_type_id, location_id, template_id, frequency, day_of_week, day_of_month,
         assigned_to, is_active, next_run)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
    """, (
        data.get("asset_type_id"), data.get("location_id"), data.get("template_id"),
        data.get("frequency", "monthly"), data.get("day_of_week"), data.get("day_of_month"),
        data.get("assigned_to"), data.get("next_run")
    ))
    sid = c.lastrowid
    conn.commit()
    conn.close()
    return sid


def update_schedule(sched_id: int, data: dict) -> bool:
    conn = _get_conn()
    sets, params = [], []
    for key in ("asset_type_id", "location_id", "template_id", "frequency",
                "day_of_week", "day_of_month", "assigned_to", "is_active",
                "last_run", "next_run"):
        if key in data:
            sets.append(f"{key} = ?")
            params.append(data[key])
    if not sets:
        conn.close()
        return False
    params.append(sched_id)
    conn.execute(f"UPDATE inspection_schedules SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()
    conn.close()
    return True


def delete_schedule(sched_id: int) -> bool:
    conn = _get_conn()
    conn.execute("DELETE FROM inspection_schedules WHERE id = ?", (sched_id,))
    conn.commit()
    conn.close()
    return True
