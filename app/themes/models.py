import sqlite3
import json
import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent / "cad.db"

def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def init_schema():
    """Create user_themes table if not exists."""
    conn = get_db()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_themes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                slot INTEGER NOT NULL DEFAULT 1,
                name TEXT NOT NULL DEFAULT 'My Theme',
                tokens_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_themes_user_slot
            ON user_themes(user_id, slot)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_theme_active (
                user_id TEXT PRIMARY KEY,
                active_slot INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.commit()
    finally:
        conn.close()

def get_active_slot(user_id: str) -> int:
    """Get active theme slot for user. 0 = system default."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT active_slot FROM user_theme_active WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        return row["active_slot"] if row else 0
    finally:
        conn.close()

def set_active_slot(user_id: str, slot: int):
    """Set active theme slot for user."""
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO user_theme_active (user_id, active_slot) VALUES (?, ?)
               ON CONFLICT(user_id) DO UPDATE SET active_slot = excluded.active_slot""",
            (user_id, slot)
        )
        conn.commit()
    finally:
        conn.close()

def get_theme(user_id: str, slot: int) -> dict | None:
    """Get a single theme by user + slot."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM user_themes WHERE user_id = ? AND slot = ?",
            (user_id, slot)
        ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "slot": row["slot"],
            "name": row["name"],
            "tokens": json.loads(row["tokens_json"]),
            "updated_at": row["updated_at"]
        }
    finally:
        conn.close()

def get_all_themes(user_id: str) -> list:
    """Get all themes for a user (up to 5 slots)."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM user_themes WHERE user_id = ? ORDER BY slot",
            (user_id,)
        ).fetchall()
        return [{
            "id": r["id"],
            "user_id": r["user_id"],
            "slot": r["slot"],
            "name": r["name"],
            "tokens": json.loads(r["tokens_json"]),
            "updated_at": r["updated_at"]
        } for r in rows]
    finally:
        conn.close()

def save_theme(user_id: str, slot: int, name: str, tokens: dict):
    """Save (upsert) a theme for user+slot."""
    now = datetime.datetime.now().isoformat()
    tokens_json = json.dumps(tokens)
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM user_themes WHERE user_id = ? AND slot = ?",
            (user_id, slot)
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE user_themes SET name = ?, tokens_json = ?, updated_at = ?
                   WHERE user_id = ? AND slot = ?""",
                (name, tokens_json, now, user_id, slot)
            )
        else:
            conn.execute(
                """INSERT INTO user_themes (user_id, slot, name, tokens_json, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, slot, name, tokens_json, now)
            )
        conn.commit()
    finally:
        conn.close()

def delete_theme(user_id: str, slot: int):
    """Delete a theme (reset slot)."""
    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM user_themes WHERE user_id = ? AND slot = ?",
            (user_id, slot)
        )
        # If active slot was this one, reset to default
        conn.execute(
            """UPDATE user_theme_active SET active_slot = 0
               WHERE user_id = ? AND active_slot = ?""",
            (user_id, slot)
        )
        conn.commit()
    finally:
        conn.close()

def duplicate_theme(user_id: str, from_slot: int, to_slot: int):
    """Copy theme from one slot to another."""
    source = get_theme(user_id, from_slot)
    if not source:
        return False
    save_theme(user_id, to_slot, source["name"] + " (Copy)", source["tokens"])
    return True

# Default theme presets
DEFAULT_PRESETS = {
    "Ford Dark": {
        "--cad-bg-app": "#0f172a",
        "--cad-bg-surface": "#1e293b",
        "--cad-bg-elevated": "#334155",
        "--cad-bg-panel": "#1e293b",
        "--cad-bg-header": "linear-gradient(135deg, #003478 0%, #1351a3 100%)",
        "--cad-bg-hover": "#334155",
        "--cad-bg-active": "#1e3a5f",
        "--cad-text-primary": "#e2e8f0",
        "--cad-text-secondary": "#94a3b8",
        "--cad-text-muted": "#64748b",
        "--cad-text-on-dark": "#ffffff",
        "--cad-text-on-brand": "#ffffff",
        "--cad-text-link": "#60a5fa",
        "--cad-border-default": "#475569",
        "--cad-border-light": "#334155",
        "--cad-border-emphasis": "#64748b",
        "--cad-accent-primary": "#3b82f6",
        "--cad-accent-secondary": "#6366f1",
        "--cad-success": "#22c55e",
        "--cad-success-bg": "#14532d",
        "--cad-warning": "#eab308",
        "--cad-warning-bg": "#422006",
        "--cad-danger": "#ef4444",
        "--cad-danger-bg": "#450a0a",
        "--cad-info": "#3b82f6",
        "--cad-info-bg": "#1e3a5f",
        "--cad-shadow-sm": "0 1px 2px rgba(0,0,0,0.3)",
        "--cad-shadow-md": "0 4px 6px rgba(0,0,0,0.4)",
        "--cad-font-ui": "Inter, sans-serif",
        "--cad-font-header": "Oswald, sans-serif",
        "--cad-font-unit": "Rajdhani, sans-serif",
        "--cad-font-incident": "Inter, sans-serif",
        "--cad-font-narrative": "SourceSans3, sans-serif",
        "--cad-font-mono": "JetBrainsMono, monospace"
    },
    "Ford Light": {
        "--cad-bg-app": "#f1f5f9",
        "--cad-bg-surface": "#ffffff",
        "--cad-bg-elevated": "#f8fafc",
        "--cad-bg-panel": "#ffffff",
        "--cad-bg-header": "linear-gradient(135deg, #003478 0%, #1351a3 100%)",
        "--cad-bg-hover": "#e2e8f0",
        "--cad-bg-active": "#dbeafe",
        "--cad-text-primary": "#0f172a",
        "--cad-text-secondary": "#475569",
        "--cad-text-muted": "#64748b",
        "--cad-text-on-dark": "#ffffff",
        "--cad-text-on-brand": "#ffffff",
        "--cad-text-link": "#1d4ed8",
        "--cad-border-default": "#cbd5e1",
        "--cad-border-light": "#e2e8f0",
        "--cad-border-emphasis": "#94a3b8",
        "--cad-accent-primary": "#2563eb",
        "--cad-accent-secondary": "#7c3aed",
        "--cad-success": "#16a34a",
        "--cad-success-bg": "#dcfce7",
        "--cad-warning": "#ca8a04",
        "--cad-warning-bg": "#fef9c3",
        "--cad-danger": "#dc2626",
        "--cad-danger-bg": "#fee2e2",
        "--cad-info": "#2563eb",
        "--cad-info-bg": "#dbeafe",
        "--cad-shadow-sm": "0 1px 2px rgba(0,0,0,0.05)",
        "--cad-shadow-md": "0 4px 6px rgba(0,0,0,0.07)",
        "--cad-font-ui": "Inter, sans-serif",
        "--cad-font-header": "Oswald, sans-serif",
        "--cad-font-unit": "Rajdhani, sans-serif",
        "--cad-font-incident": "Inter, sans-serif",
        "--cad-font-narrative": "SourceSans3, sans-serif",
        "--cad-font-mono": "JetBrainsMono, monospace"
    },
    "Fire Red": {
        "--cad-bg-app": "#1a0a0a",
        "--cad-bg-surface": "#2a1010",
        "--cad-bg-elevated": "#3a1515",
        "--cad-bg-panel": "#2a1010",
        "--cad-bg-header": "linear-gradient(135deg, #7f1d1d 0%, #991b1b 100%)",
        "--cad-bg-hover": "#3a1515",
        "--cad-bg-active": "#4a1a1a",
        "--cad-text-primary": "#fecaca",
        "--cad-text-secondary": "#f87171",
        "--cad-text-muted": "#b91c1c",
        "--cad-text-on-dark": "#ffffff",
        "--cad-text-on-brand": "#ffffff",
        "--cad-text-link": "#fca5a5",
        "--cad-border-default": "#5a2020",
        "--cad-border-light": "#3a1515",
        "--cad-border-emphasis": "#7f1d1d",
        "--cad-accent-primary": "#ef4444",
        "--cad-accent-secondary": "#f97316",
        "--cad-success": "#22c55e",
        "--cad-success-bg": "#14532d",
        "--cad-warning": "#eab308",
        "--cad-warning-bg": "#422006",
        "--cad-danger": "#ef4444",
        "--cad-danger-bg": "#450a0a",
        "--cad-info": "#3b82f6",
        "--cad-info-bg": "#1e3a5f",
        "--cad-shadow-sm": "0 1px 2px rgba(0,0,0,0.4)",
        "--cad-shadow-md": "0 4px 6px rgba(0,0,0,0.5)",
        "--cad-font-ui": "Kanit, sans-serif",
        "--cad-font-header": "BlackOpsOne, sans-serif",
        "--cad-font-unit": "Teko, sans-serif",
        "--cad-font-incident": "Kanit, sans-serif",
        "--cad-font-narrative": "SourceSans3, sans-serif",
        "--cad-font-mono": "SourceCodePro, monospace"
    },
    "Midnight Blue": {
        "--cad-bg-app": "#020617",
        "--cad-bg-surface": "#0f172a",
        "--cad-bg-elevated": "#1e293b",
        "--cad-bg-panel": "#0f172a",
        "--cad-bg-header": "linear-gradient(135deg, #1e1b4b 0%, #312e81 100%)",
        "--cad-bg-hover": "#1e293b",
        "--cad-bg-active": "#1e3a5f",
        "--cad-text-primary": "#e0e7ff",
        "--cad-text-secondary": "#a5b4fc",
        "--cad-text-muted": "#6366f1",
        "--cad-text-on-dark": "#ffffff",
        "--cad-text-on-brand": "#ffffff",
        "--cad-text-link": "#818cf8",
        "--cad-border-default": "#3730a3",
        "--cad-border-light": "#1e293b",
        "--cad-border-emphasis": "#4f46e5",
        "--cad-accent-primary": "#6366f1",
        "--cad-accent-secondary": "#8b5cf6",
        "--cad-success": "#22c55e",
        "--cad-success-bg": "#14532d",
        "--cad-warning": "#eab308",
        "--cad-warning-bg": "#422006",
        "--cad-danger": "#ef4444",
        "--cad-danger-bg": "#450a0a",
        "--cad-info": "#6366f1",
        "--cad-info-bg": "#1e1b4b",
        "--cad-shadow-sm": "0 1px 2px rgba(0,0,0,0.4)",
        "--cad-shadow-md": "0 4px 6px rgba(0,0,0,0.5)",
        "--cad-font-ui": "Exo2, sans-serif",
        "--cad-font-header": "Orbitron, sans-serif",
        "--cad-font-unit": "Exo2, sans-serif",
        "--cad-font-incident": "DMSans, sans-serif",
        "--cad-font-narrative": "IBMPlexSans, sans-serif",
        "--cad-font-mono": "IBMPlexMono, monospace"
    },
    "High Contrast": {
        "--cad-bg-app": "#000000",
        "--cad-bg-surface": "#111111",
        "--cad-bg-elevated": "#222222",
        "--cad-bg-panel": "#111111",
        "--cad-bg-header": "linear-gradient(135deg, #000000 0%, #1a1a1a 100%)",
        "--cad-bg-hover": "#333333",
        "--cad-bg-active": "#444444",
        "--cad-text-primary": "#ffffff",
        "--cad-text-secondary": "#cccccc",
        "--cad-text-muted": "#999999",
        "--cad-text-on-dark": "#ffffff",
        "--cad-text-on-brand": "#ffffff",
        "--cad-text-link": "#66bbff",
        "--cad-border-default": "#555555",
        "--cad-border-light": "#333333",
        "--cad-border-emphasis": "#777777",
        "--cad-accent-primary": "#ffff00",
        "--cad-accent-secondary": "#00ffff",
        "--cad-success": "#00ff00",
        "--cad-success-bg": "#003300",
        "--cad-warning": "#ffff00",
        "--cad-warning-bg": "#333300",
        "--cad-danger": "#ff0000",
        "--cad-danger-bg": "#330000",
        "--cad-info": "#00ccff",
        "--cad-info-bg": "#003344",
        "--cad-shadow-sm": "0 1px 2px rgba(0,0,0,0.5)",
        "--cad-shadow-md": "0 4px 6px rgba(0,0,0,0.6)",
        "--cad-font-ui": "Inter, sans-serif",
        "--cad-font-header": "LeagueSpartan, sans-serif",
        "--cad-font-unit": "BarlowCondensed, sans-serif",
        "--cad-font-incident": "PublicSans, sans-serif",
        "--cad-font-narrative": "IBMPlexSans, sans-serif",
        "--cad-font-mono": "JetBrainsMono, monospace"
    }
}
