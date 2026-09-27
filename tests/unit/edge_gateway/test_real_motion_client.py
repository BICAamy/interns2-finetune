"""The private-host writer is single-use, identified, and never implicit."""

from __future__ import annotations

import socket

import pytest

from edge_gateway import commissioning_cli
from edge_gateway.huayan.adapter import read_robot_state
from edge_gateway.huayan.models import ProtocolError, ReadCommand, ResponseUnknown
from edge_gateway.huayan.motion_codec import LinearWaypoint
from edge_gateway.huayan.real_motion_client import LocalRealMotionClient
from tests.fakes.huayan_controller import (
    CommandAction, FakeHuayanController, datasheet_document, datasheet_frame,
)
from tests.unit.edge_gateway.test_commissioning_cli import config as sample_config


def real_shaped_config():
    config = sample_config()
    return config.model_copy(update={
        "controller": config.controller.model_copy(update={
            "model": "E05-Pro", "package_versions": ["6.3.6.20240305"],
        }),
    })


def waypoint() -> LinearWaypoint:
    return LinearWaypoint(
        pose_xyzrpy=(101, 100, 100, 0, 0, 0), tcp_name="TCP", ucs_name="Base",
        speed_mm_s=2, acceleration_mm_s2=10, waypoint_id="LOCAL_1",
        reference_joints_deg=(0, 0, 90, 0, 90, 0),
    )


def redirect_controller(monkeypatch, fake: FakeHuayanController) -> None:
    original = socket.create_connection

    def connect(address, timeout=None):
        assert address == ("192.168.0.10", 10003)
        return original(("127.0.0.1", fake.command_port), timeout)

    monkeypatch.setattr(socket, "create_connection", connect)
    monkeypatch.setattr(commissioning_cli, "require_local_mac_terminal", lambda: None)


def test_real_writer_rejects_loopback_and_does_not_connect_on_construction():
    config = real_shaped_config()
    with pytest.raises(ValueError, match="private"):
        LocalRealMotionClient(config.model_copy(update={
            "controller": config.controller.model_copy(update={"host": "127.0.0.1"}),
        }), timeout_s=0.1)
    client = LocalRealMotionClient(config, timeout_s=0.1)
    assert client._socket is None
    assert LocalRealMotionClient(config, timeout_s=3.0).timeout_s == 3.0
    with pytest.raises(ValueError, match="response_ms"):
        LocalRealMotionClient(config, timeout_s=3.001)


def test_real_writer_requires_mac_terminal_before_opening_socket(monkeypatch):
    def refuse():
        raise PermissionError("not local")

    monkeypatch.setattr(commissioning_cli, "require_local_mac_terminal", refuse)
    monkeypatch.setattr(socket, "create_connection", lambda *_a, **_kw: pytest.fail("socket opened"))
    with pytest.raises(PermissionError, match="not local"):
        LocalRealMotionClient(real_shaped_config(), timeout_s=0.1).connect()


def test_real_writer_is_single_use_and_stop_requires_owned_attempt(monkeypatch):
    with FakeHuayanController(accept_fake_motion=True) as fake:
        redirect_controller(monkeypatch, fake)
        with LocalRealMotionClient(real_shaped_config(), timeout_s=0.1) as client:
            with pytest.raises(PermissionError):
                client.software_stop()
            assert client.waypoint(waypoint()) is True
            assert client.current_waypoint_id() == "LOCAL_1"
            assert client.software_stop() is True
            with pytest.raises(RuntimeError, match="single-use"):
                client.waypoint(waypoint())
        frames = [frame for frame in fake.received_commands if frame.startswith(b"WayPoint,")]
        assert len(frames) == 1
        assert b",0,0,90,0,90,0,TCP,Base,2,10,0,1," in frames[0]


def test_real_writer_never_retries_unknown_waypoint(monkeypatch):
    with FakeHuayanController(
        accept_fake_motion=True,
        motion_actions={"WayPoint": [CommandAction(None)]},
    ) as fake:
        redirect_controller(monkeypatch, fake)
        with LocalRealMotionClient(real_shaped_config(), timeout_s=0.1) as client:
            with pytest.raises(ResponseUnknown):
                client.waypoint(waypoint())
            with pytest.raises(RuntimeError, match="single-use"):
                client.waypoint(waypoint())
            with pytest.raises(RuntimeError, match="disconnected"):
                client.software_stop()
        assert len([frame for frame in fake.received_commands if frame.startswith(b"WayPoint,")]) == 1


def test_real_writer_rejects_unapproved_limits_before_write(monkeypatch):
    with FakeHuayanController(accept_fake_motion=True) as fake:
        redirect_controller(monkeypatch, fake)
        with LocalRealMotionClient(real_shaped_config(), timeout_s=0.1) as client:
            unsafe = LinearWaypoint(
                pose_xyzrpy=(101, 100, 100, 0, 0, 0), tcp_name="TCP", ucs_name="Base",
                speed_mm_s=100, acceleration_mm_s2=10, waypoint_id="LOCAL_1",
                reference_joints_deg=(0, 0, 90, 0, 90, 0),
            )
            with pytest.raises(ValueError, match="speed"):
                client.waypoint(unsafe)
        assert not any(frame.startswith((b"WayPoint,", b"GrpStop,")) for frame in fake.received_commands)


@pytest.mark.parametrize("target,frame", [
    (True, b"GrpEnable,0,;"),
    (False, b"GrpDisable,0,;"),
])
def test_real_writer_sends_one_exact_group_state_command(monkeypatch, target, frame):
    with FakeHuayanController(
        accept_fake_motion=True, initial_enabled=not target,
    ) as fake:
        redirect_controller(monkeypatch, fake)
        with LocalRealMotionClient(real_shaped_config(), timeout_s=0.1) as client:
            assert client.set_enabled(
                target, disable_stationary_confirmed=not target,
            ) is True
            assert read_robot_state(client.request(ReadCommand.ROBOT_STATE)).enabled is target
            with pytest.raises(RuntimeError, match="single-use"):
                client.set_enabled(target)
            with pytest.raises(RuntimeError, match="single-use"):
                client.waypoint(waypoint())
            with pytest.raises(PermissionError, match="own attempted WayPoint"):
                client.software_stop()
        assert fake.received_commands.count(frame) == 1


def test_real_writer_never_retries_unknown_group_state_write(monkeypatch):
    with FakeHuayanController(
        accept_fake_motion=True,
        initial_enabled=False,
        motion_actions={"GrpEnable": [CommandAction(None)]},
    ) as fake:
        redirect_controller(monkeypatch, fake)
        with LocalRealMotionClient(real_shaped_config(), timeout_s=0.1) as client:
            with pytest.raises(ResponseUnknown, match="GrpEnable outcome unknown"):
                client.set_enabled(True)
            with pytest.raises(RuntimeError, match="single-use"):
                client.set_enabled(True)
        assert fake.received_commands.count(b"GrpEnable,0,;") == 1


def test_real_writer_refuses_disable_without_stationary_confirmation(monkeypatch):
    with FakeHuayanController(accept_fake_motion=True) as fake:
        redirect_controller(monkeypatch, fake)
        with LocalRealMotionClient(real_shaped_config(), timeout_s=0.1) as client:
            with pytest.raises(PermissionError, match="stationary confirmation"):
                client.set_enabled(False)
        assert b"GrpDisable,0,;" not in fake.received_commands


def test_real_writer_rejects_datasheet_stream_on_command_socket(monkeypatch):
    with FakeHuayanController(
        accept_fake_motion=True,
        command_actions={ReadCommand.ROBOT_STATE: [CommandAction((
            datasheet_frame(datasheet_document()),
        ))]},
    ) as fake:
        redirect_controller(monkeypatch, fake)
        with LocalRealMotionClient(real_shaped_config(), timeout_s=0.1) as client:
            with pytest.raises(ProtocolError, match="DataSheet LTBR.*10003"):
                client.request(ReadCommand.ROBOT_STATE)
