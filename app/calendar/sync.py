"""Bidirectional sync engine for Google Calendar."""

import datetime
import logging

log = logging.getLogger("ford-cad.calendar")


def sync_from_google(conn, service, month=None, year=None):
    """Pull events from Google Calendar into local DB."""
    if not service:
        return {"synced": 0, "error": "No Google service available"}

    now = datetime.datetime.now()
    y = year or now.year
    m = month or now.month

    time_min = f"{y}-{m:02d}-01T00:00:00Z"
    if m == 12:
        time_max = f"{y + 1}-01-01T00:00:00Z"
    else:
        time_max = f"{y}-{m + 1:02d}-01T00:00:00Z"

    try:
        events_result = service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            maxResults=250,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = events_result.get("items", [])
    except Exception as e:
        log.error(f"Google Calendar sync failed: {e}")
        return {"synced": 0, "error": str(e)}

    synced = 0
    ts = datetime.datetime.now().isoformat()
    c = conn.cursor()

    for ev in events:
        google_id = ev.get("id", "")
        summary = ev.get("summary", "")
        description = ev.get("description", "")
        location = ev.get("location", "")

        start = ev.get("start", {})
        end = ev.get("end", {})
        all_day = 1 if "date" in start else 0
        start_time = start.get("dateTime") or start.get("date", "")
        end_time = end.get("dateTime") or end.get("date", "")

        c.execute("""
            INSERT OR REPLACE INTO CalendarEvents
            (google_event_id, summary, description, start_time, end_time,
             all_day, location, source, sync_status, created, updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'google', 'synced', ?, ?)
        """, (google_id, summary, description, start_time, end_time,
              all_day, location, ts, ts))
        synced += 1

    conn.commit()
    return {"synced": synced}


def push_to_google(conn, service, event_id):
    """Push a local event to Google Calendar."""
    if not service:
        return {"ok": False, "error": "No Google service"}

    row = conn.execute("SELECT * FROM CalendarEvents WHERE id=?", (event_id,)).fetchone()
    if not row:
        return {"ok": False, "error": "Event not found"}

    ev = dict(row)
    body = {
        "summary": ev["summary"],
        "description": ev.get("description") or "",
        "location": ev.get("location") or "",
    }

    if ev.get("all_day"):
        body["start"] = {"date": ev["start_time"][:10]}
        body["end"] = {"date": ev["end_time"][:10]}
    else:
        body["start"] = {"dateTime": ev["start_time"], "timeZone": "America/Detroit"}
        body["end"] = {"dateTime": ev["end_time"], "timeZone": "America/Detroit"}

    try:
        if ev.get("google_event_id"):
            result = service.events().update(
                calendarId="primary",
                eventId=ev["google_event_id"],
                body=body,
            ).execute()
        else:
            result = service.events().insert(calendarId="primary", body=body).execute()
            conn.execute(
                "UPDATE CalendarEvents SET google_event_id=?, sync_status='synced' WHERE id=?",
                (result["id"], event_id),
            )
            conn.commit()
        return {"ok": True, "google_event_id": result.get("id")}
    except Exception as e:
        log.error(f"Push to Google failed: {e}")
        return {"ok": False, "error": str(e)}


def delete_from_google(conn, service, event_id):
    """Delete an event from Google Calendar."""
    if not service:
        return {"ok": False, "error": "No Google service"}

    row = conn.execute("SELECT google_event_id FROM CalendarEvents WHERE id=?", (event_id,)).fetchone()
    if not row or not row["google_event_id"]:
        return {"ok": True}  # Nothing to delete on Google side

    try:
        service.events().delete(calendarId="primary", eventId=row["google_event_id"]).execute()
        return {"ok": True}
    except Exception as e:
        log.error(f"Delete from Google failed: {e}")
        return {"ok": False, "error": str(e)}
