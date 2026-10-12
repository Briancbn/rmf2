from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from rmf2_vda5050_master.websocket import WebsocketConnectionManager

router = APIRouter()


@router.websocket("/ws")
async def log_ws(websocket: WebSocket) -> None:
    manager: WebsocketConnectionManager = websocket.app.state.ws_connection_manager
    await manager.subscribe(websocket, "log")
    try:
        await websocket.receive()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        manager.unsubscribe(websocket, "log")
