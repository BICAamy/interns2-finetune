"""Authenticated Huayan real provider backed by the Mac gateway."""

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
    RobotCommandResult,
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
from ..remote_motion import RemoteMotionPolicy, RemoteMotionStore


class HuayanRealProvider:
    """Production real-robot provider backed by one authenticated Mac gateway."""

    mode = RuntimeMode.REAL
    capabilities = ProviderCapabilities()

    def __init__(
        self,
        gateway_sessions: GatewaySessionManager | None = None,
        mirror_worker: RealMirrorWorker | None = None,
        remote_motion_policy: RemoteMotionPolicy | None = None,
    ) -> None:
        self._commands = RejectedCommandStore()
        self.gateway_sessions = gateway_sessions
        self.mirror_worker = mirror_worker
        if remote_motion_policy is not None and gateway_sessions is None:
            raise ValueError("remote motion requires authenticated gateway sessions")
        self.remote_motion = (
            RemoteMotionStore(remote_motion_policy, telemetry=gateway_sessions.telemetry)
            if remote_motion_policy is not None and gateway_sessions is not None
            else None
        )
        self.capabilities = ProviderCapabilities(
            camera=mirror_worker is not None,
            mjpeg=mirror_worker is not None,
        )

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
            sequence=0,
            freshness=SourceFreshness.DISCONNECTED,
            connections=self._connections(),
        )

    @staticmethod
    def _unavailable() -> RobotRuntimeServiceError:
        return RobotRuntimeServiceError(
            ErrorCode.OPERATION_NOT_ENABLED,
            "Real robot operation is unavailable without an authenticated gateway",
        )

    def get_camera_state(self) -> SimulationCameraState:
        if self.mirror_worker is None:
            raise self._unavailable()
        return self.mirror_worker.get_camera_state()

    def control_camera(
        self, request: SimulationCameraControlRequest
    ) -> SimulationCameraState:
        if self.mirror_worker is None:
            raise self._unavailable()
        return self.mirror_worker.control_camera(request)

    def submit(
        self, kind: RobotCommandKind, request: Any
    ) -> tuple[RobotCommandRecord, bool]:
        if (
            self.remote_motion is not None
            and kind == RobotCommandKind.MOVE_RELATIVE
        ):
            return self.remote_motion.propose(request)
        if (
            self.remote_motion is not None
            and kind == RobotCommandKind.SET_ENABLED
        ):
            return self.remote_motion.set_enabled(request)
        record, _created = self._commands.reject(
            kind, request, message="Requested real robot operation is not supported"
        )
        raise RobotRuntimeServiceError(
            ErrorCode.OPERATION_NOT_ENABLED,
            record.error.message,
            status_code=403,
            command_id=request.command_id,
        )

    def get_command(self, command_id: str) -> RobotCommandRecord:
        if self.remote_motion is not None:
            try:
                return self.remote_motion.get(command_id)
            except RobotRuntimeServiceError as error:
                if error.error_code != ErrorCode.COMMAND_NOT_FOUND:
                    raise
        return self._commands.get(command_id)

    def confirm_command(self, command_id: str, fingerprint: str) -> RobotCommandRecord:
        if self.remote_motion is None:
            raise self._unavailable()
        return self.remote_motion.confirm(command_id, fingerprint)

    def take_gateway_command(self, session_id: str):
        if self.remote_motion is None:
            return None
        return self.remote_motion.take_for_gateway(session_id)

    def ingest_gateway_result(self, fingerprint: str, result: RobotCommandResult) -> None:
        if self.remote_motion is None:
            raise self._unavailable()
        self.remote_motion.finish(fingerprint, result)

    def gateway_disconnected(self, session_id: str) -> None:
        if self.remote_motion is not None:
            self.remote_motion.gateway_disconnected(session_id)

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


# Kept temporarily for source compatibility with tests and older integrations.
# Production startup uses HuayanRealProvider.
HuayanRealStubProvider = HuayanRealProvider
