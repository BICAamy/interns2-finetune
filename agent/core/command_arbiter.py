"""Input-source priority skeleton used by the later multimodal web layer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from surgical_contracts import CommandIntent, ParsedCommand


class CommandSource(str, Enum):
    TEXT = "text"
    VOICE = "voice"
    GESTURE = "gesture"


@dataclass(frozen=True)
class CommandCandidate:
    command: ParsedCommand
    source: CommandSource
    received_at_ms: int


def _priority(candidate: CommandCandidate) -> tuple[int, int]:
    if candidate.command.intent == CommandIntent.EMERGENCY_STOP:
        priority = 4
    elif candidate.command.intent == CommandIntent.STOP:
        priority = 3
    elif candidate.source == CommandSource.VOICE:
        priority = 2
    elif candidate.source == CommandSource.TEXT:
        priority = 2
    else:
        priority = 1
    return (priority, candidate.received_at_ms)


def choose_command(candidates: list[CommandCandidate]) -> CommandCandidate | None:
    """Choose by safety/source priority, then prefer the newest candidate."""

    if not candidates:
        return None
    return max(candidates, key=_priority)
