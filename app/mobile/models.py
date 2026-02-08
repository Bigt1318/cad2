"""
FORD-CAD Mobile — Database Models
"""
import sqlite3
import datetime
from typing import Optional, List, Dict

DB_PATH = "cad.db"


def _get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _ts() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_mobile_schema():
    """Create mobile-specific tables if they don't exist."""
    conn = _get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS incident_photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            filepath TEXT NOT NULL,
            mime_type TEXT DEFAULT 'image/jpeg',
            file_size INTEGER,
            caption TEXT,
            uploaded_by TEXT,
            uploaded_at TEXT
        )
    """)
    try:
        c.execute("CREATE INDEX IF NOT EXISTS idx_photos_incident ON incident_photos (incident_id)")
    except Exception:
        pass
    conn.commit()
    conn.close()


def save_photo(incident_id: int, filename: str, filepath: str,
               mime_type: str, file_size: int, caption: str, uploaded_by: str) -> int:
    conn = _get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO incident_photos (incident_id, filename, filepath, mime_type, file_size, caption, uploaded_by, uploaded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (incident_id, filename, filepath, mime_type, file_size, caption, uploaded_by, _ts()))
    photo_id = c.lastrowid
    conn.commit()
    conn.close()
    return photo_id


def get_photos(incident_id: int) -> List[Dict]:
    conn = _get_conn()
    c = conn.cursor()
    rows = c.execute("""
        SELECT * FROM incident_photos WHERE incident_id = ? ORDER BY uploaded_at DESC
    """, (incident_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
