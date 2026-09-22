"""Single-use 10003 writer, reachable only from Mac-local commissioning.

The regular gateway imports only the read-only CommandClient. Constructing
this class does not connect; connect() checks the local terminal and controller
identity again. It never enables, resets, changes IO, or sends scripts.
"""

from __future__ import annotations

import socket
import threading

from robot_runtime.real_config import RealRobotConfig

from .adapter import (
    read_controller_started, read_identity_text, read_is_simulation,
    read_waypoint_id,
)
from .command_client import _private_controller_host
from .command_codec import CommandFrameDecoder, decode_reply, encode_read
from .models import CommandReply, ProtocolError, ReadCommand, ResponseUnknown
from .motion_codec import LinearWaypoint, decode_write_reply, encode_software_stop


class LocalRealMotionClient:
    def __init__(self, config: RealRobotConfig, *, timeout_s: float) -> None:
        controller = config.controller
        if config.allowed_control != "observe-only" or config.tool.setup != "flange_only_no_tool":
            raise ValueError("local commissioning requires the observe-only bare-flange profile")
        if config.blocking_fields():
            raise ValueError("real commissioning config has missing fields")
        if controller.host is None or controller.command_port != 10003:
            raise ValueError("real commissioning requires the private 10003 controller")
        self.host = _private_controller_host(controller.host)
        self.port = controller.command_port
        if not 0 < timeout_s <= 0.5:
            raise ValueError("real commissioning socket timeout must be at most 500 ms")
        self.timeout_s = timeout_s
        self.config = config
        self._socket: socket.socket | None = None
        self._decoder = CommandFrameDecoder()
        self._lock = threading.Lock()
        self._identified = False
        self._write_attempted = False
        self.package_version: str | None = None

    def connect(self) -> None:
        # Lazy import avoids making the read-only gateway depend on this CLI.
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
            except (OSError, ResponseUnknown) as exc:
                self._socket.close()
                self._socket = None
                raise ResponseUnknown("10003 outcome unknown; never replay") from exc
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
        return decode_reply(self._exchange(encode_read(command, name=name)), expected=command)

    def current_waypoint_id(self) -> str:
        return read_waypoint_id(self.request(ReadCommand.CURRENT_WAYPOINT_ID))

    def waypoint(self, waypoint: LinearWaypoint) -> bool:
        if not self._identified or self._write_attempted:
            raise RuntimeError("real WayPoint requires an identified, single-use local session")
        if waypoint.tcp_name != self.config.tool.tcp_name or waypoint.ucs_name != "Base":
            raise ValueError("WayPoint TCP/UCS disagrees with bare-flange config")
        if waypoint.speed_mm_s > min(self.config.limits.max_speed_mm_s, 5.0) or (
            waypoint.acceleration_mm_s2 > min(self.config.limits.max_acceleration_mm_s2, 20.0)
        ):
            raise ValueError("WayPoint exceeds first-motion local speed or acceleration cap")
        low = self.config.limits.workspace_low_mm
        high = self.config.limits.workspace_high_mm
        if any(not lo <= value <= hi for value, lo, hi in zip(waypoint.pose_xyzrpy[:3], low, high)):
            raise ValueError("WayPoint target is outside the approved workspace")
        joints = waypoint.reference_joints_deg
        margin = self.config.limits.joint_margin_deg
        if any(not lo + margin <= joint <= hi - margin for joint, (lo, hi) in zip(
            joints, self.config.limits.joint_soft_limits_deg,
        )):
            raise ValueError("WayPoint reference joints exceed approved margin")
        encoded = waypoint.encode()
        self._write_attempted = True  # Set before first byte; disconnect is ambiguous.
        return decode_write_reply(self._exchange(encoded), command="WayPoint")

    def software_stop(self) -> bool:
        if not self._identified or not self._write_attempted:
            raise PermissionError("ordinary stop is only for this process's own attempted WayPoint")
        return decode_write_reply(self._exchange(encode_software_stop()), command="GrpStop")

    def __enter__(self) -> "LocalRealMotionClient":
        self.connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
