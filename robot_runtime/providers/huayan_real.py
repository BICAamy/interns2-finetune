"""Disconnected, observe-only real provider. No vendor or network imports."""

from __future__ import annotations

from typing import Any

from surgical_contracts import (
    ErrorCode,
    LinkState,
    RobotCommandKind,
    RobotCommandRecord,
    RobotConnectionState,
    RobotHealth,
    RobotProvider as RobotProviderKind,
    RobotTelemetry,
    RuntimeMode,
    SimulationCameraControlRequest,
    SimulationCameraState,
    SimulationEvent,
    SourceFreshness,
)

from ..command_store import RejectedCommandStore
from ..provider import ProviderCapabilities, RobotRuntimeServiceError


class HuayanRealStubProvider:
    """Fail-closed placeholder until an authenticated Mac gateway exists."""

    mode = RuntimeMode.REAL
    capabilities = ProviderCapabilities()

    def __init__(self) -> None:
        self._commands = RejectedCommandStore()

    def start(self) -> None:
        pass

    def shutdown(self) -> None:
        pass

    @staticmethod
    def _connections() -> RobotConnectionState:
        return RobotConnectionState(
            gateway=LinkState.DISCONNECTED,
            datasheet=LinkState.DISCONNECTED,
            command_socket=LinkState.DISCONNECTED,
            controller_box=LinkState.UNKNOWN,
        )

    def health(self) -> RobotHealth:
        return RobotHealth(
            runtime_mode=RuntimeMode.REAL,
            provider=RobotProviderKind.HUAYAN_EDGE_GATEWAY,
            control_mode="observe-only",
            status="degraded",
            freshness=SourceFreshness.DISCONNECTED,
            connections=self._connections(),
            ready_for_motion=False,
            error="gateway_disconnected",
        )

    def get_telemetry(self) -> RobotTelemetry:
        return RobotTelemetry(
            runtime_mode=RuntimeMode.REAL,
            provider=RobotProviderKind.HUAYAN_EDGE_GATEWAY,
            control_mode="observe-only",
            sequence=0,
            freshness=SourceFreshness.DISCONNECTED,
            connections=self._connections(),
        )

    @staticmethod
    def _unavailable() -> RobotRuntimeServiceError:
        return RobotRuntimeServiceError(
            ErrorCode.OPERATION_NOT_ENABLED,
            "Real robot gateway is disconnected; this capability is unavailable",
        )

    def get_camera_state(self) -> SimulationCameraState:
        raise self._unavailable()

    def control_camera(
        self, request: SimulationCameraControlRequest
    ) -> SimulationCameraState:
        raise self._unavailable()

    def submit(
        self, kind: RobotCommandKind, request: Any
    ) -> tuple[RobotCommandRecord, bool]:
        record, _created = self._commands.reject(kind, request)
        raise RobotRuntimeServiceError(
            ErrorCode.OPERATION_NOT_ENABLED,
            record.error.message,
            status_code=403,
            command_id=request.command_id,
        )

    def get_command(self, command_id: str) -> RobotCommandRecord:
        return self._commands.get(command_id)

    def register_client(self) -> None:
        raise self._unavailable()

    def unregister_client(self) -> None:
        raise self._unavailable()

    def wait_for_events(
        self, after_sequence: int, *, timeout_s: float = 5.0
    ) -> list[SimulationEvent]:
        raise self._unavailable()

    def wait_for_frame(
        self, after_sequence: int, *, timeout_s: float = 2.0
    ) -> tuple[int, Any | None]:
        raise self._unavailable()
