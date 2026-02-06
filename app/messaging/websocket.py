# ============================================================================
# FORD-CAD Messaging — WebSocket Handler
# ============================================================================
# Real-time message delivery via WebSocket with SSE fallback
# ============================================================================

from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, Set, Optional, List
import asyncio
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class MessageBroadcaster:
    """
    Manages WebSocket connections for real-time messaging.

    Features:
    - Per-user connection tracking
    - Broadcast to all users
    - Send to specific user
    - Send to user group
    - Connection heartbeat/ping
    """

    def __init__(self):
        # Map user_id -> set of WebSocket connections
        self._connections: Dict[str, Set[WebSocket]] = {}
        # Map WebSocket -> user_id
        self._ws_to_user: Dict[WebSocket, str] = {}
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, user_id: str):
        """Register a new WebSocket connection for a user."""
        await websocket.accept()

        async with self._lock:
            if user_id not in self._connections:
                self._connections[user_id] = set()
            self._connections[user_id].add(websocket)
            self._ws_to_user[websocket] = user_id

        logger.info(f"[WS] User {user_id} connected. Total connections: {self._count_connections()}")

        # Send connection confirmation
        await self._send_to_websocket(websocket, {
            "type": "connected",
            "user_id": user_id,
            "timestamp": datetime.now().isoformat(),
        })

    async def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection."""
        async with self._lock:
            user_id = self._ws_to_user.pop(websocket, None)
            if user_id and user_id in self._connections:
                self._connections[user_id].discard(websocket)
                if not self._connections[user_id]:
                    del self._connections[user_id]

        logger.info(f"[WS] User {user_id} disconnected. Total connections: {self._count_connections()}")

    def _count_connections(self) -> int:
        """Count total active connections."""
        return sum(len(conns) for conns in self._connections.values())

    def is_user_online(self, user_id: str) -> bool:
        """Check if a user has any active connections."""
        return user_id in self._connections and len(self._connections[user_id]) > 0

    def get_online_users(self) -> List[str]:
        """Get list of online user IDs."""
        return list(self._connections.keys())

    async def _send_to_websocket(self, ws: WebSocket, data: Dict) -> bool:
        """Send data to a single WebSocket."""
        try:
            await ws.send_json(data)
            return True
        except Exception as e:
            logger.warning(f"[WS] Send failed: {e}")
            return False

    async def send_to_user(
        self,
        user_id: str,
        event_type: str,
        data: Dict
    ) -> int:
        """
        Send event to all connections for a specific user.

        Returns:
            Number of connections that received the message
        """
        message = {
            "type": event_type,
            "timestamp": datetime.now().isoformat(),
            **data
        }

        sent_count = 0
        failed_connections = []

        async with self._lock:
            connections = self._connections.get(user_id, set()).copy()

        for ws in connections:
            if await self._send_to_websocket(ws, message):
                sent_count += 1
            else:
                failed_connections.append(ws)

        # Clean up failed connections
        for ws in failed_connections:
            await self.disconnect(ws)

        return sent_count

    async def send_to_users(
        self,
        user_ids: List[str],
        event_type: str,
        data: Dict
    ) -> Dict[str, int]:
        """
        Send event to multiple users.

        Returns:
            Dict mapping user_id to number of connections reached
        """
        results = {}
        for user_id in user_ids:
            results[user_id] = await self.send_to_user(user_id, event_type, data)
        return results

    async def broadcast(
        self,
        event_type: str,
        data: Dict,
        exclude_users: List[str] = None
    ) -> int:
        """
        Broadcast event to all connected users.

        Args:
            event_type: Event type identifier
            data: Event data
            exclude_users: List of user IDs to skip

        Returns:
            Number of connections that received the message
        """
        exclude_users = exclude_users or []
        total_sent = 0

        async with self._lock:
            all_users = list(self._connections.keys())

        for user_id in all_users:
            if user_id not in exclude_users:
                total_sent += await self.send_to_user(user_id, event_type, data)

        return total_sent

    async def ping_all(self):
        """Send ping to all connections to keep them alive."""
        async with self._lock:
            all_websockets = [
                ws for conns in self._connections.values()
                for ws in conns
            ]

        for ws in all_websockets:
            try:
                await ws.send_json({"type": "ping", "timestamp": datetime.now().isoformat()})
            except Exception:
                await self.disconnect(ws)


# Singleton instance
_broadcaster = None


def get_broadcaster() -> MessageBroadcaster:
    """Get or create the singleton broadcaster instance."""
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = MessageBroadcaster()
    return _broadcaster


# ============================================================================
# SSE (Server-Sent Events) Fallback
# ============================================================================

class SSEManager:
    """
    Server-Sent Events manager for browsers that don't support WebSocket.
    """

    def __init__(self):
        self._queues: Dict[str, asyncio.Queue] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, user_id: str) -> asyncio.Queue:
        """Create event queue for a user."""
        async with self._lock:
            if user_id not in self._queues:
                self._queues[user_id] = asyncio.Queue()
            return self._queues[user_id]

    async def unsubscribe(self, user_id: str):
        """Remove event queue for a user."""
        async with self._lock:
            self._queues.pop(user_id, None)

    async def send_event(self, user_id: str, event_type: str, data: Dict):
        """Queue event for a user."""
        async with self._lock:
            queue = self._queues.get(user_id)

        if queue:
            await queue.put({
                "event": event_type,
                "data": data,
                "timestamp": datetime.now().isoformat()
            })

    async def broadcast_event(self, event_type: str, data: Dict, exclude_users: List[str] = None):
        """Broadcast event to all subscribed users."""
        exclude_users = exclude_users or []

        async with self._lock:
            user_ids = list(self._queues.keys())

        for user_id in user_ids:
            if user_id not in exclude_users:
                await self.send_event(user_id, event_type, data)


# Singleton SSE manager
_sse_manager = None


def get_sse_manager() -> SSEManager:
    """Get or create the singleton SSE manager."""
    global _sse_manager
    if _sse_manager is None:
        _sse_manager = SSEManager()
    return _sse_manager


async def sse_event_generator(user_id: str):
    """
    Async generator for SSE events.

    Usage in FastAPI:
        @app.get("/messages/events")
        async def sse_endpoint(user_id: str):
            return StreamingResponse(
                sse_event_generator(user_id),
                media_type="text/event-stream"
            )
    """
    manager = get_sse_manager()
    queue = await manager.subscribe(user_id)

    try:
        while True:
            try:
                # Wait for event with timeout (for keepalive)
                event = await asyncio.wait_for(queue.get(), timeout=30)
                yield f"event: {event['event']}\n"
                yield f"data: {json.dumps(event['data'])}\n\n"
            except asyncio.TimeoutError:
                # Send keepalive
                yield f": keepalive\n\n"
    finally:
        await manager.unsubscribe(user_id)
