from __future__ import annotations

import socket

import pytest

from edge_gateway.huayan.datasheet_monitor import SourceStampStats, main, monitor_datasheet
from tests.fakes.huayan_controller import FakeHuayanController


def test_mac_only_monitor_receives_repeated_frames_without_commands() -> None:
    reports: list[dict[str, object]] = []
    with FakeHuayanController(stamp_every_n_frames=3) as fake:
        final = monitor_datasheet(
            "127.0.0.1", fake.datasheet_port, "FAKE-E05-001",
            byte_order="little", duration_s=0.35, report_every_s=0.15,
            scope="loopback", emit=reports.append,
        )
        assert fake.received_commands == []
    assert final["status"] == "complete"
    assert final["frames"] >= 2
    assert "window_rate_hz" in final
    assert "source_stamp_advances_over_100ms" in final
    assert "receive_intervals_over_100ms" in final
    assert "max_receive_interval_ms" in final
    assert final["source_timestamp_repeats"] >= 1
    assert final["joint_positions_deg"][2] == 81.099
    assert final["fsm_code"] == 33
    assert final["error_code"] == 0
    assert any(report["status"] == "running" for report in reports)


def test_monitor_fails_on_wrong_device_without_sending_commands() -> None:
    with FakeHuayanController() as fake:
        with pytest.raises(ValueError, match="DeviceSN"):
            monitor_datasheet(
                "127.0.0.1", fake.datasheet_port, "OTHER-ROBOT",
                byte_order="little", duration_s=0.2, scope="loopback",
            )
        assert fake.received_commands == []


def test_repeated_source_stamp_is_reported_but_backwards_stamp_fails() -> None:
    stats = SourceStampStats()
    stats.observe(1000, 1_000_000_000)
    stats.observe(1000, 1_050_000_000)
    assert stats.repeats == 1
    assert stats.max_hold_ms == 50
    stats.observe(1101, 1_100_000_000)
    assert stats.advances_over_100ms == 1
    with pytest.raises(ValueError, match="previous=1101, current=1100, delta_ms=-1"):
        stats.observe(1100, 1_150_000_000)


def test_real_monitor_requires_port_10004_and_operator_flags_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_socket(*_args, **_kwargs):
        raise AssertionError("monitor must not connect")

    monkeypatch.setattr(socket, "create_connection", forbidden_socket)
    with pytest.raises(ValueError, match="10004"):
        monitor_datasheet(
            "192.168.0.10", 10003, "EXPECTED-SN",
            byte_order="little", duration_s=1,
        )
    with pytest.raises(SystemExit, match="2"):
        main([
            "--real-config", "configs/robot-real.local.yaml",
            "--duration-s", "1", "--byte-order", "little",
        ])
