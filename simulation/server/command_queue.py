"""Thread-safe normal and preemptive command queues."""

from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, Queue
from typing import Any

from surgical_contracts import RobotCommandKind


URGENT_COMMANDS = {RobotCommandKind.STOP, RobotCommandKind.ESTOP}


@dataclass(frozen=True)
class QueuedCommand:
    command_id: str
    kind: RobotCommandKind
    request: Any
    fingerprint: str


class SimulationCommandQueue:
    """Separate urgent commands so stop/estop can bypass normal FIFO work."""

    def __init__(self) -> None:
        self._urgent: Queue[QueuedCommand] = Queue()
        self._normal: Queue[QueuedCommand] = Queue()

    def put(self, command: QueuedCommand) -> None:
        target = self._urgent if command.kind in URGENT_COMMANDS else self._normal
        target.put(command)

    def get_urgent_nowait(self) -> QueuedCommand | None:
        try:
            return self._urgent.get_nowait()
        except Empty:
            return None

    def get_normal_nowait(self) -> QueuedCommand | None:
        try:
            return self._normal.get_nowait()
        except Empty:
            return None

    def drain_normal(self) -> list[QueuedCommand]:
        commands: list[QueuedCommand] = []
        while True:
            command = self.get_normal_nowait()
            if command is None:
                return commands
            commands.append(command)

    @property
    def depth(self) -> int:
        return self._urgent.qsize() + self._normal.qsize()
