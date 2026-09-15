"""WS /api/maritime/stream - real-time push of vessel positions, breaches and transshipments.

The bots run on their own event loop thread; ``publish()`` hands messages to
the API loop with ``run_coroutine_threadsafe`` so any thread can push.
Message shapes follow the API spec (``vessel_position_update``,
``breach_detected``, ``transshipment_detected``) plus a batched
``vessel_positions`` frame used after every AIS poll.
"""

import asyncio
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.auth import require_websocket_token
from app.utils.logger import logger
from app.utils.serialization import jsonable
from app.utils.time import utcnow

log = logger.bind(component="stream")

router = APIRouter(tags=["maritime"])


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None  # API loop, captured at startup
        self.sent = 0

    def bind_loop(self) -> None:
        self.loop = asyncio.get_running_loop()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.add(websocket)
        await websocket.send_text(json.dumps({"type": "hello", "data": {"clients": len(self.connections), "timestamp": utcnow().isoformat() + "Z"}}))

    def disconnect(self, websocket: WebSocket) -> None:
        self.connections.discard(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        if not self.connections:
            return
        payload = json.dumps(jsonable(message), default=str)
        dead = []
        for websocket in list(self.connections):
            try:
                await websocket.send_text(payload)
                self.sent += 1
            except Exception:  # noqa: BLE001 - client went away
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(websocket)

    def publish(self, message_type: str, data: dict[str, Any]) -> None:
        """Thread-safe: schedule a broadcast on the API loop (no-op without clients)."""
        if not self.connections or self.loop is None or self.loop.is_closed():
            return
        message = {"type": message_type, "data": data, "timestamp": utcnow()}
        try:
            asyncio.run_coroutine_threadsafe(self.broadcast(message), self.loop)
        except RuntimeError:
            pass

    def status(self) -> dict[str, Any]:
        return {"clients": len(self.connections), "messages_sent": self.sent}


manager = ConnectionManager()


@router.websocket("/stream")
async def stream(websocket: WebSocket) -> None:
    await require_websocket_token(websocket)
    await manager.connect(websocket)
    try:
        while True:
            # Clients may send pings / filters; we only need to keep the socket open
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:  # noqa: BLE001
        manager.disconnect(websocket)
