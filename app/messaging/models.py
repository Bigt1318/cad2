# ============================================================================
# FORD-CAD Messaging — Database Models & Schema
# ============================================================================

import sqlite3
import datetime
import json
from typing import Optional, List, Dict, Any
from enum import Enum


class MessageChannel(str, Enum):
    """Supported messaging channels."""
    INTERNAL = "internal"
    SMS = "sms"
    EMAIL = "email"
    SIGNAL = "signal"
    WEBEX = "webex"


class MessageStatus(str, Enum):
    """Message delivery status."""
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"


class MessageDirection(str, Enum):
    """Message direction."""
    INBOUND = "inbound"
    OUTBOUND = "outbound"


# ============================================================================
# SCHEMA INITIALIZATION
# ============================================================================

def init_messaging_schema(conn: sqlite3.Connection):
    """Initialize all messaging tables."""
    c = conn.cursor()

    # -------------------------------------------------------------------------
    # Contacts - External contacts with channel preferences
    # -------------------------------------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS MessagingContacts (
            contact_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            organization TEXT,

            -- Contact methods (multiple can be set)
            phone TEXT,
            email TEXT,
            signal_number TEXT,
            webex_person_id TEXT,

            -- Preferences
            preferred_channel TEXT DEFAULT 'sms',

            -- Metadata
            notes TEXT,
            tags TEXT,  -- JSON array of tags
            is_active INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,

            -- Link to CAD user if this is a known unit/person
            linked_user_id TEXT,
            linked_unit_id TEXT
        )
    """)

    # -------------------------------------------------------------------------
    # Conversations - Message threads
    # -------------------------------------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS MessagingConversations (
            conversation_id INTEGER PRIMARY KEY AUTOINCREMENT,

            -- Conversation type
            conversation_type TEXT NOT NULL DEFAULT 'direct',  -- direct, group, broadcast
            title TEXT,  -- Optional title for group chats

            -- Participants (JSON array of participant objects)
            -- Format: [{"type": "user|contact", "id": "...", "name": "..."}]
            participants TEXT NOT NULL,

            -- Linked resources
            incident_id INTEGER,  -- If conversation is about a specific incident

            -- Status
            is_archived INTEGER DEFAULT 0,

            -- Timestamps
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_message_at TEXT
        )
    """)

    # -------------------------------------------------------------------------
    # Messages - All messages (internal and external)
    # -------------------------------------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS Messages (
            message_id INTEGER PRIMARY KEY AUTOINCREMENT,

            -- Conversation linkage
            conversation_id INTEGER,

            -- Direction and channel
            direction TEXT NOT NULL,  -- inbound, outbound
            channel TEXT NOT NULL,    -- internal, sms, email, signal, webex

            -- Sender/Recipient
            sender_type TEXT NOT NULL,     -- user, contact, system
            sender_id TEXT,                -- user_id or contact_id
            sender_name TEXT,              -- Display name
            sender_address TEXT,           -- Phone/email for external

            recipient_type TEXT,           -- user, contact, broadcast
            recipient_id TEXT,
            recipient_name TEXT,
            recipient_address TEXT,

            -- Content
            subject TEXT,                  -- For email
            body TEXT NOT NULL,
            body_html TEXT,                -- HTML version for email

            -- Attachments (JSON array)
            attachments TEXT,

            -- Status tracking
            status TEXT NOT NULL DEFAULT 'pending',
            status_updated_at TEXT,

            -- External provider tracking
            external_id TEXT,              -- Provider's message ID
            external_status TEXT,          -- Raw status from provider
            provider_response TEXT,        -- JSON of provider response

            -- Error handling
            error_message TEXT,
            retry_count INTEGER DEFAULT 0,

            -- Metadata
            metadata TEXT,                 -- JSON for extra data

            -- Timestamps
            created_at TEXT NOT NULL,
            sent_at TEXT,
            delivered_at TEXT,
            read_at TEXT,

            FOREIGN KEY (conversation_id) REFERENCES MessagingConversations(conversation_id)
        )
    """)

    # -------------------------------------------------------------------------
    # Message Read Receipts - Track who has read what
    # -------------------------------------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS MessageReadReceipts (
            receipt_id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL,
            user_id TEXT NOT NULL,
            read_at TEXT NOT NULL,

            FOREIGN KEY (message_id) REFERENCES Messages(message_id),
            UNIQUE(message_id, user_id)
        )
    """)

    # -------------------------------------------------------------------------
    # Channel Configurations - Store provider settings
    # -------------------------------------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS MessagingChannelConfig (
            config_id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL UNIQUE,
            is_enabled INTEGER DEFAULT 0,
            config_json TEXT,  -- Encrypted/encoded config
            last_verified_at TEXT,
            verification_status TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    # -------------------------------------------------------------------------
    # Message Templates - Reusable message templates
    # -------------------------------------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS MessageTemplates (
            template_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            channel TEXT,  -- NULL means all channels
            subject TEXT,
            body TEXT NOT NULL,
            variables TEXT,  -- JSON array of variable names
            is_active INTEGER DEFAULT 1,
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    # -------------------------------------------------------------------------
    # Webhook Logs - Track inbound webhooks
    # -------------------------------------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS MessagingWebhookLogs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL,
            event_type TEXT,
            payload TEXT,
            processed INTEGER DEFAULT 0,
            error_message TEXT,
            received_at TEXT NOT NULL
        )
    """)

    # -------------------------------------------------------------------------
    # Indexes for performance
    # -------------------------------------------------------------------------
    c.execute("CREATE INDEX IF NOT EXISTS idx_messages_conversation ON Messages(conversation_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_messages_status ON Messages(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_messages_channel ON Messages(channel)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_messages_created ON Messages(created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_messages_sender ON Messages(sender_type, sender_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_conversations_updated ON MessagingConversations(updated_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_contacts_phone ON MessagingContacts(phone)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_contacts_email ON MessagingContacts(email)")

    conn.commit()


# ============================================================================
# DATA ACCESS FUNCTIONS
# ============================================================================

def _ts() -> str:
    """Current timestamp in ISO format."""
    return datetime.datetime.now().isoformat()


def create_contact(
    conn: sqlite3.Connection,
    name: str,
    phone: str = None,
    email: str = None,
    signal_number: str = None,
    webex_person_id: str = None,
    preferred_channel: str = "sms",
    organization: str = None,
    notes: str = None,
    tags: List[str] = None
) -> int:
    """Create a new contact."""
    c = conn.cursor()
    now = _ts()

    c.execute("""
        INSERT INTO MessagingContacts (
            name, organization, phone, email, signal_number, webex_person_id,
            preferred_channel, notes, tags, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        name, organization, phone, email, signal_number, webex_person_id,
        preferred_channel, notes, json.dumps(tags or []), now, now
    ))

    conn.commit()
    return c.lastrowid


def get_contact(conn: sqlite3.Connection, contact_id: int) -> Optional[Dict]:
    """Get a contact by ID."""
    c = conn.cursor()
    row = c.execute(
        "SELECT * FROM MessagingContacts WHERE contact_id = ?",
        (contact_id,)
    ).fetchone()

    if row:
        d = dict(row)
        d["tags"] = json.loads(d.get("tags") or "[]")
        return d
    return None


def find_contact_by_address(
    conn: sqlite3.Connection,
    address: str,
    channel: str = None
) -> Optional[Dict]:
    """Find a contact by phone, email, or other address."""
    c = conn.cursor()

    # Normalize phone number (digits only)
    normalized_phone = ''.join(filter(str.isdigit, address))

    if channel == "email" or "@" in address:
        row = c.execute(
            "SELECT * FROM MessagingContacts WHERE LOWER(email) = LOWER(?)",
            (address,)
        ).fetchone()
    elif channel == "sms" or normalized_phone:
        # Try to match last 10 digits
        if len(normalized_phone) >= 10:
            pattern = f"%{normalized_phone[-10:]}"
            row = c.execute("""
                SELECT * FROM MessagingContacts
                WHERE REPLACE(REPLACE(REPLACE(phone, '-', ''), '(', ''), ')', '') LIKE ?
            """, (pattern,)).fetchone()
        else:
            row = None
    elif channel == "signal":
        row = c.execute(
            "SELECT * FROM MessagingContacts WHERE signal_number = ?",
            (address,)
        ).fetchone()
    elif channel == "webex":
        row = c.execute(
            "SELECT * FROM MessagingContacts WHERE webex_person_id = ?",
            (address,)
        ).fetchone()
    else:
        row = None

    if row:
        d = dict(row)
        d["tags"] = json.loads(d.get("tags") or "[]")
        return d
    return None


def create_conversation(
    conn: sqlite3.Connection,
    participants: List[Dict],
    conversation_type: str = "direct",
    title: str = None,
    incident_id: int = None
) -> int:
    """Create a new conversation."""
    c = conn.cursor()
    now = _ts()

    c.execute("""
        INSERT INTO MessagingConversations (
            conversation_type, title, participants, incident_id,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
    """, (
        conversation_type, title, json.dumps(participants),
        incident_id, now, now
    ))

    conn.commit()
    return c.lastrowid


def get_conversation(conn: sqlite3.Connection, conversation_id: int) -> Optional[Dict]:
    """Get a conversation by ID."""
    c = conn.cursor()
    row = c.execute(
        "SELECT * FROM MessagingConversations WHERE conversation_id = ?",
        (conversation_id,)
    ).fetchone()

    if row:
        d = dict(row)
        d["participants"] = json.loads(d.get("participants") or "[]")
        return d
    return None


def find_or_create_direct_conversation(
    conn: sqlite3.Connection,
    participant1: Dict,
    participant2: Dict
) -> int:
    """Find existing direct conversation or create new one."""
    c = conn.cursor()

    # Build participant identifiers
    p1_key = f"{participant1['type']}:{participant1['id']}"
    p2_key = f"{participant2['type']}:{participant2['id']}"

    # Search existing conversations
    rows = c.execute("""
        SELECT * FROM MessagingConversations
        WHERE conversation_type = 'direct' AND is_archived = 0
    """).fetchall()

    for row in rows:
        participants = json.loads(row["participants"] or "[]")
        if len(participants) == 2:
            keys = {f"{p['type']}:{p['id']}" for p in participants}
            if p1_key in keys and p2_key in keys:
                return row["conversation_id"]

    # Create new conversation
    return create_conversation(
        conn,
        participants=[participant1, participant2],
        conversation_type="direct"
    )


def create_message(
    conn: sqlite3.Connection,
    direction: str,
    channel: str,
    sender_type: str,
    body: str,
    sender_id: str = None,
    sender_name: str = None,
    sender_address: str = None,
    recipient_type: str = None,
    recipient_id: str = None,
    recipient_name: str = None,
    recipient_address: str = None,
    conversation_id: int = None,
    subject: str = None,
    body_html: str = None,
    attachments: List[Dict] = None,
    status: str = "pending",
    metadata: Dict = None
) -> int:
    """Create a new message."""
    c = conn.cursor()
    now = _ts()

    c.execute("""
        INSERT INTO Messages (
            conversation_id, direction, channel,
            sender_type, sender_id, sender_name, sender_address,
            recipient_type, recipient_id, recipient_name, recipient_address,
            subject, body, body_html, attachments,
            status, metadata, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        conversation_id, direction, channel,
        sender_type, sender_id, sender_name, sender_address,
        recipient_type, recipient_id, recipient_name, recipient_address,
        subject, body, body_html, json.dumps(attachments or []),
        status, json.dumps(metadata or {}), now
    ))

    message_id = c.lastrowid

    # Update conversation last_message_at
    if conversation_id:
        c.execute("""
            UPDATE MessagingConversations
            SET last_message_at = ?, updated_at = ?
            WHERE conversation_id = ?
        """, (now, now, conversation_id))

    conn.commit()
    return message_id


def update_message_status(
    conn: sqlite3.Connection,
    message_id: int,
    status: str,
    external_id: str = None,
    external_status: str = None,
    error_message: str = None,
    provider_response: Dict = None
):
    """Update message status after send attempt."""
    c = conn.cursor()
    now = _ts()

    updates = ["status = ?", "status_updated_at = ?"]
    params = [status, now]

    if status == "sent":
        updates.append("sent_at = ?")
        params.append(now)
    elif status == "delivered":
        updates.append("delivered_at = ?")
        params.append(now)
    elif status == "read":
        updates.append("read_at = ?")
        params.append(now)

    if external_id:
        updates.append("external_id = ?")
        params.append(external_id)

    if external_status:
        updates.append("external_status = ?")
        params.append(external_status)

    if error_message:
        updates.append("error_message = ?")
        params.append(error_message)

    if provider_response:
        updates.append("provider_response = ?")
        params.append(json.dumps(provider_response))

    params.append(message_id)

    c.execute(f"""
        UPDATE Messages SET {', '.join(updates)}
        WHERE message_id = ?
    """, params)

    conn.commit()


def get_message(conn: sqlite3.Connection, message_id: int) -> Optional[Dict]:
    """Get a message by ID."""
    c = conn.cursor()
    row = c.execute(
        "SELECT * FROM Messages WHERE message_id = ?",
        (message_id,)
    ).fetchone()

    if row:
        d = dict(row)
        d["attachments"] = json.loads(d.get("attachments") or "[]")
        d["metadata"] = json.loads(d.get("metadata") or "{}")
        return d
    return None


def get_conversation_messages(
    conn: sqlite3.Connection,
    conversation_id: int,
    limit: int = 50,
    before_id: int = None
) -> List[Dict]:
    """Get messages for a conversation."""
    c = conn.cursor()

    if before_id:
        rows = c.execute("""
            SELECT * FROM Messages
            WHERE conversation_id = ? AND message_id < ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (conversation_id, before_id, limit)).fetchall()
    else:
        rows = c.execute("""
            SELECT * FROM Messages
            WHERE conversation_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (conversation_id, limit)).fetchall()

    messages = []
    for row in rows:
        d = dict(row)
        d["attachments"] = json.loads(d.get("attachments") or "[]")
        d["metadata"] = json.loads(d.get("metadata") or "{}")
        messages.append(d)

    return list(reversed(messages))  # Return in chronological order


def get_user_conversations(
    conn: sqlite3.Connection,
    user_id: str,
    include_archived: bool = False
) -> List[Dict]:
    """Get all conversations for a user."""
    c = conn.cursor()

    archived_filter = "" if include_archived else "AND is_archived = 0"

    rows = c.execute(f"""
        SELECT * FROM MessagingConversations
        WHERE participants LIKE ?
        {archived_filter}
        ORDER BY COALESCE(last_message_at, updated_at) DESC
    """, (f'%"id": "{user_id}"%',)).fetchall()

    conversations = []
    for row in rows:
        d = dict(row)
        d["participants"] = json.loads(d.get("participants") or "[]")

        # Get last message
        last_msg = c.execute("""
            SELECT * FROM Messages
            WHERE conversation_id = ?
            ORDER BY created_at DESC LIMIT 1
        """, (d["conversation_id"],)).fetchone()

        if last_msg:
            d["last_message"] = dict(last_msg)

        # Get unread count for this user
        unread = c.execute("""
            SELECT COUNT(*) as count FROM Messages m
            WHERE m.conversation_id = ?
              AND m.sender_id != ?
              AND m.message_id NOT IN (
                  SELECT message_id FROM MessageReadReceipts WHERE user_id = ?
              )
        """, (d["conversation_id"], user_id, user_id)).fetchone()

        d["unread_count"] = unread["count"] if unread else 0

        conversations.append(d)

    return conversations


def mark_messages_read(
    conn: sqlite3.Connection,
    user_id: str,
    conversation_id: int = None,
    message_ids: List[int] = None
):
    """Mark messages as read by a user."""
    c = conn.cursor()
    now = _ts()

    if message_ids:
        for msg_id in message_ids:
            c.execute("""
                INSERT OR IGNORE INTO MessageReadReceipts (message_id, user_id, read_at)
                VALUES (?, ?, ?)
            """, (msg_id, user_id, now))
    elif conversation_id:
        # Mark all messages in conversation as read
        unread = c.execute("""
            SELECT message_id FROM Messages
            WHERE conversation_id = ?
              AND sender_id != ?
              AND message_id NOT IN (
                  SELECT message_id FROM MessageReadReceipts WHERE user_id = ?
              )
        """, (conversation_id, user_id, user_id)).fetchall()

        for row in unread:
            c.execute("""
                INSERT OR IGNORE INTO MessageReadReceipts (message_id, user_id, read_at)
                VALUES (?, ?, ?)
            """, (row["message_id"], user_id, now))

    conn.commit()


def get_unread_count(conn: sqlite3.Connection, user_id: str) -> int:
    """Get total unread message count for a user."""
    c = conn.cursor()

    result = c.execute("""
        SELECT COUNT(DISTINCT m.message_id) as count
        FROM Messages m
        JOIN MessagingConversations c ON m.conversation_id = c.conversation_id
        WHERE c.participants LIKE ?
          AND m.sender_id != ?
          AND m.message_id NOT IN (
              SELECT message_id FROM MessageReadReceipts WHERE user_id = ?
          )
    """, (f'%"id": "{user_id}"%', user_id, user_id)).fetchone()

    return result["count"] if result else 0


def log_webhook(
    conn: sqlite3.Connection,
    channel: str,
    payload: str,
    event_type: str = None
) -> int:
    """Log an incoming webhook."""
    c = conn.cursor()

    c.execute("""
        INSERT INTO MessagingWebhookLogs (channel, event_type, payload, received_at)
        VALUES (?, ?, ?, ?)
    """, (channel, event_type, payload, _ts()))

    conn.commit()
    return c.lastrowid
