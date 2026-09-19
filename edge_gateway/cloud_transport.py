"""Mac-initiated, authenticated WebSocket over a local SSH tunnel."""

from __future__ import annotations

import ipaddress
import json
import secrets
from urllib.parse import urlparse

from surgical_contracts import (
    CoordinateFrame,
    DistanceUnit,
    GatewayControlMode,
    GatewayHandshake,
    GatewayHeartbeat,
    GatewayHello,
    GatewayStateFrame,
    LinkState,
    MotionState,
    Pose6D,
    PROTOCOL_VERSION,
    RobotCommandEnvelope,
    RobotConnectionState,
    RobotProvider,
    RobotTelemetry,
    RuntimeMode,
    SourceFreshness,
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
        control_mode="observe-only",
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
            MotionState.MOVING if sample.moving or sample.fsm_code in (25, 26, 27, 47)
            else MotionState.IDLE
        ),
        potentially_moving=sample.moving or sample.fsm_code in (25, 26, 27, 47),
        fsm_code=sample.fsm_code,
        enabled=(robot_status.enabled if robot_status is not None else sample.enabled),
        electrified=(robot_status.electrified if robot_status is not None else None),
        brakes_released=(
            robot_status.brakes_released
            if robot_status is not None
            else all(sample.brake_states)
        ),
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
    def __init__(self, url: str, *, secret: bytes, gateway_id: str, config_sha256: str) -> None:
        self.url = validate_cloud_url(url)
        if len(secret) < 32:
            raise ValueError("gateway secret is too short")
        self.secret = secret
        self.gateway_id = gateway_id
        self.config_sha256 = config_sha256
        self.session_id: str | None = None
        self._connection = None
        self._message_sequence = 0
        self._rejections = RejectOnlyLedger()

    def connect(self, *, device_sn: str, robot_model: str, package_version: str) -> str:
        from websockets.sync.client import connect

        if self._connection is not None:
            raise RuntimeError("cloud connection is already open")
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
                safety_config_sha256=self.config_sha256,
                control_mode=GatewayControlMode.OBSERVE_ONLY,
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
                or accepted.get("control_mode") != "observe-only"
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
        if self._connection is not None:
            self._connection.close()
        self._connection = None
        self.session_id = None
        self._message_sequence = 0

    def _send_and_confirm(self, payload: GatewayStateFrame | GatewayHeartbeat) -> None:
        if self._connection is None:
            raise RuntimeError("cloud is disconnected")
        self._connection.send(payload.model_dump_json())
        while True:
            response = parse_wire_json(self._connection.recv(timeout=3))
            if response.get("type") == "command":
                envelope = RobotCommandEnvelope.model_validate(response.get("envelope"))
                rejection = self._rejections.reject(envelope, active_session_id=self.session_id)
                self._connection.send(json.dumps({
                    "type": "command_rejected",
                    "result": rejection.model_dump(mode="json"),
                }, separators=(",", ":")))
                continue
            if response.get("type") != "ack" or response.get("message_sequence") != payload.message_sequence:
                raise ValueError("gateway acknowledgement is missing or mismatched")
            return

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
