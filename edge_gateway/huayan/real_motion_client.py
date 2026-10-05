"""Single-use 10003 writer for Mac-local commissioning and the Mac gateway.

The regular gateway imports only the read-only CommandClient. Constructing
this class does not connect; connect() checks the local terminal and controller
identity again. Only this Mac-local client exposes explicit group enable,
disable, WayPoint and owned-stop writes. It never resets, changes IO, or sends
scripts.
"""

from __future__ import annotations

import socket
import threading

from robot_runtime.real_config import RealRobotConfig

from .adapter import (
    read_controller_started, read_identity_text, read_is_simulation,
    read_override, read_waypoint_id,
)
from .command_client import _private_controller_host
from .command_codec import CommandFrameDecoder, decode_reply, encode_read
from .models import CommandReply, ProtocolError, ReadCommand, ResponseUnknown
from .motion_codec import (
    JointWaypoint, LinearWaypoint, decode_write_reply, encode_group_enabled,
    encode_software_stop, encode_speed_override,
)


class LocalRealMotionClient:
    def __init__(
        self,
        config: RealRobotConfig,
        *,
        timeout_s: float,
        require_local_terminal: bool = True,
    ) -> None:
        controller = config.controller
        if config.tool.setup != "flange_only_no_tool":
            raise ValueError("real control requires the approved bare-flange profile")
        if config.blocking_fields():
            raise ValueError("real commissioning config has missing fields")
        if controller.host is None or controller.command_port != 10003:
            raise ValueError("real commissioning requires the private 10003 controller")
        self.host = _private_controller_host(controller.host)
        self.port = controller.command_port
        response_ms = config.deadlines.response_ms
        if response_ms is None or not 0 < timeout_s <= response_ms / 1000:
            raise ValueError("socket timeout must not exceed configured response_ms")
        self.timeout_s = timeout_s
        self.config = config
        self.require_local_terminal = require_local_terminal
        self._socket: socket.socket | None = None
        self._decoder = CommandFrameDecoder()
        self._lock = threading.Lock()
        self._identified = False
        self._write_command: str | None = None
        self.package_version: str | None = None

    def connect(self) -> None:
        if self.require_local_terminal:
            from edge_gateway.commissioning_cli import require_local_mac_terminal

            require_local_mac_terminal()
        if self._socket is not None:
            raise RuntimeError("commissioning command socket is already connected")
        self._socket = socket.create_connection((self.host, self.port), self.timeout_s)
        self._socket.settimeout(self.timeout_s)
        try:
            version = read_identity_text(self.request(ReadCommand.PACKAGE_VERSION))
            model = read_identity_text(self.request(ReadCommand.ROBOT_MODEL))
            simulation = read_is_simulation(self.request(ReadCommand.IS_SIMULATION))
            started = read_controller_started(self.request(ReadCommand.CONTROLLER_STATE))
            if (
                version not in self.config.controller.package_versions
                or model != self.config.controller.model or simulation or not started
            ):
                raise ValueError("commissioning controller identity or state disagrees with config")
            self._identified = True
            self.package_version = version
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        with self._lock:
            if self._socket is not None:
                self._socket.close()
            self._socket = None
            self._decoder = CommandFrameDecoder()
            self._identified = False
            self.package_version = None

    def _exchange(self, frame: bytes) -> bytes:
        if not self._lock.acquire(timeout=self.timeout_s):
            raise ResponseUnknown("10003 busy; write/stop outcome unknown")
        try:
            if self._socket is None:
                raise RuntimeError("10003 commissioning socket is disconnected")
            if self._decoder.pending:
                self._socket.close()
                self._socket = None
                raise ProtocolError("unexpected bytes before next command")
            try:
                self._socket.sendall(frame)
                while True:
                    chunk = self._socket.recv(4096)
                    if not chunk:
                        raise ResponseUnknown("10003 closed before reply; robot may keep moving")
                    replies = self._decoder.feed(chunk)
                    if len(replies) > 1 or (replies and self._decoder.pending):
                        raise ProtocolError("unsolicited or pipelined controller reply")
                    if replies:
                        return replies[0]
            except socket.timeout as exc:
                self._socket.close()
                self._socket = None
                raise ResponseUnknown(
                    f"10003 response timed out after {self.timeout_s:g}s; never replay"
                ) from exc
            except ResponseUnknown:
                self._socket.close()
                self._socket = None
                raise
            except OSError as exc:
                self._socket.close()
                self._socket = None
                raise ResponseUnknown(
                    f"10003 transport failed with {type(exc).__name__}; never replay"
                ) from exc
            except ProtocolError:
                self._socket.close()
                self._socket = None
                raise
            except BaseException:
                # A terminal interrupt may arrive after sendall transmitted
                # bytes. Do not reuse a socket with an unknown reply boundary.
                self._socket.close()
                self._socket = None
                raise
        finally:
            self._lock.release()

    def request(self, command: ReadCommand, *, name: str | None = None) -> CommandReply:
        try:
            return decode_reply(
                self._exchange(encode_read(command, name=name)), expected=command,
            )
        except ProtocolError as exc:
            raise ProtocolError(f"{command.value} reply invalid: {exc}") from exc
        except ResponseUnknown as exc:
            raise ResponseUnknown(f"{command.value} read failed: {exc}") from exc

    def current_waypoint_id(self) -> str | None:
        return read_waypoint_id(self.request(ReadCommand.CURRENT_WAYPOINT_ID))

    def current_override(self) -> float:
        return read_override(self.request(ReadCommand.OVERRIDE))

    def set_override(
        self, value: float, *, stationary_confirmed: bool = False,
    ) -> bool:
        """Set one controller-wide speed ratio after dual-channel stationary proof."""
        if not self._identified or self._write_command is not None:
            raise RuntimeError("SetOverride requires an identified, single-use local session")
        if not stationary_confirmed:
            raise PermissionError("SetOverride requires prior dual-channel stationary confirmation")
        encoded = encode_speed_override(value)
        self._write_command = "SetOverride"
        try:
            return decode_write_reply(self._exchange(encoded), command="SetOverride")
        except ResponseUnknown as exc:
            raise ResponseUnknown(f"SetOverride outcome unknown: {exc}") from exc

    def waypoint(self, waypoint: LinearWaypoint | JointWaypoint) -> bool:
        if not self._identified or self._write_command is not None:
            raise RuntimeError("real WayPoint requires an identified, single-use local session")
        if waypoint.tcp_name != self.config.tool.tcp_name or waypoint.ucs_name != "Base":
            raise ValueError("WayPoint TCP/UCS disagrees with bare-flange config")
        if isinstance(waypoint, LinearWaypoint):
            if waypoint.speed_mm_s > self.config.limits.max_speed_mm_s or (
                waypoint.acceleration_mm_s2 > self.config.limits.max_acceleration_mm_s2
            ):
                raise ValueError("WayPoint exceeds limits configured in robot-real.local.yaml")
            low = self.config.limits.workspace_low_mm
            high = self.config.limits.workspace_high_mm
            if any(not lo <= value <= hi for value, lo, hi in zip(waypoint.pose_xyzrpy[:3], low, high)):
                raise ValueError("WayPoint target is outside the approved workspace")
            joints = waypoint.reference_joints_deg
        else:
            if waypoint.speed_deg_s > self.config.motion.joint_speed_deg_s or (
                waypoint.acceleration_deg_s2
                > self.config.motion.joint_acceleration_deg_s2
            ):
                raise ValueError("joint WayPoint exceeds YAML speed or acceleration")
            joints = waypoint.target_joints_deg
        margin = self.config.limits.joint_margin_deg
        if any(not lo + margin <= joint <= hi - margin for joint, (lo, hi) in zip(
            joints, self.config.limits.joint_soft_limits_deg,
        )):
            raise ValueError("WayPoint reference joints exceed approved margin")
        encoded = waypoint.encode()
        self._write_command = "WayPoint"  # Set before first byte; disconnect is ambiguous.
        try:
            return decode_write_reply(self._exchange(encoded), command="WayPoint")
        except ResponseUnknown as exc:
            raise ResponseUnknown(f"WayPoint outcome unknown: {exc}") from exc

    def software_stop(self) -> bool:
        if not self._identified or self._write_command != "WayPoint":
            raise PermissionError("ordinary stop is only for this process's own attempted WayPoint")
        try:
            return decode_write_reply(self._exchange(encode_software_stop()), command="GrpStop")
        except ResponseUnknown as exc:
            raise ResponseUnknown(f"GrpStop outcome unknown: {exc}") from exc

    def prepare_next_waypoint(self, *, stationary_confirmed: bool = False) -> None:
        """Reuse this identified socket only after actual feedback confirmed arrival."""
        if not stationary_confirmed:
            raise PermissionError("next WayPoint requires confirmed stationary feedback")
        if not self._identified or self._write_command != "WayPoint":
            raise RuntimeError("no completed WayPoint is available for sequence continuation")
        self._write_command = None

    def set_enabled(
        self, enabled: bool, *, disable_stationary_confirmed: bool = False,
    ) -> bool:
        """Send one explicit lifecycle write; callers must verify real feedback."""
        if type(enabled) is not bool:
            raise TypeError("enabled must be a bool")
        if not self._identified or self._write_command is not None:
            raise RuntimeError("group enable/disable requires an identified, single-use local session")
        if not enabled and not disable_stationary_confirmed:
            raise PermissionError("GrpDisable requires prior dual-channel stationary confirmation")
        command = "GrpEnable" if enabled else "GrpDisable"
        self._write_command = command  # Set before first byte; disconnect is ambiguous.
        try:
            return decode_write_reply(
                self._exchange(encode_group_enabled(enabled)), command=command,
            )
        except ResponseUnknown as exc:
            raise ResponseUnknown(f"{command} outcome unknown: {exc}") from exc

    def __enter__(self) -> "LocalRealMotionClient":
        self.connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
