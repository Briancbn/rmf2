"""WebSocket connection manager — topic-filtered fan-out hub for connected clients."""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict

from fastapi import WebSocket

_LOGGER = logging.getLogger(__name__)


class WebsocketConnectionManager:
    def __init__(self) -> None:
        self._subscriptions: dict[str, list[WebSocket]] = defaultdict(list)
        self._loop: asyncio.AbstractEventLoop | None = None

    def setup(self) -> None:
        """Capture the running event loop. Call once during app startup."""
        self._loop = asyncio.get_running_loop()

    async def subscribe(self, websocket: WebSocket, topic: str) -> None:
        await websocket.accept()
        self._subscriptions[topic].append(websocket)
        _LOGGER.info("WebSocket client subscribed to %r", topic)

    def unsubscribe(self, websocket: WebSocket, topic: str) -> None:
        self._subscriptions[topic].remove(websocket)
        _LOGGER.info("WebSocket client unsubscribed from %r", topic)

    def publish(self, topic: str, body: str) -> None:
        """Thread-safe: deliver to clients subscribed to the exact topic or a
        suffix of it (e.g. ``"state"`` matches ``"prefix/mfr/sn/state"``).
        """
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._publish(topic, body), self._loop)

    async def _publish(self, topic: str, body: str) -> None:
        for sub, connections in self._subscriptions.items():
            if topic == sub or topic.endswith(f"/{sub}"):
                for connection in connections:
                    try:
                        await connection.send_text(body)
                    except Exception:
                        pass


class WebsocketLogHandler(logging.Handler):
    """Logging handler that streams records to WebSocket clients on topic ``log``."""

    def __init__(self, manager: WebsocketConnectionManager) -> None:
        super().__init__()
        self._manager = manager

    def emit(self, record: logging.LogRecord) -> None:
        try:
            body = json.dumps({
                "time": logging.Formatter().formatTime(record),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            })
            self._manager.publish("log", body)
        except Exception:
            self.handleError(record)
