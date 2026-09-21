"""Scriptable loopback-only HansRobot fake; never executes motion commands."""

from __future__ import annotations

import copy
import json
import math
import socket
import struct
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from edge_gateway.huayan.command_codec import MAX_COMMAND_BYTES
from edge_gateway.huayan.models import (
    FAST_PORT_COMMANDS, NAMED_READ_COMMANDS, ROBOT_ID_COMMANDS, ReadCommand,
)

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "huayan" / "datasheet-v6.json"
MAX_RECORDED_COMMANDS = 4096


def datasheet_document() -> dict[str, Any]:
    return copy.deepcopy(json.loads(_FIXTURE.read_text(encoding="utf-8")))


def datasheet_frame(document: dict[str, Any], *, byte_order: str = "little") -> bytes:
    payload = json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    fmt = "<II" if byte_order == "little" else ">II" if byte_order == "big" else None
    if fmt is None:
        raise ValueError("choose little or big byte order")
    return b"LTBR" + struct.pack(fmt, len(payload) + 12, len(payload)) + payload


@dataclass(frozen=True)
class CommandAction:
    # None means response lost and socket closed. Several chunks simulate TCP splits.
    chunks: tuple[bytes, ...] | None
    delay_s: float = 0.0


DEFAULT_REPLIES: dict[ReadCommand, bytes] = {
    ReadCommand.IS_SIMULATION: b"IsSimulation,OK,0,;",
    ReadCommand.CONTROLLER_STATE: b"ReadControllerState,OK,1,;",
    ReadCommand.ROBOT_MODEL: b"ReadRobotModel,OK,E05-Pro,;",
    ReadCommand.PACKAGE_VERSION: b"PackageVersion,OK,6.3.6.20240305,;",
    ReadCommand.ROBOT_STATE: b"ReadRobotState,OK,0,1,0,0,0,1,0,0,0,1,1,1,1,;",
    ReadCommand.CURRENT_FSM: b"ReadCurFSM,OK,33,;",
    ReadCommand.ACTUAL_POSITION: (
        b"ReadActPos,OK,0,0,81.099,0,81.099,0,367.945,0,359.628,180,17.803,180,"
        b"0,0,0,0,0,0,0,0,0,0,0,0,;"
    ),
    ReadCommand.EMERGENCY_INFO: b"ReadEmergencyInfo,OK,0,0,0,0,;",
    ReadCommand.CURRENT_WAYPOINT_ID: b"ReadCurWayPointID,OK,FAKE_ONLY,;",
    ReadCommand.AXIS_ERROR_CODE: b"ReadAxisErrorCode,OK,0,0,0,0,0,0,0,;",
    ReadCommand.PAYLOAD: b"ReadPayload,OK,1.500000,12.000000,25.000000,39.000000,;",
    ReadCommand.JOINT_MAX_VELOCITY: b"ReadJointMaxVel,OK,150,150,160,170,180,180,;",
    ReadCommand.JOINT_MAX_ACCELERATION: b"ReadJointMaxAcc,OK,300,300,320,340,350,360,;",
    ReadCommand.LINEAR_MAX_MOTION: b"ReadLinearMaxVel,OK,2000,2500,5000,;",
    ReadCommand.BASE_INSTALLING_ANGLE: b"GetBaseInstallingAngle,OK,90,90,;",
    ReadCommand.CURRENT_TCP: b"ReadCurTCP,OK,60,80,120,50,0,0,;",
    ReadCommand.CURRENT_UCS: b"ReadCurUCS,OK,0,0,0,0,0,0,;",
    ReadCommand.TCP_BY_NAME: b"ReadTCPByName,OK,60,80,120,50,0,0,;",
    ReadCommand.UCS_BY_NAME: b"ReadUCSByName,OK,0,0,0,0,0,0,;",
}


class FakeHuayanController:
    """Three local listeners: ordinary commands, fast reads, 20 Hz DataSheet."""

    def __init__(
        self,
        *,
        command_actions: dict[ReadCommand, list[CommandAction]] | None = None,
        motion_actions: dict[str, list[CommandAction]] | None = None,
        accept_fake_motion: bool = False,
        data_actions: list[bytes | float] | None = None,
        data_interval_s: float = 0.05,
        stamp_every_n_frames: int = 1,
        byte_order: str = "little",
    ) -> None:
        if data_interval_s <= 0:
            raise ValueError("data_interval_s must be positive")
        if stamp_every_n_frames < 1:
            raise ValueError("stamp_every_n_frames must be positive")
        self._byte_order = byte_order
        self._data_interval_s = data_interval_s
        self._stamp_every_n_frames = stamp_every_n_frames
        self._data_actions = data_actions
        self._command_actions = defaultdict(deque)
        for command, actions in (command_actions or {}).items():
            self._command_actions[command].extend(actions)
        self._motion_actions = defaultdict(deque)
        for command, actions in (motion_actions or {}).items():
            self._motion_actions[command].extend(actions)
        self.accept_fake_motion = accept_fake_motion
        self._current_waypoint_id = "FAKE_ONLY"
        # Keep test diagnostics bounded during long-running gateway soak tests.
        self.received_commands: list[bytes] = []
        self._stop = threading.Event()
        self._listeners: list[socket.socket] = []
        self._threads: list[threading.Thread] = []
        self.command_port = 0
        self.fast_port = 0
        self.datasheet_port = 0

    @classmethod
    def scenario(
        cls,
        name: Literal[
            "delayed_start", "never_start", "never_arrive",
            "contradictory_state", "external_waypoint",
        ],
    ) -> "FakeHuayanController":
        """Deterministic later-motion diagnostics without accepting motion bytes."""
        if name == "external_waypoint":
            return cls(command_actions={
                ReadCommand.CURRENT_WAYPOINT_ID: [
                    CommandAction((b"ReadCurWayPointID,OK,EXTERNAL_WRITER,;",))
                ],
            })

        def state_frame(fsm: int, moving: int, in_position: int) -> bytes:
            document = datasheet_document()
            state = document["StateAndError"]
            state["robotState"] = fsm
            state["robotMoving"] = moving
            state["InPos"] = in_position
            state["robotBlendingDone"] = int(not moving)
            return datasheet_frame(document)

        idle = state_frame(33, 0, 1)
        moving = state_frame(25, 1, 0)
        if name == "delayed_start":
            actions: list[bytes | float] = [idle, 0.05, moving, 0.05, idle]
        elif name == "never_start":
            actions = [idle, 0.05, idle, 0.05, idle]
        elif name == "never_arrive":
            actions = [moving, 0.05, moving, 0.05, moving]
        elif name == "contradictory_state":
            actions = [state_frame(33, 1, 1)]
        else:
            raise ValueError("unknown fake scenario")
        return cls(data_actions=actions)

    def start(self) -> "FakeHuayanController":
        if self._listeners:
            raise RuntimeError("fake controller already started")
        for kind in ("command", "fast", "data"):
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen(4)
            listener.settimeout(0.1)
            self._listeners.append(listener)
            setattr(self, f"{kind if kind != 'data' else 'datasheet'}_port", listener.getsockname()[1])
            thread = threading.Thread(target=self._serve, args=(listener, kind), daemon=True)
            thread.start()
            self._threads.append(thread)
        return self

    def close(self) -> None:
        self._stop.set()
        for listener in self._listeners:
            listener.close()
        for thread in self._threads:
            thread.join(timeout=1)
        self._listeners.clear()
        self._threads.clear()

    def __enter__(self) -> "FakeHuayanController":
        return self.start()

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _serve(self, listener: socket.socket, kind: str) -> None:
        while not self._stop.is_set():
            try:
                connection, _address = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with connection:
                connection.settimeout(0.1)
                try:
                    if kind == "data":
                        self._serve_data(connection)
                    else:
                        self._serve_commands(connection, fast=(kind == "fast"))
                except (BrokenPipeError, ConnectionResetError, OSError):
                    continue

    def _serve_commands(self, connection: socket.socket, *, fast: bool) -> None:
        buffer = bytearray()
        while not self._stop.is_set():
            try:
                chunk = connection.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                return
            buffer.extend(chunk)
            if len(buffer) > MAX_COMMAND_BYTES or b";" not in buffer:
                if len(buffer) > MAX_COMMAND_BYTES:
                    return
                continue
            end = buffer.index(b";") + 1
            frame = bytes(buffer[:end])
            self.received_commands.append(frame)
            if len(self.received_commands) > MAX_RECORDED_COMMANDS:
                del self.received_commands[:len(self.received_commands) - MAX_RECORDED_COMMANDS]
            # The documented controller accepts only the first complete command
            # from a multi-command send; any trailing bytes are discarded.
            pipelined = len(buffer) != end
            buffer.clear()
            if not frame.endswith(b",;"):
                connection.sendall(b"Unknown,Fail,20007,malformed command,;")
                if pipelined:
                    return
                continue
            fields = frame[:-2].split(b",")
            name = fields[0].decode("ascii", errors="replace")
            if name == "FakeOnlyIdentity" and self.accept_fake_motion and not fast:
                if fields != [b"FakeOnlyIdentity"]:
                    connection.sendall(b"FakeOnlyIdentity,Fail,20006,invalid parameters,;")
                else:
                    connection.sendall(b"FakeOnlyIdentity,OK,INTERN-S2-FAKE-MOTION-V1,;")
                continue
            if name in ("WayPoint", "GrpStop") and self.accept_fake_motion and not fast:
                if name == "WayPoint":
                    valid = (
                        len(fields) == 25 and fields[1] == b"0"
                        and all(part == b"0" for part in fields[8:14])
                        and fields[15] == b"Base"
                        and fields[19:24] == [b"1", b"0", b"0", b"0", b"0"]
                        and 1 <= len(fields[24]) <= 64
                    )
                    if valid:
                        try:
                            numeric = [float(value) for value in (*fields[2:8], fields[16], fields[17], fields[18])]
                            valid = (all(math.isfinite(value) for value in numeric)
                                     and numeric[6] > 0 and numeric[7] > 0 and numeric[8] == 0)
                        except ValueError:
                            valid = False
                    if valid:
                        self._current_waypoint_id = fields[24].decode("ascii", errors="replace")
                else:
                    valid = fields == [b"GrpStop", b"0"]
                if not valid:
                    connection.sendall(f"{name},Fail,20006,invalid parameters,;".encode())
                    continue
                action = self._motion_actions[name].popleft() if self._motion_actions[name] else None
                if action is None:
                    action = CommandAction((f"{name},OK,;".encode(),))
                if action.delay_s and self._stop.wait(action.delay_s):
                    return
                if action.chunks is None:
                    return
                for part in action.chunks:
                    connection.sendall(part)
                if pipelined:
                    return
                continue
            try:
                command = ReadCommand(name)
            except ValueError:
                connection.sendall(b"Unknown,Fail,20005,read-only fake,;")
                if pipelined:
                    return
                continue
            valid_args = (
                len(fields) == (3 if command in NAMED_READ_COMMANDS else 2)
                and fields[1] in (b"0", b"1", b"2", b"3", b"4", b"5")
                and (command not in NAMED_READ_COMMANDS or (
                    fields[2].isascii() and fields[2].replace(b"_", b"").replace(b"-", b"").isalnum()
                    and 1 <= len(fields[2]) <= 64
                ))
                if command in ROBOT_ID_COMMANDS else len(fields) == 1
            )
            if not valid_args:
                connection.sendall(f"{name},Fail,20006,invalid parameters,;".encode("ascii"))
                if pipelined:
                    return
                continue
            if fast and command not in FAST_PORT_COMMANDS:
                connection.sendall(f"{name},Fail,20099,not allowed on fast port,;".encode("ascii"))
                if pipelined:
                    return
                continue
            action = self._command_actions[command].popleft() if self._command_actions[command] else None
            if action is None:
                reply = (
                    f"ReadFastCmdPort,OK,{self.fast_port},;".encode("ascii")
                    if command == ReadCommand.FAST_COMMAND_PORT
                    else f"ReadCurWayPointID,OK,{self._current_waypoint_id},;".encode("ascii")
                    if command == ReadCommand.CURRENT_WAYPOINT_ID and self.accept_fake_motion
                    else DEFAULT_REPLIES[command]
                )
                action = CommandAction((reply,))
            if action.delay_s:
                if self._stop.wait(action.delay_s):
                    return
            if action.chunks is None:
                return
            for part in action.chunks:
                connection.sendall(part)
            if pipelined:
                return

    def _serve_data(self, connection: socket.socket) -> None:
        if self._data_actions is not None:
            for action in self._data_actions:
                if self._stop.is_set():
                    return
                if isinstance(action, float):
                    if self._stop.wait(action):
                        return
                else:
                    connection.sendall(action)
            return
        frame_index = 0
        source_stamp_ms = 0
        while not self._stop.is_set():
            document = datasheet_document()
            if frame_index % self._stamp_every_n_frames == 0:
                source_stamp_ms = time.time_ns() // 1_000_000
            document["MsgTitle"]["Stamp"] = str(source_stamp_ms)
            frame = datasheet_frame(document, byte_order=self._byte_order)
            connection.sendall(frame)
            frame_index += 1
            if self._stop.wait(self._data_interval_s):
                return
