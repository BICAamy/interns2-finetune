"""Scriptable loopback-only HansRobot fake; never executes motion commands."""

from __future__ import annotations

import copy
import json
import socket
import struct
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from edge_gateway.huayan.command_codec import MAX_COMMAND_BYTES
from edge_gateway.huayan.models import FAST_PORT_COMMANDS, ROBOT_ID_COMMANDS, ReadCommand

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "huayan" / "datasheet-v6.json"


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
}


class FakeHuayanController:
    """Three local listeners: ordinary commands, fast reads, 20 Hz DataSheet."""

    def __init__(
        self,
        *,
        command_actions: dict[ReadCommand, list[CommandAction]] | None = None,
        data_actions: list[bytes | float] | None = None,
        data_interval_s: float = 0.05,
        byte_order: str = "little",
    ) -> None:
        if data_interval_s <= 0:
            raise ValueError("data_interval_s must be positive")
        self._byte_order = byte_order
        self._data_interval_s = data_interval_s
        self._data_actions = data_actions
        self._command_actions = defaultdict(deque)
        for command, actions in (command_actions or {}).items():
            self._command_actions[command].extend(actions)
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
            try:
                command = ReadCommand(name)
            except ValueError:
                connection.sendall(b"Unknown,Fail,20005,read-only fake,;")
                if pipelined:
                    return
                continue
            valid_args = (
                len(fields) == 2 and fields[1] in (b"0", b"1", b"2", b"3", b"4", b"5")
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
        while not self._stop.is_set():
            document = datasheet_document()
            document["MsgTitle"]["Stamp"] = str(time.time_ns() // 1_000_000)
            frame = datasheet_frame(document, byte_order=self._byte_order)
            connection.sendall(frame)
            if self._stop.wait(self._data_interval_s):
                return
