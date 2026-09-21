"""Fail-closed write-ahead journal for offline fake motion trials.

This journal is deliberately not wired into the real observe-only gateway.
Every transition is append-only and fsynced before the caller may continue.
"""

from __future__ import annotations

import hashlib
import fcntl
import json
import os
from pathlib import Path
from threading import RLock
import time

from .huayan.command_codec import validate_identifier

_STATES = frozenset({
    "prepared", "send_started", "accepted", "executing", "stopping",
    "succeeded", "stopped", "not_sent", "rejected", "unknown", "stop_unconfirmed",
})
_TERMINAL = frozenset({"succeeded", "stopped", "not_sent", "rejected"})
_TRANSITIONS = {
    "prepared": {"send_started", "not_sent"},
    "send_started": {"accepted", "unknown", "stopping"},
    "accepted": {"executing", "stopping", "unknown"},
    "executing": {"succeeded", "stopping", "unknown"},
    "stopping": {"stopped", "stop_unconfirmed", "unknown"},
    "unknown": {"stopping", "stopped"},
    "stop_unconfirmed": {"stopping", "stopped"},
    "succeeded": set(), "stopped": set(), "not_sent": set(), "rejected": set(),
}


class JournalError(RuntimeError):
    pass


class CommandJournal:
    """Single-process offline journal; unresolved entries block every new trial."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = RLock()
        if self.path.is_symlink() or self.path.parent.is_symlink():
            raise JournalError("journal may not be a symlink")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_path = self.path.with_name(self.path.name + ".lock")
        if lock_path.is_symlink():
            raise JournalError("journal lock may not be a symlink")
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        self._lock_fd = os.open(lock_path, flags, 0o600)
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._records = self._load()
        except Exception as exc:
            os.close(self._lock_fd)
            self._lock_fd = -1
            if isinstance(exc, OSError):
                raise JournalError("journal is already owned by another process") from exc
            raise

    def close(self) -> None:
        with self._lock:
            if self._lock_fd >= 0:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                os.close(self._lock_fd)
                self._lock_fd = -1

    def __enter__(self) -> "CommandJournal":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        if not self.path.is_file() or self.path.stat().st_size > 10 * 1024 * 1024:
            raise JournalError("invalid or oversized command journal")
        records: dict[str, dict] = {}
        try:
            with self.path.open("rb") as stream:
                for line in stream:
                    event = json.loads(line)
                    command_id = validate_identifier(event["command_id"])
                    state = event["state"]
                    if state not in _STATES:
                        raise JournalError("unknown journal state")
                    previous = records.get(command_id)
                    if previous is None:
                        if state != "prepared" or not isinstance(event.get("fingerprint"), str):
                            raise JournalError("journal begins without prepared record")
                    elif state not in _TRANSITIONS[previous["state"]]:
                        raise JournalError("invalid journal transition")
                    records[command_id] = event
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise JournalError("corrupt command journal; refuse new motion") from exc
        return records

    def _append(self, event: dict) -> None:
        if self._lock_fd < 0:
            raise JournalError("journal is closed")
        payload = (json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(self.path, flags, 0o600)
        try:
            with os.fdopen(fd, "ab", closefd=False) as stream:
                stream.write(payload)
                stream.flush()
            os.fsync(fd)
        finally:
            os.close(fd)
        directory = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def unresolved(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(command_id for command_id, value in self._records.items()
                         if value["state"] not in _TERMINAL)

    def record(self, command_id: str) -> dict | None:
        with self._lock:
            value = self._records.get(command_id)
            return dict(value) if value is not None else None

    def prepare(
        self, *, command_id: str, fingerprint: str, session_id: str,
        safety_state_hash: str, start_sequence: int, encoded_frame: bytes,
    ) -> None:
        validate_identifier(command_id)
        if any(not isinstance(value, str) or not value for value in
               (fingerprint, session_id, safety_state_hash)):
            raise ValueError("journal identity fields must be nonempty")
        if type(start_sequence) is not int or start_sequence < 0:
            raise ValueError("start sequence must be nonnegative")
        with self._lock:
            if self._records:
                if command_id in self._records:
                    raise JournalError("command ID already used; never replay")
                if self.unresolved():
                    raise JournalError("unresolved potentially-moving command blocks new motion")
            event = {
                "command_id": command_id, "state": "prepared", "fingerprint": fingerprint,
                "session_id": session_id, "safety_state_hash": safety_state_hash,
                "start_sequence": start_sequence,
                "encoded_sha256": hashlib.sha256(encoded_frame).hexdigest(),
                "potentially_moving": True,
                "at_ms": time.time_ns() // 1_000_000,
            }
            self._append(event)
            self._records[command_id] = event

    def transition(self, command_id: str, state: str, *, evidence: str = "") -> None:
        validate_identifier(command_id)
        if state not in _STATES:
            raise ValueError("unknown journal state")
        if len(evidence) > 128:
            raise ValueError("journal evidence is too long")
        with self._lock:
            previous = self._records.get(command_id)
            if previous is None or state not in _TRANSITIONS[previous["state"]]:
                raise JournalError("invalid command journal transition")
            if state in _TERMINAL and not evidence:
                raise JournalError("terminal transition requires explicit evidence")
            event = {**previous, "state": state, "potentially_moving": state not in _TERMINAL,
                     "evidence": evidence, "at_ms": time.time_ns() // 1_000_000}
            self._append(event)
            self._records[command_id] = event
