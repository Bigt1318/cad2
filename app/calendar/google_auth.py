"""Google OAuth2 flow and token management."""

import os
import datetime
import json
import logging

log = logging.getLogger("ford-cad.calendar")

# Google OAuth2 configuration
SCOPES = ["https://www.googleapis.com/auth/calendar"]
CLIENT_SECRETS_FILE = os.path.join(os.path.dirname(__file__), "client_secret.json")
REDIRECT_URI = "/api/calendar/callback"


def get_credentials_from_db(conn):
    """Load stored Google credentials from DB."""
    try:
        row = conn.execute("SELECT * FROM GoogleCalendarTokens LIMIT 1").fetchone()
        if row:
            return dict(row)
    except Exception:
        pass
    return None


def save_credentials_to_db(conn, email, access_token, refresh_token, expiry):
    """Store Google credentials in DB."""
    conn.execute("""
        INSERT OR REPLACE INTO GoogleCalendarTokens (email, access_token, refresh_token, token_expiry)
        VALUES (?, ?, ?, ?)
    """, (email, access_token, refresh_token, expiry))
    conn.commit()


def get_auth_url(base_url=""):
    """Generate Google OAuth2 authorization URL."""
    try:
        from google_auth_oauthlib.flow import Flow
        if not os.path.isfile(CLIENT_SECRETS_FILE):
            return None
        flow = Flow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES)
        flow.redirect_uri = base_url + REDIRECT_URI
        auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")
        return auth_url
    except ImportError:
        log.warning("google-auth-oauthlib not installed")
        return None
    except Exception as e:
        log.error(f"OAuth URL generation failed: {e}")
        return None


def handle_callback(code, base_url=""):
    """Exchange authorization code for tokens."""
    try:
        from google_auth_oauthlib.flow import Flow
        flow = Flow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES)
        flow.redirect_uri = base_url + REDIRECT_URI
        flow.fetch_token(code=code)
        creds = flow.credentials
        return {
            "access_token": creds.token,
            "refresh_token": creds.refresh_token,
            "expiry": creds.expiry.isoformat() if creds.expiry else None,
            "email": "sertcad2022@gmail.com",
        }
    except ImportError:
        return None
    except Exception as e:
        log.error(f"OAuth callback failed: {e}")
        return None


def get_google_service(conn):
    """Build an authorized Google Calendar API service."""
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        stored = get_credentials_from_db(conn)
        if not stored or not stored.get("refresh_token"):
            return None

        creds = Credentials(
            token=stored.get("access_token"),
            refresh_token=stored.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=_get_client_id(),
            client_secret=_get_client_secret(),
        )

        if creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
            save_credentials_to_db(
                conn,
                stored["email"],
                creds.token,
                creds.refresh_token,
                creds.expiry.isoformat() if creds.expiry else None,
            )

        return build("calendar", "v3", credentials=creds)
    except ImportError:
        log.warning("Google API client not installed")
        return None
    except Exception as e:
        log.error(f"Failed to build Google service: {e}")
        return None


def _get_client_id():
    try:
        with open(CLIENT_SECRETS_FILE) as f:
            data = json.load(f)
            return data.get("web", {}).get("client_id", "")
    except Exception:
        return ""


def _get_client_secret():
    try:
        with open(CLIENT_SECRETS_FILE) as f:
            data = json.load(f)
            return data.get("web", {}).get("client_secret", "")
    except Exception:
        return ""
