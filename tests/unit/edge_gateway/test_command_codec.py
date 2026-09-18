from __future__ import annotations

import pytest

from edge_gateway.huayan.command_codec import (
    CommandFrameDecoder,
    decode_reply,
    encode_read,
    validate_identifier,
)
from edge_gateway.huayan.models import ProtocolError, ReadCommand


def test_documented_read_commands_are_exact_and_allowlisted() -> None:
    assert encode_read(ReadCommand.ROBOT_STATE) == b"ReadRobotState,0,;"
    assert encode_read(ReadCommand.PACKAGE_VERSION) == b"PackageVersion,;"
    assert encode_read(ReadCommand.ROBOT_STATE, robot_id=5) == b"ReadRobotState,5,;"
    with pytest.raises(TypeError):
        encode_read("WayPoint,0,;")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        encode_read(ReadCommand.ROBOT_STATE, robot_id=6)
    with pytest.raises(ValueError):
        encode_read(ReadCommand.PACKAGE_VERSION, robot_id=1)


@pytest.mark.parametrize("value", ["a,b", "a;b", "a\n", "a\x00", "中文字", "x" * 65, ""])
def test_unsafe_future_ids_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        validate_identifier(value)


def test_half_and_sticky_packets_keep_exact_frame_boundaries() -> None:
    decoder = CommandFrameDecoder()
    assert decoder.feed(b"ReadCurFSM,OK,") == []
    frames = decoder.feed(b"33,;ReadRobotModel,OK,E05,;")
    assert frames == [b"ReadCurFSM,OK,33,;", b"ReadRobotModel,OK,E05,;"]
    assert not decoder.pending
    assert decode_reply(frames[0], expected=ReadCommand.CURRENT_FSM).values == ("33",)


def test_failure_preserves_vendor_code_and_comma_in_explanation() -> None:
    response = decode_reply(
        b"ReadCurFSM,Fail,20018,forbidden, while moving,;",
        expected=ReadCommand.CURRENT_FSM,
    )
    assert response.vendor_error_code == 20018
    assert response.vendor_error_message == "forbidden, while moving"
    assert not response.protocol_deviation
    noncanonical = decode_reply(
        b"ReadCurFSM,Fail,20018,forbidden;", expected=ReadCommand.CURRENT_FSM
    )
    assert noncanonical.protocol_deviation


@pytest.mark.parametrize("frame", [
    b"Other,OK,33,;",
    b"ReadCurFSM,Maybe,33,;",
    b"ReadCurFSM,OK,33,extra,;",
    b"ReadCurFSM,OK,33;",
    b"ReadCurFSM,Fail,0,no error,;",
    b"ReadCurFSM,OK,\xff,;",
    b"ReadCurFSM,OK,\n33,;",
])
def test_invalid_replies_fail_closed(frame: bytes) -> None:
    with pytest.raises(ProtocolError):
        decode_reply(frame, expected=ReadCommand.CURRENT_FSM)


def test_unterminated_and_complete_oversized_replies_are_rejected() -> None:
    decoder = CommandFrameDecoder(max_reply_bytes=32)
    with pytest.raises(ProtocolError):
        decoder.feed(b"X" * 33)
    with pytest.raises(ProtocolError):
        CommandFrameDecoder(max_reply_bytes=32).feed(b"X" * 33 + b";")
