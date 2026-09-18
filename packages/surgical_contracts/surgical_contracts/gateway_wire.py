"""Authenticated, observe-only wire messages for the Step 5 edge session."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .base import ContractModel
from .gateway import GatewayControlMode, GatewayHandshake
from .robot import LinkState, RobotTelemetry, RuntimeMode

PROTOCOL_VERSION = "huayan-v6-observe-v1"
MAX_WIRE_BYTES = 64 * 1024


class GatewayHello(ContractModel):
    type: Literal["hello"] = "hello"
    gateway_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    protocol_version: Literal["huayan-v6-observe-v1"] = PROTOCOL_VERSION
    challenge: str = Field(pattern=r"^[0-9a-f]{32}$")
    handshake: GatewayHandshake
    auth_tag: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def observe_only(self) -> "GatewayHello":
        if self.handshake.control_mode != GatewayControlMode.OBSERVE_ONLY:
            raise ValueError("Step 5 gateway must be observe-only")
        return self


class GatewayStateFrame(ContractModel):
    type: Literal["state"] = "state"
    gateway_session_id: str = Field(min_length=1, max_length=128)
    message_sequence: int = Field(ge=1)
    state: RobotTelemetry

    @model_validator(mode="after")
    def state_matches_session(self) -> "GatewayStateFrame":
        if self.state.gateway_session_id != self.gateway_session_id:
            raise ValueError("state belongs to another gateway session")
        if self.state.runtime_mode != RuntimeMode.REAL or self.state.control_mode != "observe-only":
            raise ValueError("Step 5 state must be real and observe-only")
        return self


class GatewayHeartbeat(ContractModel):
    type: Literal["heartbeat"] = "heartbeat"
    gateway_session_id: str = Field(min_length=1, max_length=128)
    message_sequence: int = Field(ge=1)
    datasheet: LinkState
    command_socket: LinkState


def hello_auth_tag(
    secret: bytes,
    *,
    gateway_id: str,
    challenge: str,
    handshake: GatewayHandshake,
) -> str:
    payload = json.dumps(
        {
            "gateway_id": gateway_id,
            "challenge": challenge,
            "protocol_version": PROTOCOL_VERSION,
            "handshake": handshake.model_dump(mode="json"),
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def load_gateway_secret(path: str | Path) -> bytes:
    """Read a private shared secret; never log its path contents or value."""
    selected = Path(path)
    if selected.is_symlink() or not selected.is_file():
        raise ValueError("gateway secret must be a regular, non-symlink file")
    metadata = selected.stat()
    if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError("gateway secret must be owned by this user with mode 0600")
    if not 32 <= metadata.st_size <= 1024:
        raise ValueError("gateway secret must contain 32..1024 bytes")
    secret = selected.read_bytes().strip()
    if len(secret) < 32:
        raise ValueError("gateway secret is too short")
    return secret


def parse_wire_json(raw: str) -> dict[str, object]:
    if len(raw.encode("utf-8")) > MAX_WIRE_BYTES:
        raise ValueError("gateway message exceeds maximum length")

    def unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate gateway message field")
            result[key] = value
        return result

    def invalid_constant(_value: str) -> None:
        raise ValueError("non-finite gateway JSON number")

    result = json.loads(raw, object_pairs_hook=unique_pairs, parse_constant=invalid_constant)
    if not isinstance(result, dict):
        raise ValueError("gateway message must be an object")
    return result
