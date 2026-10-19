"""云桥文件是将机械臂发送过来的数据经过处理，处理完成之后再发给服务器"""
from __future__ import annotations

import ipaddress
import secrets
import threading
import time
from collections import deque
from typing import Callable
from urllib.parse import urlparse

from surgical_contracts import (
    CoordinateFrame,
    DistanceUnit,
    ErrorCode,
    GatewayCommandFrame,
    GatewayCommandKind,
    GatewayCommandAcceptedFrame,
    GatewayCommandResultFrame,
    GatewayHandshake,
    GatewayHeartbeat,
    GatewayHello,
    GatewayStateFrame,
    LinkState,
    MotionState,
    MotionStopConfirmation,
    Pose6D,
    PROTOCOL_VERSION,
    RobotCommandEnvelope,
    RobotCommandResult,
    RobotConnectionState,
    RobotProvider,
    RobotTelemetry,
    RuntimeMode,
    SourceFreshness,
    SoftwareStopResult,
    StopDelivery,
    ToolStatus,
    VendorFault,
    hello_auth_tag,
    parse_wire_json,
)

from .huayan.adapter import fixed_xyz_quaternion
from .huayan.adapter import EmergencyInfoRead, RobotStateRead
from .state_machine import RejectOnlyLedger, SampleRecord
from .watchdog import StateWatchdog


def validate_cloud_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "ws" or parsed.path != "/v1/gateway/connect" or parsed.query or parsed.fragment:
        raise ValueError("Step 5 requires ws://127.0.0.1:<tunnel-port>/v1/gateway/connect")
    if parsed.username or parsed.password or parsed.port is None:
        raise ValueError("cloud URL must not contain credentials and must specify a port")
    try:
        if not ipaddress.ip_address(parsed.hostname or "").is_loopback:
            raise ValueError("plain WebSocket is allowed only over a local SSH tunnel")
    except ValueError as exc:
        raise ValueError("cloud WebSocket host must be a literal loopback address") from exc
    return url

# 将DatasheetSample转化为RobotTelemetry（华沿厂商协议世界 -> 项目统一协议世界）
def telemetry_from_sample(
    record: SampleRecord,
    *,
    session_id: str,
    device_sn: str,
    robot_model: str,
    package_version: str,
    controller_is_simulation: bool,
    command_connected: bool,
    watchdog: StateWatchdog,
    robot_status: RobotStateRead | None = None,
    emergency_status: EmergencyInfoRead | None = None,
) -> RobotTelemetry:
    sample = record.sample
    if controller_is_simulation:
        raise ValueError("controller reports simulation mode")
    if sample.device_sn != device_sn:
        raise ValueError("DataSheet device SN disagrees with gateway identity")
    age_ms = watchdog.age_ms(sample)
    if age_ms > watchdog.stale_ms:
        raise ValueError("cannot upload stale DataSheet as fresh")
    pose = Pose6D(
        translation_mm=sample.base_pose[:3],
        rotation_rpy_deg=sample.base_pose[3:6],
        quaternion_xyzw=fixed_xyz_quaternion(sample.base_pose[3:6]),
        frame=CoordinateFrame.ROBOT_BASE,
        unit=DistanceUnit.MILLIMETER,
    )
    return RobotTelemetry(
        runtime_mode=RuntimeMode.REAL,
        provider=RobotProvider.HUAYAN_EDGE_GATEWAY,
        sequence=record.sequence,
        freshness=SourceFreshness.FRESH,
        connections=RobotConnectionState(
            gateway=LinkState.CONNECTED,
            datasheet=LinkState.CONNECTED,
            command_socket=LinkState.CONNECTED if command_connected else LinkState.DISCONNECTED,
            controller_box=(
                LinkState.CONNECTED
                if robot_status is not None and robot_status.controller_box_connected
                else LinkState.DISCONNECTED
                if robot_status is not None
                else LinkState.UNKNOWN
            ),
        ),
        source_timestamp_ms=sample.source_timestamp_ms,
        gateway_received_at_ms=sample.received_wall_ms,
        state_age_at_gateway_send_ms=age_ms,
        state_age_ms=age_ms,
        gateway_session_id=session_id,
        device_sn=device_sn,
        robot_model=robot_model,
        package_version=package_version,
        joint_positions_deg=sample.joint_positions_deg,
        joint_velocities_deg_s=sample.joint_velocities_deg_s,
        actual_pose_robot_base=pose,
        motion_state=(
            MotionState.FAILED if sample.error_code else
            MotionState.PAUSED if (
                (robot_status.paused if robot_status is not None else sample.paused)
                or sample.fsm_code == 32
            ) else
            MotionState.MOVING if sample.moving or sample.fsm_code in (25, 26, 27, 47)
            else MotionState.IDLE
        ),
        potentially_moving=(
            sample.moving
            or sample.paused
            or sample.fsm_code in (25, 26, 27, 32, 47)
            or (robot_status.paused if robot_status is not None else False)
        ),
        fsm_code=sample.fsm_code,
        enabled=(robot_status.enabled if robot_status is not None else sample.enabled),
        electrified=(robot_status.electrified if robot_status is not None else None),
        paused=(robot_status.paused if robot_status is not None else sample.paused),
        moving=sample.moving,
        in_position=(robot_status.in_position if robot_status is not None else sample.in_position),
        physical_estop_active=(
            emergency_status.emergency_stop
            if emergency_status is not None
            else robot_status.emergency_stop
            if robot_status is not None
            else None
        ),
        emergency_stop_circuit_fault=(
            emergency_status.emergency_circuit_fault
            if emergency_status is not None
            else None
        ),
        safeguard_active=(
            emergency_status.safeguard
            if emergency_status is not None
            else robot_status.safeguard
            if robot_status is not None
            else None
        ),
        safeguard_circuit_fault=(
            emergency_status.safeguard_circuit_fault
            if emergency_status is not None
            else None
        ),
        reduced_mode=sample.reduced_mode,
        auto_mode=sample.auto_mode,
        free_drive_active=sample.free_drive_mode,
        force_control_active=bool(sample.force_control_state),
        controller_is_simulation=controller_is_simulation,
        vendor_fault=(
            VendorFault(
                vendor_error_code=sample.error_code,
                vendor_error_axis=sample.error_axis or None,
            )
            if sample.error_code
            else None
        ),
    )


class CloudTransport:
    def __init__(
        self,
        url: str,
        *,
        secret: bytes,
        gateway_id: str,
        command_handler: Callable[
            [RobotCommandEnvelope, str], RobotCommandResult
        ] | None = None,
        stop_handler: Callable[
            [RobotCommandEnvelope, str], RobotCommandResult
        ] | None = None,
    ) -> None:
        self.url = validate_cloud_url(url)
        if len(secret) < 32:
            raise ValueError("gateway secret is too short")
        self.secret = secret
        self.gateway_id = gateway_id
        self.command_handler = command_handler
        self.stop_handler = stop_handler
        self.session_id: str | None = None
        self._connection = None
        self._message_sequence = 0
        self._rejections = RejectOnlyLedger()
        self._command_lock = threading.Lock()
        self._command_context = threading.local()
        self._command_thread: threading.Thread | None = None
        self._command_result: GatewayCommandResultFrame | None = None
        self._active_command_id: str | None = None
        self._stop_thread: threading.Thread | None = None
        self._stop_result: GatewayCommandResultFrame | None = None
        self._active_stop_id: str | None = None
        self._priority_threads: dict[str, threading.Thread] = {}
        self._priority_results: deque[GatewayCommandResultFrame] = deque()
        self._priority_kinds: dict[str, GatewayCommandKind] = {}

    def _sync_priority_compat_locked(self) -> None:
        """Keep the historical single-slot attributes useful to diagnostics."""
        self._stop_result = (
            self._priority_results[0] if self._priority_results else None
        )
        self._active_stop_id = next(iter(self._priority_kinds), None)
        self._stop_thread = (
            self._priority_threads.get(self._active_stop_id)
            if self._active_stop_id is not None
            else None
        )

    def connect(self, *, device_sn: str, robot_model: str, package_version: str) -> str:
        from websockets.sync.client import connect

        if self._connection is not None:
            raise RuntimeError("cloud connection is already open")
        with self._command_lock:
            if (
                self._active_command_id is not None
                or bool(self._priority_kinds)
                or (
                    self._command_thread is not None
                    and self._command_thread.is_alive()
                )
                or any(thread.is_alive() for thread in self._priority_threads.values())
            ):
                raise RuntimeError(
                    "previous remote command thread has not exited"
                )
        connection = connect(self.url, open_timeout=3, close_timeout=1, max_size=64 * 1024)
        try:
            challenge = parse_wire_json(connection.recv(timeout=3))
            if challenge.get("type") != "challenge" or challenge.get("protocol_version") != PROTOCOL_VERSION:
                raise ValueError("unexpected gateway challenge")
            nonce = challenge.get("challenge")
            if not isinstance(nonce, str):
                raise ValueError("invalid gateway challenge nonce")
            session_id = secrets.token_hex(16)
            handshake = GatewayHandshake(
                gateway_session_id=session_id,
                device_sn=device_sn,
                robot_model=robot_model,
                package_version=package_version,
            )
            hello = GatewayHello(
                gateway_id=self.gateway_id,
                challenge=nonce,
                handshake=handshake,
                auth_tag=hello_auth_tag(
                    self.secret, gateway_id=self.gateway_id,
                    challenge=nonce, handshake=handshake,
                ),
            )
            connection.send(hello.model_dump_json())
            accepted = parse_wire_json(connection.recv(timeout=3))
            if (
                accepted.get("type") != "accepted"
                or accepted.get("gateway_session_id") != session_id
            ):
                raise ValueError("gateway session was not accepted")
        except Exception:
            connection.close()
            raise
        self._connection = connection
        self.session_id = session_id
        self._message_sequence = 0
        return session_id

    def close(self) -> None:
        connection = self._connection
        self._connection = None
        self.session_id = None
        self._message_sequence = 0
        if connection is not None:
            try:
                connection.close()
            except Exception:
                # Command ownership cleanup below is mandatory even when the
                # WebSocket implementation itself fails during close.
                pass

        # A lost WebSocket does not cancel a WayPoint already handed to the
        # controller.  Do not reconnect (and therefore do not accept another
        # motion command) until the old command handler has fully unwound.
        with self._command_lock:
            command_thread = self._command_thread
            priority_threads = tuple(self._priority_threads.values())
        if (
            command_thread is not None
            and command_thread is not threading.current_thread()
        ):
            while command_thread.is_alive():
                command_thread.join(timeout=0.1)
        for priority_thread in priority_threads:
            if priority_thread is threading.current_thread():
                continue
            while priority_thread.is_alive():
                priority_thread.join(timeout=0.1)
        with self._command_lock:
            self._command_result = None
            self._active_command_id = None
            self._priority_results.clear()
            self._priority_kinds.clear()
            self._priority_threads.clear()
            if self._command_thread is command_thread:
                self._command_thread = None
            self._sync_priority_compat_locked()

    def _run_command(
        self,
        frame: GatewayCommandFrame,
        *,
        session_id: str,
        received_at_monotonic_ns: int,
        is_stop: bool = False,
    ) -> None:
        handler = self.stop_handler if is_stop else self.command_handler
        assert handler is not None
        self._command_context.received_at_monotonic_ns = received_at_monotonic_ns
        try:
            try:
                # created_at_ms/expires_at_ms are stamped by the server.  The
                # Mac must never compare them with its own wall clock: even a
                # small host clock skew can make a freshly received proposal
                # look expired.  The server authorizes execution in the ACK;
                # once authorized, all local deadlines use this immutable
                # Mac monotonic receipt timestamp.
                result = handler(
                    frame.envelope,
                    frame.fingerprint,
                )
            except Exception as exc:
                result = RobotCommandResult(
                    gateway_session_id=frame.envelope.gateway_session_id,
                    command_id=frame.envelope.command_id,
                    command_kind=frame.envelope.command_kind,
                    status=ToolStatus.FAILED,
                    error_code=ErrorCode.INTERNAL_ERROR,
                    error_message=f"{type(exc).__name__}: {exc}"[:512],
                    software_stop=(
                        SoftwareStopResult(
                            delivery=StopDelivery.UNKNOWN,
                            motion_stop=MotionStopConfirmation.UNCONFIRMED,
                        )
                        if frame.envelope.command_kind
                        == GatewayCommandKind.SOFTWARE_STOP_REQUEST
                        else None
                    ),
                )
            with self._command_lock:
                command_id = frame.envelope.command_id
                still_active = (
                    command_id in self._priority_kinds
                    if is_stop
                    else self._active_command_id == command_id
                )
                if self.session_id == session_id and still_active:
                    result_frame = GatewayCommandResultFrame(
                        fingerprint=frame.fingerprint,
                        result=result,
                    )
                    if is_stop:
                        if (
                            frame.envelope.command_kind
                            == GatewayCommandKind.SOFTWARE_STOP_REQUEST
                        ):
                            self._priority_results.appendleft(result_frame)
                        else:
                            self._priority_results.append(result_frame)
                        self._sync_priority_compat_locked()
                    else:
                        self._command_result = result_frame
        finally:
            del self._command_context.received_at_monotonic_ns

    def command_received_monotonic_ns(self) -> int:
        """Return this command worker's immutable Mac receipt timestamp."""
        value = getattr(
            self._command_context,
            "received_at_monotonic_ns",
            None,
        )
        if value is None:
            raise RuntimeError("command receipt time is unavailable outside its worker")
        return value

    def _flush_command_result(self) -> None:
        if self._connection is None:
            raise RuntimeError("cloud is disconnected")
        with self._command_lock:
            is_stop = bool(self._priority_results)
            frame = (
                self._priority_results[0]
                if is_stop
                else self._command_result
            )
        if frame is None:
            return
        self._connection.send(frame.model_dump_json())
        response = parse_wire_json(self._connection.recv(timeout=3))
        if (
            response.get("type") != "command_result_ack"
            or response.get("command_id") != frame.result.command_id
        ):
            raise ValueError("gateway command result acknowledgement is missing")
        with self._command_lock:
            if is_stop and self._priority_results and (
                self._priority_results[0] == frame
            ):
                self._priority_results.popleft()
                command_id = frame.result.command_id
                self._priority_kinds.pop(command_id, None)
                self._priority_threads.pop(command_id, None)
                self._sync_priority_compat_locked()
            elif not is_stop and self._command_result == frame:
                self._command_result = None
                self._active_command_id = None
                self._command_thread = None

    def _send_and_confirm(self, payload: GatewayStateFrame | GatewayHeartbeat) -> None:
        if self._connection is None:
            raise RuntimeError("cloud is disconnected")
        self._flush_command_result()
        self._connection.send(payload.model_dump_json())
        while True:
            response = parse_wire_json(self._connection.recv(timeout=3))
            if response.get("type") == "command":
                frame = GatewayCommandFrame.model_validate(response)
                # Pause, resume and hard software-stop must run beside the
                # long-lived motion worker and share that worker's owned
                # 10003 client.  Pause/resume are serialized, while a hard
                # stop is always admitted and may overtake a control worker
                # which is waiting for dual-channel confirmation.
                is_stop = frame.envelope.command_kind in {
                    GatewayCommandKind.SOFTWARE_STOP_REQUEST,
                    GatewayCommandKind.PAUSE_REQUEST,
                    GatewayCommandKind.RESUME_REQUEST,
                }
                handler = self.stop_handler if is_stop else self.command_handler
                if handler is None:
                    rejection = self._rejections.reject(
                        frame.envelope, active_session_id=self.session_id,
                    )
                    raise PermissionError(
                        f"gateway has no command executor for {rejection.command_id}"
                    )
                with self._command_lock:
                    if is_stop:
                        is_hard_stop = (
                            frame.envelope.command_kind
                            == GatewayCommandKind.SOFTWARE_STOP_REQUEST
                        )
                        if self._priority_kinds and not is_hard_stop:
                            raise RuntimeError(
                                "gateway already has an active pause/resume control"
                            )
                    elif self._active_command_id is not None:
                        raise RuntimeError("gateway already has an active remote command")
                    session_id = self.session_id
                    if session_id is None:
                        raise RuntimeError(
                            "command arrived without an active gateway session"
                        )
                    if is_stop:
                        self._priority_kinds[frame.envelope.command_id] = (
                            frame.envelope.command_kind
                        )
                        self._sync_priority_compat_locked()
                    else:
                        self._active_command_id = frame.envelope.command_id
                    received_at_monotonic_ns = time.monotonic_ns()
                self._connection.send(GatewayCommandAcceptedFrame(
                    command_id=frame.envelope.command_id,
                    fingerprint=frame.fingerprint,
                ).model_dump_json())
                authorization = parse_wire_json(
                    self._connection.recv(timeout=3)
                )
                if (
                    authorization.get("type") != "ack"
                    or authorization.get("message_sequence")
                    != payload.message_sequence
                    or authorization.get("command_id")
                    != frame.envelope.command_id
                    or not isinstance(authorization.get("execute"), bool)
                ):
                    raise ValueError(
                        "gateway command execution authorization is missing or mismatched"
                    )
                if authorization["execute"] is not True:
                    # The server remains the source of truth for the failed
                    # command record.  No result is emitted because no Mac
                    # command handler (and therefore no robot write) ran.
                    with self._command_lock:
                        if (
                            is_stop
                            and frame.envelope.command_id in self._priority_kinds
                        ):
                            self._priority_kinds.pop(
                                frame.envelope.command_id,
                                None,
                            )
                            self._priority_threads.pop(
                                frame.envelope.command_id,
                                None,
                            )
                            self._priority_results = deque(
                                result
                                for result in self._priority_results
                                if result.result.command_id
                                != frame.envelope.command_id
                            )
                            self._sync_priority_compat_locked()
                        elif self._active_command_id == frame.envelope.command_id:
                            self._active_command_id = None
                            self._command_thread = None
                            self._command_result = None
                    return
                with self._command_lock:
                    if (
                        self.session_id != session_id
                        or (
                            frame.envelope.command_id not in self._priority_kinds
                            if is_stop
                            else self._active_command_id
                            != frame.envelope.command_id
                        )
                    ):
                        raise RuntimeError(
                            "gateway session changed before command authorization"
                        )
                    worker = threading.Thread(
                        target=self._run_command,
                        args=(frame,),
                        kwargs={
                            "session_id": session_id,
                            "received_at_monotonic_ns": received_at_monotonic_ns,
                            "is_stop": is_stop,
                        },
                        daemon=True,
                    )
                    if is_stop:
                        self._priority_threads[
                            frame.envelope.command_id
                        ] = worker
                        self._sync_priority_compat_locked()
                    else:
                        self._command_thread = worker
                    worker.start()
                return
            if response.get("type") != "ack" or response.get("message_sequence") != payload.message_sequence:
                raise ValueError("gateway acknowledgement is missing or mismatched")
            return
    # 将 RobotTelemetry 转化为 GatewayStateFrame，准备发送给服务器
    def send_state(self, state: RobotTelemetry) -> None:
        if self.session_id is None:
            raise RuntimeError("cloud is disconnected")
        self._message_sequence += 1
        self._send_and_confirm(GatewayStateFrame(
            gateway_session_id=self.session_id,
            message_sequence=self._message_sequence,
            state=state,
        ))

    def send_heartbeat(self, *, datasheet: LinkState, command_socket: LinkState) -> None:
        if self.session_id is None:
            raise RuntimeError("cloud is disconnected")
        self._message_sequence += 1
        self._send_and_confirm(GatewayHeartbeat(
            gateway_session_id=self.session_id,
            message_sequence=self._message_sequence,
            datasheet=datasheet,
            command_socket=command_socket,
        ))
