from __future__ import annotations

import pytest

from edge_gateway.state_machine import EdgeMode, EdgeState
from edge_gateway.huayan.datasheet_codec import DatasheetFrameDecoder
from tests.fakes.huayan_controller import datasheet_document, datasheet_frame


def sample(*, fsm: int = 33, error: int = 0):
    document = datasheet_document()
    document["StateAndError"]["robotState"] = fsm
    document["StateAndError"]["Error_Code"] = error
    return DatasheetFrameDecoder(byte_order="little").feed(datasheet_frame(document))[0]


def test_edge_is_never_armed_and_reconnect_requires_new_session() -> None:
    state = EdgeState()
    assert state.mode == EdgeMode.DISCONNECTED
    assert not state.motion_enabled
    state.command_connected = True
    state.observe(sample())
    state.start_cloud_session("a" * 32)
    assert state.mode == EdgeMode.OBSERVE_ONLY
    state.cloud_lost()
    assert state.session_id is None
    assert state.mode == EdgeMode.DISCONNECTED
    state.start_cloud_session("b" * 32)
    assert state.mode == EdgeMode.OBSERVE_ONLY
    assert not state.motion_enabled


def test_pose_slot_is_latest_wins_but_status_and_errors_remain_bounded() -> None:
    state = EdgeState(max_events=2)
    state.observe(sample())
    state.observe(sample())
    assert state.snapshot()[0].sequence == 2
    assert [record.sequence for record in state.snapshot()[1]] == [1]
    state.observe(sample(fsm=25))
    assert [record.sequence for record in state.snapshot()[1]] == [1, 3]
    with pytest.raises(RuntimeError, match="queue full"):
        state.observe(sample(error=20018))
    assert state.mode == EdgeMode.FAULT
    state.acknowledged_through(1)
    assert [record.sequence for record in state.snapshot()[1]] == [3]
