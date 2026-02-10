"""Calendar schema definitions."""

SCHEMA_SQL = [
    """CREATE TABLE IF NOT EXISTS GoogleCalendarTokens (
        email TEXT PRIMARY KEY,
        access_token TEXT,
        refresh_token TEXT,
        token_expiry TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS CalendarEvents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        google_event_id TEXT UNIQUE,
        summary TEXT,
        description TEXT,
        start_time TEXT,
        end_time TEXT,
        all_day INTEGER DEFAULT 0,
        location TEXT,
        source TEXT DEFAULT 'local',
        sync_status TEXT DEFAULT 'synced',
        created TEXT,
        updated TEXT
    )""",
]


def ensure_calendar_schema(conn):
    """Create calendar tables if they don't exist."""
    c = conn.cursor()
    for sql in SCHEMA_SQL:
        c.execute(sql)
    conn.commit()
