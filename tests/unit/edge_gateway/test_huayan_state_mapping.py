from __future__ import annotations

import pytest

from edge_gateway.huayan.adapter import (
    read_actual_position,
    read_current_fsm,
    read_emergency_info,
    read_fast_port,
    read_is_simulation,
    read_controller_started,
    read_robot_state,
    read_waypoint_id,
)
from edge_gateway.huayan.command_codec import decode_reply
from edge_gateway.huayan.models import ProtocolError, ReadCommand
from tests.fakes.huayan_controller import DEFAULT_REPLIES


def test_documented_robot_state_and_emergency_fields_are_mapped() -> None:
    state = read_robot_state(decode_reply(
        DEFAULT_REPLIES[ReadCommand.ROBOT_STATE], expected=ReadCommand.ROBOT_STATE
    ))
    assert not state.moving
    assert state.enabled
    assert state.electrified
    assert state.controller_box_connected
    assert state.in_position
    emergency = read_emergency_info(decode_reply(
        DEFAULT_REPLIES[ReadCommand.EMERGENCY_INFO], expected=ReadCommand.EMERGENCY_INFO
    ))
    assert not emergency.emergency_stop
    assert not emergency.emergency_circuit_fault


def test_actual_position_requires_24_finite_values() -> None:
    reply = decode_reply(DEFAULT_REPLIES[ReadCommand.ACTUAL_POSITION], expected=ReadCommand.ACTUAL_POSITION)
    position = read_actual_position(reply)
    assert len(position.joints_deg) == 6
    assert position.joints_deg[2] == 81.099
    assert position.current_pose[0] == 367.945
    bad = decode_reply(
        DEFAULT_REPLIES[ReadCommand.ACTUAL_POSITION].replace(b"81.099", b"NaN", 1),
        expected=ReadCommand.ACTUAL_POSITION,
    )
    with pytest.raises(ProtocolError):
        read_actual_position(bad)


def test_fsm_and_fast_port_are_typed() -> None:
    assert read_current_fsm(decode_reply(b"ReadCurFSM,OK,33,;", expected=ReadCommand.CURRENT_FSM)) == 33
    assert read_fast_port(decode_reply(
        b"ReadFastCmdPort,OK,10001,;", expected=ReadCommand.FAST_COMMAND_PORT
    )) == 10001
    with pytest.raises(ProtocolError):
        read_fast_port(decode_reply(
            b"ReadFastCmdPort,OK,70000,;", expected=ReadCommand.FAST_COMMAND_PORT
        ))
    assert not read_is_simulation(decode_reply(
        b"IsSimulation,OK,0,;", expected=ReadCommand.IS_SIMULATION
    ))
    assert read_controller_started(decode_reply(
        b"ReadControllerState,OK,1,;", expected=ReadCommand.CONTROLLER_STATE
    ))
    assert read_waypoint_id(decode_reply(
        b"ReadCurWayPointID,OK,FAKE_ONLY,;", expected=ReadCommand.CURRENT_WAYPOINT_ID
    )) == "FAKE_ONLY"
