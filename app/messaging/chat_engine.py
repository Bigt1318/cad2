# ============================================================================
# FORD-CAD Chat Engine — Core Business Logic
# ============================================================================
# Channel-based messaging: DM, incident, shift, ops, broadcast
# ============================================================================

import sqlite3
import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from .models import (
    _ts, get_or_create_channel, add_channel_member, remove_channel_member,
    get_channel_members, insert_chat_message, get_chat_messages,
    get_user_channels, update_chat_message, soft_delete_chat_message,
    upsert_receipt, search_chat_messages, add_reaction, remove_reaction,
    get_message_reactions, get_messages_reactions_bulk
)

logger = logging.getLogger(__name__)


class ChatEngine:
    """
    Core chat engine handling channel management, messaging, and delivery.

    Usage:
        engine = ChatEngine(get_conn)
        channel = engine.get_or_create_dm("E1", "CAR1")
        msg = engine.send_message(channel["id"], "unit", "E1", "Hello", sender_name="Engine 1")
    """

    def __init__(self, get_conn):
        """
        Args:
            get_conn: Callable that returns a sqlite3.Connection (row_factory set).
        """
        self._get_conn = get_conn
        self._broadcaster = None

    def _conn(self) -> sqlite3.Connection:
        return self._get_conn()

    def get_broadcaster(self):
        if self._broadcaster is None:
            from .websocket import get_broadcaster
            self._broadcaster = get_broadcaster()
        return self._broadcaster

    # ---- Channel Management ----

    def get_or_create_dm(self, user1: str, user2: str, name1: str = None, name2: str = None) -> Dict:
        """Get or create a DM channel between two users."""
        parts = sorted([user1, user2])
        key = f"dm:{parts[0]}:{parts[1]}"
        conn = self._conn()
        try:
            channel = get_or_create_channel(conn, key, "dm", created_by=user1)
            # Ensure both are members
            add_channel_member(conn, channel["id"], "unit", user1, display_name=name1)
            add_channel_member(conn, channel["id"], "unit", user2, display_name=name2)
            return channel
        finally:
            conn.close()

    def get_or_create_incident_channel(self, incident_id: int, title: str = None, created_by: str = None) -> Dict:
        """Get or create a channel for an incident."""
        key = f"inc:{incident_id}"
        display = title or f"Incident #{incident_id}"
        conn = self._conn()
        try:
            return get_or_create_channel(conn, key, "incident", title=display,
                                         incident_id=incident_id, created_by=created_by)
        finally:
            conn.close()

    def get_or_create_shift_channel(self, shift_letter: str, created_by: str = None) -> Dict:
        """Get or create a shift channel (A/B/C/D)."""
        key = f"shift:{shift_letter.upper()}"
        title = f"Shift {shift_letter.upper()}"
        conn = self._conn()
        try:
            return get_or_create_channel(conn, key, "shift", title=title,
                                         shift=shift_letter.upper(), created_by=created_by)
        finally:
            conn.close()

    def create_ops_channel(self, title: str, created_by: str) -> Dict:
        """Create an operations/group channel."""
        import time
        key = f"ops:{int(time.time())}:{created_by}"
        conn = self._conn()
        try:
            return get_or_create_channel(conn, key, "ops", title=title, created_by=created_by)
        finally:
            conn.close()

    def get_channel(self, channel_id: int) -> Optional[Dict]:
        """Get a channel by ID."""
        conn = self._conn()
        try:
            c = conn.cursor()
            row = c.execute("SELECT * FROM chat_channels WHERE id = ?", (channel_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_channel_by_key(self, key: str) -> Optional[Dict]:
        """Get a channel by key."""
        conn = self._conn()
        try:
            c = conn.cursor()
            row = c.execute("SELECT * FROM chat_channels WHERE key = ?", (key,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    # ---- Members ----

    def add_member(self, channel_id: int, member_type: str, member_id: str,
                   display_name: str = None, role: str = "member") -> Optional[Dict]:
        conn = self._conn()
        try:
            return add_channel_member(conn, channel_id, member_type, member_id, display_name, role)
        finally:
            conn.close()

    def remove_member(self, channel_id: int, member_type: str, member_id: str) -> bool:
        conn = self._conn()
        try:
            return remove_channel_member(conn, channel_id, member_type, member_id)
        finally:
            conn.close()

    def get_members(self, channel_id: int) -> List[Dict]:
        conn = self._conn()
        try:
            return get_channel_members(conn, channel_id)
        finally:
            conn.close()

    # ---- Messages ----

    def send_message(
        self,
        channel_id: int,
        sender_type: str,
        sender_id: str,
        body: str,
        sender_name: str = None,
        msg_type: str = "text",
        priority: str = "normal",
        reply_to_id: int = None,
        metadata: Dict = None,
        require_ack: bool = False
    ) -> Dict:
        """Send a message to a channel and broadcast via WebSocket."""
        conn = self._conn()
        try:
            msg = insert_chat_message(
                conn, channel_id, sender_type, sender_id, body,
                sender_name=sender_name, msg_type=msg_type, priority=priority,
                reply_to_id=reply_to_id, metadata=metadata,
                require_ack=1 if require_ack else 0
            )
            # Get channel members for delivery
            members = get_channel_members(conn, channel_id)
        finally:
            conn.close()

        # Broadcast via WebSocket (async — fire and forget from sync context)
        self._broadcast_message(msg, members, sender_id)
        return msg

    def _broadcast_message(self, msg: Dict, members: List[Dict], exclude_sender: str = None):
        """Broadcast a message to channel members via WebSocket."""
        import asyncio
        broadcaster = self.get_broadcaster()
        recipient_ids = [m["member_id"] for m in members if m["member_id"] != exclude_sender]

        payload = {
            "channel_id": msg["channel_id"],
            "message": msg
        }

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(broadcaster.send_to_users(recipient_ids, "channel_message", payload))
        except RuntimeError:
            # No running loop — skip real-time delivery
            pass

    def edit_message(self, message_id: int, new_body: str, editor_id: str) -> Optional[Dict]:
        """Edit a message (only sender). Returns updated message or None."""
        conn = self._conn()
        try:
            msg = update_chat_message(conn, message_id, new_body, editor_id)
            if msg:
                members = get_channel_members(conn, msg["channel_id"])
                self._broadcast_edit(msg, members)
            return msg
        finally:
            conn.close()

    def _broadcast_edit(self, msg: Dict, members: List[Dict]):
        import asyncio
        broadcaster = self.get_broadcaster()
        recipient_ids = [m["member_id"] for m in members]
        payload = {"message_id": msg["id"], "channel_id": msg["channel_id"],
                   "body": msg["body"], "edited_at": msg["edited_at"]}
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(broadcaster.send_to_users(recipient_ids, "message_edited", payload))
        except RuntimeError:
            pass

    def delete_message(self, message_id: int, deleter_id: str) -> bool:
        """Soft-delete a message. Returns True on success."""
        conn = self._conn()
        try:
            # Get channel_id before delete
            c = conn.cursor()
            row = c.execute("SELECT channel_id FROM chat_messages WHERE id = ?", (message_id,)).fetchone()
            if not row:
                return False
            channel_id = row["channel_id"]
            ok = soft_delete_chat_message(conn, message_id, deleter_id)
            if ok:
                members = get_channel_members(conn, channel_id)
                self._broadcast_delete(message_id, channel_id, members)
            return ok
        finally:
            conn.close()

    def _broadcast_delete(self, message_id: int, channel_id: int, members: List[Dict]):
        import asyncio
        broadcaster = self.get_broadcaster()
        recipient_ids = [m["member_id"] for m in members]
        payload = {"message_id": message_id, "channel_id": channel_id}
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(broadcaster.send_to_users(recipient_ids, "message_deleted", payload))
        except RuntimeError:
            pass

    def get_messages(self, channel_id: int, limit: int = 50, before_id: int = None) -> List[Dict]:
        """Get messages for a channel."""
        conn = self._conn()
        try:
            msgs = get_chat_messages(conn, channel_id, limit, before_id)
            # Attach reactions
            msg_ids = [m["id"] for m in msgs]
            reactions = get_messages_reactions_bulk(conn, msg_ids)
            for m in msgs:
                m["reactions"] = reactions.get(m["id"], [])
            return msgs
        finally:
            conn.close()

    def get_channels(self, user_id: str) -> List[Dict]:
        """Get all channels for a user with unread counts."""
        conn = self._conn()
        try:
            return get_user_channels(conn, user_id)
        finally:
            conn.close()

    # ---- Receipts ----

    def mark_delivered(self, message_id: int, recipient_id: str) -> bool:
        conn = self._conn()
        try:
            return upsert_receipt(conn, message_id, "unit", recipient_id, "delivered_at")
        finally:
            conn.close()

    def mark_read(self, message_id: int, recipient_id: str) -> bool:
        conn = self._conn()
        try:
            return upsert_receipt(conn, message_id, "unit", recipient_id, "read_at")
        finally:
            conn.close()

    def mark_read_bulk(self, channel_id: int, recipient_id: str) -> int:
        """Mark all messages in channel as read for recipient."""
        conn = self._conn()
        try:
            c = conn.cursor()
            now = _ts()
            # Get unread message IDs
            rows = c.execute("""
                SELECT m.id FROM chat_messages m
                WHERE m.channel_id = ? AND m.sender_id != ? AND m.is_deleted = 0
                  AND m.id NOT IN (
                    SELECT message_id FROM chat_receipts
                    WHERE recipient_id = ? AND read_at IS NOT NULL
                  )
            """, (channel_id, recipient_id, recipient_id)).fetchall()
            count = 0
            for r in rows:
                try:
                    c.execute("""
                        INSERT INTO chat_receipts (message_id, recipient_type, recipient_id, read_at)
                        VALUES (?, 'unit', ?, ?)
                    """, (r["id"], recipient_id, now))
                    count += 1
                except sqlite3.IntegrityError:
                    c.execute("""
                        UPDATE chat_receipts SET read_at = ?
                        WHERE message_id = ? AND recipient_id = ? AND read_at IS NULL
                    """, (now, r["id"], recipient_id))
                    count += 1
            conn.commit()
            return count
        finally:
            conn.close()

    def mark_ack(self, message_id: int, recipient_id: str) -> bool:
        conn = self._conn()
        try:
            ok = upsert_receipt(conn, message_id, "unit", recipient_id, "ack_at")
            if ok:
                # Broadcast ack to channel
                c = conn.cursor()
                row = c.execute("SELECT channel_id FROM chat_messages WHERE id = ?", (message_id,)).fetchone()
                if row:
                    members = get_channel_members(conn, row["channel_id"])
                    self._broadcast_receipt(message_id, row["channel_id"], recipient_id, "ack", members)
            return ok
        finally:
            conn.close()

    def _broadcast_receipt(self, message_id, channel_id, recipient_id, status, members):
        import asyncio
        broadcaster = self.get_broadcaster()
        recipient_ids = [m["member_id"] for m in members]
        payload = {"message_id": message_id, "channel_id": channel_id,
                   "recipient_id": recipient_id, "status": status}
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(broadcaster.send_to_users(recipient_ids, "receipt_update", payload))
        except RuntimeError:
            pass

    # ---- Search ----

    def search(self, user_id: str, query: str, channel_type: str = None,
               sender_id: str = None, limit: int = 50) -> List[Dict]:
        conn = self._conn()
        try:
            return search_chat_messages(conn, user_id, query, channel_type, sender_id, limit)
        finally:
            conn.close()

    # ---- Reactions ----

    def react(self, message_id: int, user_id: str, reaction: str) -> bool:
        conn = self._conn()
        try:
            return add_reaction(conn, message_id, user_id, reaction)
        finally:
            conn.close()

    def unreact(self, message_id: int, user_id: str, reaction: str) -> bool:
        conn = self._conn()
        try:
            return remove_reaction(conn, message_id, user_id, reaction)
        finally:
            conn.close()

    def get_reactions(self, message_id: int) -> List[Dict]:
        conn = self._conn()
        try:
            return get_message_reactions(conn, message_id)
        finally:
            conn.close()

    # ---- System Cards ----

    def post_system_card(self, channel_id: int, card_type: str, data: Dict,
                         body: str = None) -> Dict:
        """Post a system-generated card message to a channel."""
        display_body = body or data.get("description", f"System: {card_type}")
        return self.send_message(
            channel_id=channel_id,
            sender_type="system",
            sender_id="SYSTEM",
            body=display_body,
            sender_name="System",
            msg_type=f"card:{card_type}",
            metadata=data
        )

    # ---- Broadcast ----

    def broadcast(
        self,
        targets: List[str],
        body: str,
        sender_id: str,
        sender_name: str = None,
        priority: str = "normal",
        require_ack: bool = False
    ) -> List[Dict]:
        """Send a broadcast message to multiple units (creates DMs or uses broadcast channel)."""
        messages = []
        for target in targets:
            channel = self.get_or_create_dm(sender_id, target,
                                            name1=sender_name, name2=target)
            msg = self.send_message(
                channel_id=channel["id"],
                sender_type="unit",
                sender_id=sender_id,
                body=body,
                sender_name=sender_name,
                msg_type="text",
                priority=priority,
                require_ack=require_ack
            )
            messages.append(msg)
        return messages

    # ---- File Attachments ----

    def add_attachment(self, message_id: int, filename: str, path: str,
                       mime: str = None, size: int = None, sha256: str = None,
                       thumbnail_path: str = None) -> Dict:
        """Record an attachment for a message."""
        conn = self._conn()
        try:
            c = conn.cursor()
            now = _ts()
            c.execute("""
                INSERT INTO chat_attachments (message_id, filename, path, mime, size, sha256, thumbnail_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (message_id, filename, path, mime, size, sha256, thumbnail_path, now))
            conn.commit()
            return {"id": c.lastrowid, "message_id": message_id, "filename": filename,
                    "path": path, "mime": mime, "size": size, "thumbnail_path": thumbnail_path}
        finally:
            conn.close()

    def get_attachments(self, message_id: int) -> List[Dict]:
        conn = self._conn()
        try:
            c = conn.cursor()
            rows = c.execute("SELECT * FROM chat_attachments WHERE message_id = ?", (message_id,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ---- Presence (DB persistence) ----

    def persist_presence(self, member_type: str, member_id: str, status: str):
        """Persist presence status to DB for last_seen tracking."""
        conn = self._conn()
        try:
            c = conn.cursor()
            now = _ts()
            c.execute("""
                INSERT INTO chat_presence (member_type, member_id, status, last_seen)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(member_type, member_id) DO UPDATE SET status = ?, last_seen = ?
            """, (member_type, member_id, status, now, status, now))
            conn.commit()
        finally:
            conn.close()

    def get_all_presence(self) -> List[Dict]:
        """Get all presence records."""
        conn = self._conn()
        try:
            c = conn.cursor()
            rows = c.execute("SELECT * FROM chat_presence").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


# ============================================================================
# CAD Event → Chat Integration Helper
# ============================================================================

def post_cad_event_to_chat(engine: ChatEngine, incident_id: int, event_type: str,
                           unit_id: str = None, user: str = None, details: str = None):
    """Post a CAD event as a system card to the incident channel.

    Call from main.py after key incident events (dispatch, enroute, arrive, clear, close).
    """
    try:
        channel = engine.get_or_create_incident_channel(incident_id)
        now = datetime.now().isoformat()

        event_labels = {
            "DISPATCH": "dispatched",
            "ENROUTE": "en route",
            "ARRIVED": "arrived on scene",
            "OPERATING": "operating",
            "CLEAR": "cleared",
            "CLOSE": "closed",
            "HOLD": "placed on HOLD",
            "UNHOLD": "removed from HOLD",
            "REOPEN": "reopened",
        }

        label = event_labels.get(event_type, event_type.lower())
        if unit_id:
            body = f"{unit_id} {label}"
        else:
            body = f"Incident {label}"
        if details:
            body += f" — {details}"

        metadata = {
            "card_type": "status_update",
            "event": event_type,
            "unit_id": unit_id,
            "timestamp": now,
            "user": user or "SYSTEM",
            "details": details
        }

        engine.post_system_card(channel["id"], "status", metadata, body=body)
        logger.info(f"[CHAT] Posted {event_type} card to incident {incident_id} channel")
    except Exception as e:
        logger.warning(f"[CHAT] Failed to post event card: {e}")


# Singleton engine instance
_chat_engine = None


def get_chat_engine(get_conn=None) -> ChatEngine:
    """Get or create the singleton ChatEngine instance."""
    global _chat_engine
    if _chat_engine is None:
        if get_conn is None:
            raise RuntimeError("ChatEngine not initialized — pass get_conn on first call")
        _chat_engine = ChatEngine(get_conn)
    return _chat_engine
