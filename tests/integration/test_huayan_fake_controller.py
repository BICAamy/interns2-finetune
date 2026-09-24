from __future__ import annotations

import socket
import struct

import pytest

from edge_gateway.huayan.adapter import (
    read_current_fsm, read_identity_text, read_robot_state, read_waypoint_id,
)
from edge_gateway.huayan.command_client import CommandClient
from edge_gateway.huayan.datasheet_client import DatasheetClient
from edge_gateway.huayan.error_policy import vendor_fault
from edge_gateway.huayan.models import ProtocolError, ReadCommand, ResponseUnknown
from tests.fakes.huayan_controller import (
    CommandAction,
    FakeHuayanController,
    datasheet_document,
    datasheet_frame,
)


def test_fake_supports_ordinary_and_discovered_fast_read_port() -> None:
    with FakeHuayanController() as fake:
        with CommandClient("127.0.0.1", fake.command_port) as ordinary:
            assert ordinary.discover_fast_port() == fake.fast_port
            assert read_identity_text(ordinary.request(ReadCommand.ROBOT_MODEL)) == "E05-Pro"
            assert read_robot_state(ordinary.request(ReadCommand.ROBOT_STATE)).in_position
            with CommandClient("127.0.0.1", fake.fast_port, fast_port=True) as fast:
                assert read_current_fsm(fast.request(ReadCommand.CURRENT_FSM)) == 33
                with pytest.raises(ValueError, match="not documented"):
                    fast.request(ReadCommand.EMERGENCY_INFO)
        assert fake.received_commands == [
            b"ReadFastCmdPort,;", b"ReadRobotModel,;", b"ReadRobotState,0,;", b"ReadCurFSM,0,;"
        ]


def test_fake_fragments_response_and_drops_lost_response_without_retry() -> None:
    with FakeHuayanController(command_actions={
        ReadCommand.CURRENT_FSM: [
            CommandAction((b"ReadCur", b"FSM,OK,33,;")),
            CommandAction(None),
        ],
    }) as fake:
        with CommandClient("127.0.0.1", fake.command_port) as client:
            assert read_current_fsm(client.request(ReadCommand.CURRENT_FSM)) == 33
            with pytest.raises(ResponseUnknown, match="do not retry"):
                client.request(ReadCommand.CURRENT_FSM)
            with pytest.raises(RuntimeError, match="not connected"):
                client.request(ReadCommand.CURRENT_FSM)
        assert fake.received_commands == [b"ReadCurFSM,0,;", b"ReadCurFSM,0,;"]


@pytest.mark.parametrize("bad_reply", [
    b"ReadRobotModel,OK,E05,;ReadRobotModel,OK,E05,;",
    b"PackageVersion,OK,6.0,;",
    b"ReadRobotModel,OK,\xff,;",
    b"ReadRobotModel,OK," + b"X" * 5000 + b",;",
])
def test_bad_or_unsolicited_reply_closes_command_socket(bad_reply: bytes) -> None:
    with FakeHuayanController(command_actions={
        ReadCommand.ROBOT_MODEL: [CommandAction((bad_reply,))],
    }) as fake:
        with CommandClient("127.0.0.1", fake.command_port) as client:
            with pytest.raises(ProtocolError):
                client.request(ReadCommand.ROBOT_MODEL)
            with pytest.raises(RuntimeError, match="not connected"):
                client.request(ReadCommand.ROBOT_MODEL)


def test_fake_rejects_motion_bytes_and_step4_client_rejects_real_host() -> None:
    with pytest.raises(ValueError, match="cannot connect to a real controller"):
        CommandClient("192.168.0.10", 10003)
    with pytest.raises(ValueError, match="cannot connect to a real controller"):
        DatasheetClient("192.168.0.10", 10004, byte_order="little")
    with FakeHuayanController() as fake:
        with socket.create_connection(("127.0.0.1", fake.command_port), timeout=1) as client:
            client.sendall(b"WayPoint,0,;")
            assert b"Fail,20005" in client.recv(1024)


def test_fake_rejects_wrong_argument_count_and_range() -> None:
    with FakeHuayanController() as fake:
        with socket.create_connection(("127.0.0.1", fake.command_port), timeout=1) as client:
            client.sendall(b"ReadCurFSM,999,;")
            assert b"ReadCurFSM,Fail,20006" in client.recv(1024)
            client.sendall(b"ReadRobotModel,0,;")
            assert b"ReadRobotModel,Fail,20006" in client.recv(1024)
        assert fake.received_commands == [b"ReadCurFSM,999,;", b"ReadRobotModel,0,;"]


def test_fake_can_return_unknown_vendor_error_without_guessing_recovery() -> None:
    with FakeHuayanController(command_actions={
        ReadCommand.CURRENT_FSM: [CommandAction((b"ReadCurFSM,Fail,99999,new code,;",))],
    }) as fake:
        with CommandClient("127.0.0.1", fake.command_port) as client:
            reply = client.request(ReadCommand.CURRENT_FSM)
            fault = vendor_fault(reply)
            assert fault.vendor_error_code == 99999
            assert fault.stable_error_code is None


def test_fake_default_datasheet_ticks_at_roughly_20_hz() -> None:
    with FakeHuayanController() as fake:
        with DatasheetClient("127.0.0.1", fake.datasheet_port, byte_order="little") as client:
            first = None
            while first is None:
                first = client.poll()
            second = None
            while second is None:
                second = client.poll()
            assert first is not None and second is not None
            assert 20 <= second.source_timestamp_ms - first.source_timestamp_ms <= 300


def test_datasheet_stream_keeps_latest_pose_and_all_status_transitions() -> None:
    def packet(fsm: int, moving: int, error: int = 0) -> bytes:
        data = datasheet_document()
        state = data["StateAndError"]
        state["robotState"] = fsm
        state["robotMoving"] = moving
        state["Error_Code"] = error
        return datasheet_frame(data)

    stream = packet(33, 0) + packet(25, 1) + packet(25, 1) + packet(27, 1) + packet(33, 0)
    with FakeHuayanController(data_actions=[stream]) as fake:
        with DatasheetClient("127.0.0.1", fake.datasheet_port, byte_order="little") as client:
            while client.latest is None or client.latest.fsm_code != 33 or not client.latest.received_wall_ms:
                client.poll()
            # A single TCP read may be split. Consume until the fake closes if
            # necessary, while keeping every status transition in the alert queue.
            while client.pending_events < 4:
                client.poll()
            assert client.latest is not None
            assert client.latest.fsm_code == 33
            assert [event.fsm_code for event in client.drain_events()] == [33, 25, 27, 33]


def test_datasheet_bad_frame_and_stalled_stream_fail_closed() -> None:
    valid = datasheet_frame(datasheet_document())
    bad_length = valid[:8] + struct.pack("<I", 1) + valid[12:]
    with FakeHuayanController(data_actions=[bad_length]) as fake:
        with DatasheetClient("127.0.0.1", fake.datasheet_port, byte_order="little") as client:
            with pytest.raises(ProtocolError):
                client.poll()
    bad_json = b"{bad json"
    bad_json_frame = b"LTBR" + struct.pack("<II", 12 + len(bad_json), len(bad_json)) + bad_json
    with FakeHuayanController(data_actions=[bad_json_frame]) as fake:
        with DatasheetClient("127.0.0.1", fake.datasheet_port, byte_order="little") as client:
            with pytest.raises(ProtocolError):
                client.poll()
    with FakeHuayanController(data_actions=[valid, 0.3]) as fake:
        with DatasheetClient(
            "127.0.0.1", fake.datasheet_port, byte_order="little", timeout_s=0.05
        ) as client:
            assert client.poll() is not None
            with pytest.raises(socket.timeout):
                client.poll()


def test_data_event_queue_never_silently_drops_faults() -> None:
    data = datasheet_document()
    data["StateAndError"]["Error_Code"] = 20018
    packet = datasheet_frame(data)
    with FakeHuayanController(data_actions=[packet * 3]) as fake:
        with DatasheetClient(
            "127.0.0.1", fake.datasheet_port, byte_order="little", max_events=2
        ) as client:
            with pytest.raises(ProtocolError, match="queue full"):
                client.poll()


@pytest.mark.parametrize("scenario,expected", [
    ("delayed_start", [33, 25, 33]),
    ("never_start", [33, 33, 33]),
    ("never_arrive", [25, 25, 25]),
    ("contradictory_state", [33]),
])
def test_fake_reproduces_motion_feedback_scenarios(scenario: str, expected: list[int]) -> None:
    with FakeHuayanController.scenario(scenario) as fake:  # type: ignore[arg-type]
        with DatasheetClient(
            "127.0.0.1", fake.datasheet_port, byte_order="little", timeout_s=0.2
        ) as client:
            while client.received_samples < len(expected):
                client.poll()
            assert client.latest is not None
            assert client.latest.fsm_code == expected[-1]
            if scenario == "delayed_start":
                assert [event.fsm_code for event in client.drain_events()] == expected
                assert client.latest.brake_states == (0, 0, 0, 0, 0, 0)
            if scenario == "never_arrive":
                assert client.latest.brake_states == (1, 1, 1, 1, 1, 1)
            if scenario == "contradictory_state":
                assert client.latest.moving and client.latest.fsm_code == 33


def test_fake_reports_external_waypoint_id_without_claiming_ownership() -> None:
    with FakeHuayanController.scenario("external_waypoint") as fake:
        with CommandClient("127.0.0.1", fake.command_port) as client:
            reported = read_waypoint_id(client.request(ReadCommand.CURRENT_WAYPOINT_ID))
            assert reported == "EXTERNAL_WRITER"
