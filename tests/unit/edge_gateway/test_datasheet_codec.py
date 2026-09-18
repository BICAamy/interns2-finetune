from __future__ import annotations

import json
import struct

import pytest

from edge_gateway.huayan.datasheet_codec import DatasheetFrameDecoder, parse_datasheet
from edge_gateway.huayan.models import ProtocolError
from tests.fakes.huayan_controller import datasheet_document, datasheet_frame


@pytest.mark.parametrize("byte_order", ["little", "big"])
def test_documented_datasheet_sample_parses_only_with_explicit_byte_order(byte_order: str) -> None:
    frame = datasheet_frame(datasheet_document(), byte_order=byte_order)
    parser = DatasheetFrameDecoder(byte_order=byte_order)
    assert parser.feed(frame[:1]) == []
    assert parser.feed(frame[1:9]) == []
    assert parser.feed(frame[9:-4]) == []
    (sample,) = parser.feed(frame[-4:])
    assert len(sample.joint_positions_deg) == 6
    assert sample.joint_positions_deg[2] == 81.099
    assert sample.base_pose[0] == 367.945
    assert sample.device_sn == "FAKE-E05-001"
    assert sample.fsm_code == 33
    assert sample.received_wall_ms > 0
    assert sample.received_monotonic_ns > 0


def test_sticky_packets_and_bounded_magic_resynchronization() -> None:
    frame = datasheet_frame(datasheet_document())
    parser = DatasheetFrameDecoder(byte_order="little")
    samples = parser.feed(b"noise" + frame + frame)
    assert len(samples) == 2
    with pytest.raises(ProtocolError, match="resync"):
        DatasheetFrameDecoder(byte_order="little", max_resync_bytes=2).feed(b"noiseX")


def test_bad_lengths_endianness_and_max_size_fail_closed() -> None:
    frame = datasheet_frame(datasheet_document())
    with pytest.raises(ProtocolError):
        DatasheetFrameDecoder(byte_order="big").feed(frame)
    with pytest.raises(ProtocolError, match="lengths disagree"):
        DatasheetFrameDecoder(byte_order="little").feed(
            frame[:8] + struct.pack("<I", 3) + frame[12:]
        )
    with pytest.raises(ProtocolError, match="out of bounds"):
        DatasheetFrameDecoder(byte_order="little").feed(
            b"LTBR" + struct.pack("<II", 1024 * 1024 + 1, 1024 * 1024 - 11)
        )
    with pytest.raises(ValueError):
        DatasheetFrameDecoder(byte_order="auto")


@pytest.mark.parametrize("change", [
    lambda d: d["PosAndVel"].update(Actual_Position=["0"] * 11),
    lambda d: d["PosAndVel"].update(Actual_Joint_Velocity=["0"] * 5),
    lambda d: d["PosAndVel"].update(Actual_PCS_Base=["0"] * 5),
    lambda d: d["PosAndVel"].update(Actual_Override="NaN"),
    lambda d: d["StateAndError"].update(robotMoving=2),
    lambda d: d["StateAndError"].update(BrakeState=[0] * 5),
    lambda d: d["StateAndError"].update(Error_AxisID=7),
    lambda d: d["MsgTitle"].update(Stamp="not-a-time"),
])
def test_bad_schema_and_nonfinite_numbers_fail_closed(change) -> None:
    document = datasheet_document()
    change(document)
    with pytest.raises(ProtocolError):
        DatasheetFrameDecoder(byte_order="little").feed(datasheet_frame(document))


def test_bad_json_duplicate_keys_and_invalid_utf8_fail_closed() -> None:
    def parse(payload: bytes) -> None:
        parse_datasheet(payload, received_wall_ms=1, received_monotonic_ns=1)

    with pytest.raises(ProtocolError):
        parse(b"{bad json")
    with pytest.raises(ProtocolError):
        parse(b'{"a":1,"a":2}')
    with pytest.raises(ProtocolError):
        parse(b"\xff")
    with pytest.raises(ProtocolError):
        parse(json.dumps({"PosAndVel": {"Actual_Position": [float("nan")]}}).encode())
