"""Bounded ASCII command framing for the V6 read-only allowlist."""

from __future__ import annotations

import re

from .models import (
    CommandReply, NAMED_READ_COMMANDS, ProtocolError, REPLY_FIELD_COUNTS,
    ROBOT_ID_COMMANDS, ReadCommand,
)

MAX_COMMAND_BYTES = 128
MAX_REPLY_BYTES = 4096
_ERROR_CODE = re.compile(r"[1-9][0-9]*\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


def validate_identifier(value: str) -> str:
    """Validate a future WayPoint ID without enabling any motion command."""
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError("identifier must be 1..64 safe ASCII characters")
    return value


def encode_read(command: ReadCommand, *, robot_id: int = 0, name: str | None = None) -> bytes:
    if not isinstance(command, ReadCommand):
        raise TypeError("only listed read-only commands are allowed")
    if type(robot_id) is not int or not 0 <= robot_id <= 5:
        raise ValueError("robot_id must be an integer from 0 to 5")
    fields = [command.value]
    if command in ROBOT_ID_COMMANDS:
        fields.append(str(robot_id))
    elif robot_id != 0:
        raise ValueError("this command has no robot_id parameter")
    if command in NAMED_READ_COMMANDS:
        if name is None:
            raise ValueError("named read requires an approved name")
        fields.append(validate_identifier(name))
    elif name is not None:
        raise ValueError("this command has no name parameter")
    frame = (",".join(fields) + ",;").encode("ascii")
    if len(frame) > MAX_COMMAND_BYTES:
        raise ValueError("command exceeds maximum length")
    return frame


class CommandFrameDecoder:
    """Incremental semicolon framing; keeps unconsumed bytes across recv calls."""

    def __init__(self, *, max_reply_bytes: int = MAX_REPLY_BYTES) -> None:
        if max_reply_bytes < 16:
            raise ValueError("max_reply_bytes is too small")
        self.max_reply_bytes = max_reply_bytes
        self._pending = bytearray()

    @property
    def pending(self) -> bool:
        return bool(self._pending)

    def feed(self, data: bytes) -> list[bytes]:
        if not isinstance(data, bytes):
            raise TypeError("TCP data must be bytes")
        if len(self._pending) + len(data) > self.max_reply_bytes * 2:
            raise ProtocolError("reply receive chunk exceeds bounded buffer")
        self._pending.extend(data)
        frames: list[bytes] = []
        while (end := self._pending.find(b";")) >= 0:
            if end + 1 > self.max_reply_bytes:
                raise ProtocolError("reply frame exceeds maximum length")
            frames.append(bytes(self._pending[:end + 1]))
            del self._pending[:end + 1]
        if len(self._pending) > self.max_reply_bytes:
            raise ProtocolError("unterminated reply exceeds maximum length")
        return frames


def decode_reply(frame: bytes, *, expected: ReadCommand) -> CommandReply:
    if not isinstance(expected, ReadCommand):
        raise TypeError("expected must be a read command")
    if len(frame) > MAX_REPLY_BYTES or not frame.endswith(b";"):
        raise ProtocolError("invalid or oversized reply terminator")
    try:
        message = frame.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ProtocolError(f"invalid UTF-8 reply (prefix={frame[:32].hex()})") from exc
    if any(ord(char) < 32 or ord(char) == 127 for char in message):
        raise ProtocolError("control character in reply")
    canonical = message.endswith(",;")
    fields = message[:-2].split(",") if canonical else message[:-1].split(",")
    if len(fields) < 2 or fields[0] != expected.value:
        raise ProtocolError("command echo does not match pending request")
    if fields[1] == "OK":
        if not canonical or len(fields[2:]) != REPLY_FIELD_COUNTS[expected]:
            raise ProtocolError("wrong number of success fields")
        if any(not field for field in fields[2:]):
            raise ProtocolError("empty success field")
        return CommandReply(expected, tuple(fields[2:]))
    if fields[1] != "Fail" or len(fields) < 3 or not _ERROR_CODE.fullmatch(fields[2]):
        raise ProtocolError("invalid reply status or failure code")
    # Explanations are vendor-controlled and may contain commas. Bound them.
    explanation = ",".join(fields[3:])[:512] or None
    return CommandReply(
        expected,
        vendor_error_code=int(fields[2]),
        vendor_error_message=explanation,
        protocol_deviation=not canonical,
    )
