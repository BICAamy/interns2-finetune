"""Bounded Mac-only observation of a real controller's 10004 DataSheet stream.

This tool opens one receive-only socket. It has no command socket, server
transport, or configuration writer.
"""

from __future__ import annotations

import argparse
import json
import math
import resource
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from robot_runtime.real_config import load_real_config

from .datasheet_client import DatasheetClient
from .real_probe import validate_probe_config


def _peak_rss_mib() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(peak / (1024 * 1024 if sys.platform == "darwin" else 1024), 1)


@dataclass
class SourceStampStats:
    """Count repeated stamps without mistaking one repeat for a stopped stream."""

    previous_ms: int | None = None
    repeats: int = 0
    advances_over_100ms: int = 0
    last_advance_monotonic_ns: int | None = None
    max_hold_ms: float = 0.0

    def observe(self, stamp_ms: int, received_monotonic_ns: int) -> None:
        if self.previous_ms is not None:
            delta_ms = stamp_ms - self.previous_ms
            if delta_ms < 0:
                raise ValueError(
                    "DataSheet source timestamp moved backwards: "
                    f"previous={self.previous_ms}, current={stamp_ms}, delta_ms={delta_ms}"
                )
            if delta_ms == 0:
                self.repeats += 1
            else:
                if delta_ms > 100:
                    self.advances_over_100ms += 1
                self.last_advance_monotonic_ns = received_monotonic_ns
        else:
            self.last_advance_monotonic_ns = received_monotonic_ns
        self.previous_ms = stamp_ms
        if self.last_advance_monotonic_ns is not None:
            hold_ms = max(0, received_monotonic_ns - self.last_advance_monotonic_ns) / 1_000_000
            self.max_hold_ms = max(self.max_hold_ms, hold_ms)


def monitor_datasheet(
    host: str,
    port: int,
    expected_device_sn: str,
    *,
    byte_order: Literal["little", "big"],
    duration_s: float,
    report_every_s: float = 10.0,
    scope: Literal["loopback", "private-read-only"] = "private-read-only",
    emit: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    """Read parsed frames until a finite deadline, failing on identity/data loss."""
    if scope == "private-read-only" and port != 10004:
        raise ValueError("real DataSheet monitoring is limited to port 10004")
    if not expected_device_sn:
        raise ValueError("expected DeviceSN is required")
    if not math.isfinite(duration_s) or not 0 < duration_s <= 1800:
        raise ValueError("duration_s must be within (0, 1800]")
    if not math.isfinite(report_every_s) or not 0 < report_every_s <= 60:
        raise ValueError("report_every_s must be within (0, 60]")
    output = emit or (lambda report: print(json.dumps(report, ensure_ascii=False, indent=2)))
    started = time.monotonic()
    report_started = started
    next_report = started + report_every_s
    deadline = started + duration_s
    frames = 0
    window_frames = 0
    stamps = SourceStampStats()
    receive_intervals_over_100ms = 0
    max_receive_interval_ms = 0.0
    previous_receive_ns: int | None = None
    latest = None

    def report(kind: str, now: float) -> dict[str, object]:
        nonlocal report_started, next_report, window_frames
        interval = max(now - report_started, 1e-9)
        result: dict[str, object] = {
            "status": kind,
            "elapsed_s": round(now - started, 2),
            "frames": frames,
            "window_rate_hz": round(window_frames / interval, 2),
            "source_timestamp_repeats": stamps.repeats,
            "source_stamp_advances_over_100ms": stamps.advances_over_100ms,
            "source_stamp_max_hold_ms": round(stamps.max_hold_ms, 1),
            "receive_intervals_over_100ms": receive_intervals_over_100ms,
            "max_receive_interval_ms": round(max_receive_interval_ms, 1),
            "peak_rss_mib": _peak_rss_mib(),
        }
        if latest is not None:
            result.update({
                "source_timestamp_ms": latest.source_timestamp_ms,
                "source_minus_mac_receive_ms": (
                    latest.source_timestamp_ms - latest.received_wall_ms
                ),
                "mac_receive_age_ms": round(
                    (time.monotonic_ns() - latest.received_monotonic_ns) / 1_000_000, 1
                ),
                "source_stamp_advance_age_ms": round(
                    (time.monotonic_ns() - stamps.last_advance_monotonic_ns) / 1_000_000, 1
                ),
                "joint_positions_deg": latest.joint_positions_deg,
                "fsm_code": latest.fsm_code,
                "moving": latest.moving,
                "error_code": latest.error_code,
            })
        output(result)
        report_started = now
        next_report = now + report_every_s
        window_frames = 0
        return result

    with DatasheetClient(
        host, port, byte_order=byte_order, timeout_s=0.5,
        scope=scope,
    ) as client:
        while time.monotonic() < deadline:
            client.poll()
            for sample in client.last_batch:
                if sample.device_sn != expected_device_sn:
                    raise ValueError("DataSheet DeviceSN disagrees with the real config")
                if sample.error_code or any(sample.axis_error_codes):
                    raise ValueError("DataSheet reports a robot or axis error")
                if previous_receive_ns is not None:
                    interval_ms = max(
                        0, sample.received_monotonic_ns - previous_receive_ns
                    ) / 1_000_000
                    max_receive_interval_ms = max(max_receive_interval_ms, interval_ms)
                    if interval_ms > 100:
                        receive_intervals_over_100ms += 1
                previous_receive_ns = sample.received_monotonic_ns
                stamps.observe(sample.source_timestamp_ms, sample.received_monotonic_ns)
                latest = sample
                frames += 1
                window_frames += 1
            client.drain_events()
            now = time.monotonic()
            if now >= next_report:
                report("running", now)
    if frames == 0:
        raise ValueError("DataSheet supplied no complete frames")
    return report("complete", time.monotonic())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Mac-only, receive-only 10004 DataSheet monitoring; no server connection",
    )
    parser.add_argument("--real-config", type=Path, required=True)
    parser.add_argument("--duration-s", type=float, required=True)
    parser.add_argument("--report-every-s", type=float, default=10.0)
    parser.add_argument("--byte-order", choices=("little", "big"), required=True)
    parser.add_argument("--connect-real-read-only", action="store_true")
    parser.add_argument("--vendor-compatibility-confirmed", action="store_true")
    parser.add_argument("--operator-ready", action="store_true")
    args = parser.parse_args(argv)
    if not (
        args.connect_real_read_only
        and args.vendor_compatibility_confirmed
        and args.operator_ready
    ):
        parser.error("live monitoring requires read-only, vendor and operator confirmation")
    config = load_real_config(args.real_config)
    validate_probe_config(config)
    try:
        monitor_datasheet(
            config.controller.host,
            config.controller.datasheet_port,
            config.controller.device_sn,
            byte_order=args.byte_order,
            duration_s=args.duration_s,
            report_every_s=args.report_every_s,
        )
    except (OSError, ConnectionError, ValueError) as exc:
        print(f"DATASHEET MONITOR FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("DATASHEET MONITOR STOPPED BY OPERATOR", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
