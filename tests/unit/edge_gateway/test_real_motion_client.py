"""The private-host writer is single-use, identified, and never implicit."""

from __future__ import annotations

import socket

import pytest

from edge_gateway import commissioning_cli
from edge_gateway.huayan.models import ResponseUnknown
from edge_gateway.huayan.motion_codec import LinearWaypoint
from edge_gateway.huayan.real_motion_client import LocalRealMotionClient
from tests.fakes.huayan_controller import CommandAction, FakeHuayanController
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
