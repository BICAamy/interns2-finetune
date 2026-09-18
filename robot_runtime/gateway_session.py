"""Authenticated single-owner, observe-only session for the Mac edge gateway."""

from __future__ import annotations

import hmac
import secrets
import time
from collections import deque
from threading import RLock
from typing import Callable

from surgical_contracts import (
    GatewayHeartbeat,
    GatewayHello,
    GatewayStateFrame,
    LinkState,
    RobotConnectionState,
    RobotHealth,
    RobotProvider,
    RobotTelemetry,
    RuntimeMode,
    SourceFreshness,
    hello_auth_tag,
)


class GatewaySessionError(ValueError):
    """Authentication, ownership or sequence check failed."""


class GatewaySessionManager:
    def __init__(
        self,
        *,
        secret: bytes,
        gateway_id: str,
        device_sn: str,
        robot_model: str,
        package_versions: tuple[str, ...],
        config_sha256: str,
        stale_ms: int = 250,
        gateway_timeout_ms: int = 1500,
        transit_budget_ms: int = 100,
        clock_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        if len(secret) < 32:
            raise ValueError("gateway secret must be at least 32 bytes")
        if not gateway_id or not device_sn or not robot_model or not package_versions:
            raise ValueError("gateway identity must be complete")
        if len(config_sha256) != 64 or any(char not in "0123456789abcdef" for char in config_sha256):
            raise ValueError("invalid real config digest")
        if stale_ms <= 0 or gateway_timeout_ms <= stale_ms or transit_budget_ms < 0:
            raise ValueError("invalid gateway deadlines")
        self._secret = secret
        self.gateway_id = gateway_id
        self.device_sn = device_sn
        self.robot_model = robot_model
        self.package_versions = frozenset(package_versions)
        self.config_sha256 = config_sha256
        self.stale_ms = stale_ms
        self.gateway_timeout_ms = gateway_timeout_ms
        self.transit_budget_ms = transit_budget_ms
        self._clock_ns = clock_ns
        self._lock = RLock()
        self._connection_key: str | None = None
        self._session_id: str | None = None
        self._used_ids: set[str] = set()
        self._used_order: deque[str] = deque()
        self._message_sequence = 0
        self._source_sequence = -1
        self._last_contact_ns = 0
        self._last_state_received_ns = 0
        self._last_state_wall_ms: int | None = None
        self._latest: RobotTelemetry | None = None
        self._datasheet = LinkState.DISCONNECTED
        self._command_socket = LinkState.DISCONNECTED
        self._controller_box = LinkState.UNKNOWN

    @staticmethod
    def new_challenge() -> str:
        return secrets.token_hex(16)

    def _expire_if_needed(self, now_ns: int) -> None:
        if self._connection_key is not None and (
            now_ns - self._last_contact_ns > self.gateway_timeout_ms * 1_000_000
        ):
            self._connection_key = None
            self._session_id = None
            self._datasheet = LinkState.DISCONNECTED
            self._command_socket = LinkState.DISCONNECTED

    def open(self, hello: GatewayHello, *, challenge: str, connection_key: str) -> None:
        expected_tag = hello_auth_tag(
            self._secret,
            gateway_id=hello.gateway_id,
            challenge=challenge,
            handshake=hello.handshake,
        )
        identity = hello.handshake
        if hello.challenge != challenge or not hmac.compare_digest(hello.auth_tag, expected_tag):
            raise GatewaySessionError("gateway authentication failed")
        if (
            hello.gateway_id != self.gateway_id
            or identity.device_sn != self.device_sn
            or identity.robot_model != self.robot_model
            or identity.package_version not in self.package_versions
            or identity.safety_config_sha256 != self.config_sha256
        ):
            raise GatewaySessionError("gateway identity does not match real config")
        session_id = identity.gateway_session_id
        if len(session_id) != 32 or any(char not in "0123456789abcdef" for char in session_id):
            raise GatewaySessionError("gateway session nonce is invalid")
        now_ns = self._clock_ns()
        with self._lock:
            self._expire_if_needed(now_ns)
            if self._connection_key is not None:
                raise GatewaySessionError("another gateway session is active")
            if session_id in self._used_ids:
                raise GatewaySessionError("gateway session nonce was already used")
            self._used_ids.add(session_id)
            self._used_order.append(session_id)
            if len(self._used_order) > 4096:
                self._used_ids.remove(self._used_order.popleft())
            self._connection_key = connection_key
            self._session_id = session_id
            self._message_sequence = 0
            self._source_sequence = -1
            self._last_contact_ns = now_ns
            self._last_state_received_ns = 0
            self._last_state_wall_ms = None
            self._latest = None
            self._datasheet = LinkState.DISCONNECTED
            self._command_socket = LinkState.DISCONNECTED
            self._controller_box = LinkState.UNKNOWN

    def _check_frame(self, session_id: str, sequence: int, connection_key: str, now_ns: int) -> None:
        self._expire_if_needed(now_ns)
        if self._connection_key != connection_key or self._session_id != session_id:
            raise GatewaySessionError("message belongs to an inactive gateway session")
        if sequence <= self._message_sequence:
            raise GatewaySessionError("duplicate or out-of-order message sequence")
        self._message_sequence = sequence
        self._last_contact_ns = now_ns

    def ingest_state(self, frame: GatewayStateFrame, *, connection_key: str) -> None:
        state = frame.state
        if (
            state.provider != RobotProvider.HUAYAN_EDGE_GATEWAY
            or state.freshness != SourceFreshness.FRESH
            or state.device_sn != self.device_sn
            or state.robot_model != self.robot_model
            or state.package_version not in self.package_versions
            or state.controller_is_simulation is not False
            or state.state_age_at_gateway_send_ms is None
            or state.state_age_ms is None
            or state.gateway_received_at_ms is None
            or state.source_timestamp_ms is None
            or state.connections.gateway != LinkState.CONNECTED
            or state.connections.datasheet != LinkState.CONNECTED
        ):
            raise GatewaySessionError("gateway state is incomplete or inconsistent")
        if abs(float(state.state_age_ms) - float(state.state_age_at_gateway_send_ms)) > 1:
            raise GatewaySessionError("gateway state age fields disagree")
        if state.state_age_at_gateway_send_ms > self.stale_ms:
            raise GatewaySessionError("gateway sent stale DataSheet state")
        now_ns = self._clock_ns()
        with self._lock:
            self._check_frame(frame.gateway_session_id, frame.message_sequence, connection_key, now_ns)
            if state.sequence <= self._source_sequence:
                raise GatewaySessionError("duplicate or out-of-order source sequence")
            self._source_sequence = state.sequence
            self._latest = state.model_copy(deep=True)
            self._last_state_received_ns = now_ns
            self._last_state_wall_ms = time.time_ns() // 1_000_000
            self._datasheet = state.connections.datasheet
            self._command_socket = state.connections.command_socket
            self._controller_box = state.connections.controller_box

    def ingest_heartbeat(self, frame: GatewayHeartbeat, *, connection_key: str) -> None:
        now_ns = self._clock_ns()
        with self._lock:
            self._check_frame(frame.gateway_session_id, frame.message_sequence, connection_key, now_ns)
            self._datasheet = frame.datasheet
            self._command_socket = frame.command_socket

    def disconnect(self, *, connection_key: str) -> None:
        with self._lock:
            if self._connection_key == connection_key:
                self._connection_key = None
                self._session_id = None
                self._datasheet = LinkState.DISCONNECTED
                self._command_socket = LinkState.DISCONNECTED

    def _snapshot(self) -> tuple[SourceFreshness, RobotConnectionState, str | None, float | None]:
        now_ns = self._clock_ns()
        with self._lock:
            self._expire_if_needed(now_ns)
            gateway = LinkState.CONNECTED if self._connection_key else LinkState.DISCONNECTED
            connections = RobotConnectionState(
                gateway=gateway,
                datasheet=self._datasheet,
                command_socket=self._command_socket,
                controller_box=self._controller_box,
            )
            if gateway == LinkState.DISCONNECTED:
                return SourceFreshness.DISCONNECTED, connections, "gateway_disconnected", None
            if self._latest is None:
                return SourceFreshness.DISCONNECTED, connections, "datasheet_disconnected", None
            residence_ms = max(0.0, (now_ns - self._last_state_received_ns) / 1_000_000)
            age_ms = float(self._latest.state_age_at_gateway_send_ms or 0) + self.transit_budget_ms + residence_ms
            if self._datasheet != LinkState.CONNECTED:
                return SourceFreshness.DISCONNECTED, connections, "datasheet_disconnected", age_ms
            if age_ms > self.stale_ms:
                return SourceFreshness.STALE, connections, "datasheet_stale", age_ms
            if self._command_socket != LinkState.CONNECTED:
                return SourceFreshness.FRESH, connections, "command_socket_disconnected", age_ms
            return SourceFreshness.FRESH, connections, None, age_ms

    def health(self) -> RobotHealth:
        freshness, connections, error, _age = self._snapshot()
        return RobotHealth(
            runtime_mode=RuntimeMode.REAL,
            provider=RobotProvider.HUAYAN_EDGE_GATEWAY,
            control_mode="observe-only",
            status="healthy" if error is None else "degraded",
            freshness=freshness,
            connections=connections,
            ready_for_motion=False,
            error=error,
        )

    def telemetry(self) -> RobotTelemetry:
        freshness, connections, _error, age_ms = self._snapshot()
        with self._lock:
            latest = self._latest.model_copy(deep=True) if self._latest is not None else None
            session_id = self._session_id
            received_wall_ms = self._last_state_wall_ms
        if latest is None:
            return RobotTelemetry(
                runtime_mode=RuntimeMode.REAL,
                provider=RobotProvider.HUAYAN_EDGE_GATEWAY,
                control_mode="observe-only",
                sequence=0,
                freshness=freshness,
                connections=connections,
                gateway_session_id=session_id,
            )
        return latest.model_copy(update={
            "freshness": freshness,
            "connections": connections,
            "state_age_ms": age_ms,
            "server_received_at_ms": received_wall_ms,
            "gateway_session_id": session_id,
        })
