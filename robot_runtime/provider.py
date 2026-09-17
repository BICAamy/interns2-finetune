"""Small service boundary; the SOFA worker remains the simulation owner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from surgical_contracts import (
    ErrorCode,
    RobotCommandKind,
    RobotCommandRecord,
    RobotHealth,
    RobotTelemetry,
    RuntimeMode,
    SimulationCameraControlRequest,
    SimulationCameraState,
    SimulationEvent,
    SimulationHealth,
    SimulationTelemetry,
)


@dataclass(frozen=True)
class ProviderCapabilities:
    camera: bool = False
    events: bool = False
    mjpeg: bool = False


class RobotRuntimeServiceError(RuntimeError):
    def __init__(
        self,
        error_code: ErrorCode,
        message: str,
        *,
        status_code: int = 503,
        command_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.status_code = status_code
        self.command_id = command_id


class RobotProvider(Protocol):
    """Operations used by the common API, not a vendor command interface."""

    mode: RuntimeMode
    capabilities: ProviderCapabilities

    def start(self) -> None: ...
    def shutdown(self) -> None: ...
    def health(self) -> SimulationHealth | RobotHealth: ...
    def get_telemetry(self) -> SimulationTelemetry | RobotTelemetry: ...
    def get_camera_state(self) -> SimulationCameraState: ...
    def control_camera(
        self, request: SimulationCameraControlRequest
    ) -> SimulationCameraState: ...
    def submit(
        self, kind: RobotCommandKind, request: Any
    ) -> tuple[RobotCommandRecord, bool]: ...
    def get_command(self, command_id: str) -> RobotCommandRecord: ...
    def register_client(self) -> None: ...
    def unregister_client(self) -> None: ...
    def wait_for_events(
        self, after_sequence: int, *, timeout_s: float = 5.0
    ) -> list[SimulationEvent]: ...
    def wait_for_frame(
        self, after_sequence: int, *, timeout_s: float = 2.0
    ) -> tuple[int, Any | None]: ...
