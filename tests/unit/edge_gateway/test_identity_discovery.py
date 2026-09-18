from __future__ import annotations

import sys

import pytest

from edge_gateway.huayan.identity_discovery import (
    discover_datasheet_identity, discover_identity, inspect_datasheet_header, main,
)
from tests.fakes.huayan_controller import FakeHuayanController


def test_minimal_identity_discovery_sends_only_four_read_requests() -> None:
    with FakeHuayanController() as fake:
        result = discover_identity("127.0.0.1", fake.command_port)
        assert result.package_version == "6.3.6.20240305"
        assert result.robot_model == "E05-Pro"
        assert result.is_simulation is False
        assert result.controller_started is True
        assert fake.received_commands == [
            b"PackageVersion,;",
            b"ReadRobotModel,;",
            b"IsSimulation,;",
            b"ReadControllerState,;",
        ]


def test_datasheet_header_and_sn_can_be_read_without_prefilled_config() -> None:
    with FakeHuayanController() as fake:
        header = inspect_datasheet_header("127.0.0.1", fake.datasheet_port)
        assert header["header_hex"].startswith("4c544252")
        assert header["candidates"]["little"]["lengths_consistent"] is True
        assert header["candidates"]["big"]["lengths_consistent"] is False
        identity = discover_datasheet_identity(
            "127.0.0.1", fake.datasheet_port, byte_order="little",
        )
        assert identity.device_sn == "FAKE-E05-001"
        assert identity.joint_positions_deg[2] == 81.099
        assert fake.received_commands == []


def test_discovery_cli_dry_run_and_missing_operator_gate_open_no_socket(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    def forbidden_socket(*_args, **_kwargs):
        raise AssertionError("discovery must not connect without operator confirmation")

    monkeypatch.setattr("socket.create_connection", forbidden_socket)
    monkeypatch.setattr(sys, "argv", [
        "discover", "--host", "192.168.0.10", "--show-requests",
    ])
    assert main() == 0
    assert capsys.readouterr().out.splitlines() == [
        "PackageVersion,;", "ReadRobotModel,;", "IsSimulation,;",
        "ReadControllerState,;", "No network connection was opened",
    ]
    monkeypatch.setattr(sys, "argv", [
        "discover", "--host", "192.168.0.10", "--discover-real-identity",
    ])
    with pytest.raises(SystemExit, match="2"):
        main()
    with pytest.raises(ValueError, match="10003"):
        discover_identity("192.168.0.10", 10004, scope="private-read-only")
