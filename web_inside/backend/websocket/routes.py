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
    last_telemetry_sequence = -1
    last_telemetry_sent = 0.0
    next_telemetry_poll = 0.0
    try:
        while True:
            snapshot = runtime.get_session(session_id)
            now = time.monotonic()
            if snapshot.revision != last_revision or now - last_sent >= 5.0:
                await websocket.send_json(snapshot.model_dump(mode="json"))
                last_revision = snapshot.revision
                last_sent = now
            if now >= next_telemetry_poll:
                try:
                    telemetry = await asyncio.to_thread(
                        runtime.get_simulation_telemetry,
                        session_id,
                    )
                except Exception as error:
                    telemetry = runtime.simulation_telemetry_error(
                        session_id,
                        error,
                    )
                if (
                    telemetry.sequence != last_telemetry_sequence
                    or now - last_telemetry_sent >= 1.0
                ):
                    await websocket.send_json(telemetry.model_dump(mode="json"))
                    last_telemetry_sequence = telemetry.sequence
                    last_telemetry_sent = now
                next_telemetry_poll = now + runtime.telemetry_interval_s
            await asyncio.sleep(0.05)
    except (WebSocketDisconnect, RuntimeError):
        return
