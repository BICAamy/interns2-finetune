"""Observe-only real provider; never sends a vendor command."""

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
from ..gateway_session import GatewaySessionManager
from ..mirror_worker import RealMirrorWorker
from ..provider import ProviderCapabilities, RobotRuntimeServiceError


class HuayanRealStubProvider:
    """Disconnected by default; optionally receives authenticated Mac state."""

    mode = RuntimeMode.REAL
    capabilities = ProviderCapabilities()

    def __init__(
        self,
        gateway_sessions: GatewaySessionManager | None = None,
        mirror_worker: RealMirrorWorker | None = None,
    ) -> None:
        self._commands = RejectedCommandStore()
        self.gateway_sessions = gateway_sessions
        self.mirror_worker = mirror_worker
        self.capabilities = ProviderCapabilities(mjpeg=mirror_worker is not None)

    def start(self) -> None:
        if self.mirror_worker is not None:
            self.mirror_worker.start()

    def shutdown(self) -> None:
        if self.mirror_worker is not None:
            self.mirror_worker.shutdown()

    def get_mirror_status(self):
        if self.mirror_worker is None:
            raise RobotRuntimeServiceError(
                ErrorCode.OPERATION_NOT_ENABLED, "Real SOFA mirror is disabled"
            )
        return self.mirror_worker.status()

    @staticmethod
    def _connections() -> RobotConnectionState:
        return RobotConnectionState(
            gateway=LinkState.DISCONNECTED,
            datasheet=LinkState.DISCONNECTED,
            command_socket=LinkState.DISCONNECTED,
            controller_box=LinkState.UNKNOWN,
        )

    def health(self) -> RobotHealth:
        if self.gateway_sessions is not None:
            return self.gateway_sessions.health()
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
        if self.gateway_sessions is not None:
            return self.gateway_sessions.telemetry()
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
            "Real robot motion and camera are unavailable in observe-only mode",
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
        record, _created = self._commands.reject(
            kind, request, message="Real robot control is not enabled in Step 5"
        )
        raise RobotRuntimeServiceError(
            ErrorCode.OPERATION_NOT_ENABLED,
            record.error.message,
            status_code=403,
            command_id=request.command_id,
        )

    def get_command(self, command_id: str) -> RobotCommandRecord:
        return self._commands.get(command_id)

    def register_client(self) -> None:
        if self.mirror_worker is None:
            raise self._unavailable()

    def unregister_client(self) -> None:
        if self.mirror_worker is None:
            raise self._unavailable()

    def wait_for_events(
        self, after_sequence: int, *, timeout_s: float = 5.0
    ) -> list[SimulationEvent]:
        raise self._unavailable()

    def wait_for_frame(
        self, after_sequence: int, *, timeout_s: float = 2.0
    ) -> tuple[int, Any | None]:
        if self.mirror_worker is None:
            raise self._unavailable()
        return self.mirror_worker.wait_for_frame(after_sequence, timeout_s=timeout_s)
