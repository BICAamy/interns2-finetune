"""Revision-based session WebSocket stream."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..sessions import SessionNotFound


router = APIRouter()


@router.websocket("/ws/sessions/{session_id}")
async def session_events(websocket: WebSocket, session_id: str) -> None:
    runtime = websocket.app.state.runtime
    try:
        snapshot = runtime.get_session(session_id)
    except SessionNotFound:
        await websocket.close(code=4404, reason="session not found")
        return

    await websocket.accept()
    last_revision = -1
    last_sent = 0.0
    try:
        while True:
            snapshot = runtime.get_session(session_id)
            now = time.monotonic()
            if snapshot.revision != last_revision or now - last_sent >= 5.0:
                await websocket.send_json(snapshot.model_dump(mode="json"))
                last_revision = snapshot.revision
                last_sent = now
            await asyncio.sleep(0.2)
    except (WebSocketDisconnect, RuntimeError):
        return
