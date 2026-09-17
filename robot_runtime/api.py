"""Provider-neutral version of the existing port-8001 robot API."""

from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
import time
from typing import TYPE_CHECKING, Any

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
    RobotHealth,
    RobotTelemetry,
    RuntimeMode,
    SimulationHeartbeat,
    SimulationCameraControlRequest,
    SimulationCameraState,
    SimulationHealth,
    SimulationTelemetry,
)
from simulation.server.video_stream import MJPEG_BOUNDARY, mjpeg_stream

from .provider import RobotProvider, RobotRuntimeServiceError

if TYPE_CHECKING:
    from simulation.server.simulation_worker import SimulationWorker


def create_provider(
    mode: RuntimeMode | str = RuntimeMode.SIMULATION,
    *,
    worker: SimulationWorker | None = None,
) -> RobotProvider:
    selected = RuntimeMode(mode)
    if selected == RuntimeMode.SIMULATION:
        from .providers.simulation import SimulationProvider

        return SimulationProvider(worker)
    if worker is not None:
        raise ValueError("a simulation worker cannot be used by the real provider")
    from .providers.huayan_real import HuayanRealStubProvider

    return HuayanRealStubProvider()


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
    provider: RobotProvider | None = None,
    *,
    mode: RuntimeMode | str = RuntimeMode.SIMULATION,
    worker: SimulationWorker | None = None,
    manage_provider: bool = True,
) -> FastAPI:
    selected = RuntimeMode(mode)
    if provider is not None and worker is not None:
        raise ValueError("pass either a provider or a simulation worker")
    runtime_provider = provider if provider is not None else create_provider(selected, worker=worker)
    if runtime_provider.mode != selected:
        raise ValueError("provider mode does not match requested runtime mode")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if manage_provider:
            await asyncio.to_thread(runtime_provider.start)
        try:
            yield
        finally:
            if manage_provider:
                await asyncio.to_thread(runtime_provider.shutdown)

    app = FastAPI(
        title=(
            "InternS2 Robot Simulation"
            if selected == RuntimeMode.SIMULATION
            else "InternS2 Robot Runtime"
        ),
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.robot_provider = runtime_provider
    if selected == RuntimeMode.SIMULATION:
        from .providers.simulation import SimulationProvider

        if isinstance(runtime_provider, SimulationProvider):
            app.state.simulation_worker = runtime_provider.worker

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, error: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content=_error_payload(
                ErrorCode.INVALID_COMMAND_SCHEMA,
                (
                    "Request did not match the simulation API contract"
                    if selected == RuntimeMode.SIMULATION
                    else "Request did not match the robot runtime API contract"
                ),
                details={"errors": jsonable_encoder(error.errors())},
            ),
        )

    if selected == RuntimeMode.SIMULATION:
        from simulation.server.simulation_worker import (
            CommandConflictError,
            CommandNotFoundError,
            SimulationServiceError,
        )

        @app.exception_handler(SimulationServiceError)
        async def simulation_error_handler(
            _request: Request, error: SimulationServiceError
        ):
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

    @app.exception_handler(RobotRuntimeServiceError)
    async def runtime_error_handler(_request: Request, error: RobotRuntimeServiceError):
        return JSONResponse(
            status_code=error.status_code,
            content=_error_payload(
                error.error_code, str(error), command_id=error.command_id
            ),
        )

    router = APIRouter()

    @router.get("/health", response_model=SimulationHealth | RobotHealth)
    def health() -> SimulationHealth | RobotHealth:
        return runtime_provider.health()

    @router.get("/v1/state", response_model=SimulationTelemetry | RobotTelemetry)
    def state() -> SimulationTelemetry | RobotTelemetry:
        return runtime_provider.get_telemetry()

    @router.get("/v1/camera", response_model=SimulationCameraState)
    def camera_state() -> SimulationCameraState:
        return runtime_provider.get_camera_state()

    @router.put("/v1/camera", response_model=SimulationCameraState)
    def control_camera(
        request: SimulationCameraControlRequest,
    ) -> SimulationCameraState:
        return runtime_provider.control_camera(request)

    @router.post("/v1/reset", response_model=RobotCommandRecord, status_code=202)
    def reset(request: ResetSimulationRequest) -> RobotCommandRecord:
        return runtime_provider.submit(RobotCommandKind.RESET, request)[0]

    @router.post(
        "/v1/commands/move-to-entry",
        response_model=RobotCommandRecord,
        status_code=202,
    )
    def move_to_entry(request: MoveToEntryRequest) -> RobotCommandRecord:
        return runtime_provider.submit(RobotCommandKind.MOVE_TO_ENTRY, request)[0]

    @router.post(
        "/v1/commands/move-relative",
        response_model=RobotCommandRecord,
        status_code=202,
    )
    def move_relative(request: MoveRelativeRequest) -> RobotCommandRecord:
        return runtime_provider.submit(RobotCommandKind.MOVE_RELATIVE, request)[0]

    @router.post("/v1/commands/stop", response_model=RobotCommandRecord, status_code=202)
    def stop(request: RobotActionRequest) -> RobotCommandRecord:
        return runtime_provider.submit(RobotCommandKind.STOP, request)[0]

    @router.post("/v1/commands/estop", response_model=RobotCommandRecord, status_code=202)
    def estop(request: RobotActionRequest) -> RobotCommandRecord:
        return runtime_provider.submit(RobotCommandKind.ESTOP, request)[0]

    @router.get("/v1/commands/{command_id}", response_model=RobotCommandRecord)
    def command(command_id: str) -> RobotCommandRecord:
        return runtime_provider.get_command(command_id)

    @router.get("/v1/stream.mjpeg")
    def stream() -> StreamingResponse:
        if not runtime_provider.capabilities.mjpeg:
            raise RobotRuntimeServiceError(
                ErrorCode.OPERATION_NOT_ENABLED,
                "Robot video is unavailable in this provider",
            )
        return StreamingResponse(
            mjpeg_stream(runtime_provider),
            media_type=f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}",
            headers={"Cache-Control": "no-store"},
        )

    @router.websocket("/v1/events")
    async def events(websocket: WebSocket) -> None:
        if not runtime_provider.capabilities.events:
            await websocket.accept()
            await websocket.close(code=1013, reason="gateway_disconnected")
            return
        await websocket.accept()
        runtime_provider.register_client()
        try:
            try:
                sequence = max(0, int(websocket.query_params.get("after", "0")))
            except ValueError:
                await websocket.close(code=1008, reason="after must be a non-negative integer")
                return
            while True:
                updates = await asyncio.to_thread(
                    runtime_provider.wait_for_events,
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
            runtime_provider.unregister_client()

    app.include_router(router)
    return app
