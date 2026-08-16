"""FastAPI routes for the robot-simulation service."""

from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
import time
from typing import Any

from fastapi import APIRouter, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse

from surgical_contracts import (
    ErrorCode,
    ErrorResponse,
    MoveRelativeRequest,
    MoveToEntryRequest,
    ResetSimulationRequest,
    RobotActionRequest,
    RobotCommandKind,
    RobotCommandRecord,
    SimulationHeartbeat,
    SimulationHealth,
    SimulationTelemetry,
)

from .simulation_worker import (
    CommandConflictError,
    CommandNotFoundError,
    SimulationServiceError,
    SimulationWorker,
)
from .video_stream import MJPEG_BOUNDARY, mjpeg_stream


def _error_payload(
    code: ErrorCode,
    message: str,
    *,
    command_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return ErrorResponse(
        code=code,
        message=message,
        command_id=command_id,
        details=details or {},
    ).model_dump(mode="json")


def create_app(
    worker: SimulationWorker | None = None,
    *,
    manage_worker: bool = True,
) -> FastAPI:
    simulation_worker = worker or SimulationWorker()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if manage_worker:
            await asyncio.to_thread(simulation_worker.start)
        try:
            yield
        finally:
            if manage_worker:
                await asyncio.to_thread(simulation_worker.shutdown)

    app = FastAPI(
        title="InternS2 Robot Simulation",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.simulation_worker = simulation_worker

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, error: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content=_error_payload(
                ErrorCode.INVALID_COMMAND_SCHEMA,
                "Request did not match the simulation API contract",
                details={"errors": jsonable_encoder(error.errors())},
            ),
        )

    @app.exception_handler(SimulationServiceError)
    async def service_error_handler(_request: Request, error: SimulationServiceError):
        status_code = (
            409
            if isinstance(error, CommandConflictError)
            else 404
            if isinstance(error, CommandNotFoundError)
            else 503
        )
        return JSONResponse(
            status_code=status_code,
            content=_error_payload(error.error_code, str(error)),
        )

    router = APIRouter()

    @router.get("/health", response_model=SimulationHealth)
    def health() -> SimulationHealth:
        return simulation_worker.health()

    @router.get("/v1/state", response_model=SimulationTelemetry)
    def state() -> SimulationTelemetry:
        return simulation_worker.get_telemetry()

    @router.post("/v1/reset", response_model=RobotCommandRecord, status_code=202)
    def reset(request: ResetSimulationRequest) -> RobotCommandRecord:
        return simulation_worker.submit(RobotCommandKind.RESET, request)[0]

    @router.post(
        "/v1/commands/move-to-entry",
        response_model=RobotCommandRecord,
        status_code=202,
    )
    def move_to_entry(request: MoveToEntryRequest) -> RobotCommandRecord:
        return simulation_worker.submit(RobotCommandKind.MOVE_TO_ENTRY, request)[0]

    @router.post(
        "/v1/commands/move-relative",
        response_model=RobotCommandRecord,
        status_code=202,
    )
    def move_relative(request: MoveRelativeRequest) -> RobotCommandRecord:
        return simulation_worker.submit(RobotCommandKind.MOVE_RELATIVE, request)[0]

    @router.post(
        "/v1/commands/stop",
        response_model=RobotCommandRecord,
        status_code=202,
    )
    def stop(request: RobotActionRequest) -> RobotCommandRecord:
        return simulation_worker.submit(RobotCommandKind.STOP, request)[0]

    @router.post(
        "/v1/commands/estop",
        response_model=RobotCommandRecord,
        status_code=202,
    )
    def estop(request: RobotActionRequest) -> RobotCommandRecord:
        return simulation_worker.submit(RobotCommandKind.ESTOP, request)[0]

    @router.get(
        "/v1/commands/{command_id}",
        response_model=RobotCommandRecord,
    )
    def command(command_id: str) -> RobotCommandRecord:
        return simulation_worker.get_command(command_id)

    @router.get("/v1/stream.mjpeg")
    def stream() -> StreamingResponse:
        return StreamingResponse(
            mjpeg_stream(simulation_worker),
            media_type=f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}",
            headers={"Cache-Control": "no-store"},
        )

    @router.websocket("/v1/events")
    async def events(websocket: WebSocket) -> None:
        await websocket.accept()
        simulation_worker.register_client()
        try:
            try:
                sequence = max(0, int(websocket.query_params.get("after", "0")))
            except ValueError:
                await websocket.close(code=1008, reason="after must be a non-negative integer")
                return
            while True:
                updates = await asyncio.to_thread(
                    simulation_worker.wait_for_events,
                    sequence,
                    timeout_s=5.0,
                )
                if not updates:
                    heartbeat = SimulationHeartbeat(
                        after_sequence=sequence,
                        timestamp_ms=time.time_ns() // 1_000_000,
                    )
                    await websocket.send_json(heartbeat.model_dump(mode="json"))
                    continue
                for event in updates:
                    await websocket.send_json(event.model_dump(mode="json"))
                    sequence = event.sequence
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            simulation_worker.unregister_client()

    app.include_router(router)
    return app
