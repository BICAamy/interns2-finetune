"""Exact V6 group-write frames and strict reply parsing."""

from __future__ import annotations

import pytest

from edge_gateway.huayan.models import ProtocolError
from edge_gateway.huayan.motion_codec import decode_write_reply, encode_group_enabled


def test_group_enable_disable_frames_are_exact() -> None:
    assert encode_group_enabled(True) == b"GrpEnable,0,;"
    assert encode_group_enabled(False) == b"GrpDisable,0,;"
    with pytest.raises(TypeError):
        encode_group_enabled(1)  # type: ignore[arg-type]


@pytest.mark.parametrize("command", ["GrpEnable", "GrpDisable"])
def test_group_write_reply_accepts_only_matching_ok_or_documented_fail(command: str) -> None:
    assert decode_write_reply(f"{command},OK,;".encode(), command=command) is True
    assert decode_write_reply(
        f"{command},Fail,20006,invalid parameters,;".encode(), command=command,
    ) is False
    with pytest.raises(ProtocolError, match="unexpected"):
        decode_write_reply(b"GrpStop,OK,;", command=command)
    with pytest.raises(ProtocolError, match="unexpected"):
        decode_write_reply(f"{command},OK,extra,;".encode(), command=command)


def test_group_write_reply_rejects_bad_framing_and_unknown_parser_mode() -> None:
    with pytest.raises(ProtocolError, match="framing"):
        decode_write_reply(b"GrpEnable,OK", command="GrpEnable")
    with pytest.raises(ValueError, match="unsupported"):
        decode_write_reply(b"Anything,OK,;", command="Anything")
