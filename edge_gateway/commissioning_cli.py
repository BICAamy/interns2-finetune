"""Mac-local Step 11 preparation. This entry point is READ-ONLY.

The Step 10 motion client is fake-only. Until the real Gate C evidence and
controller mode/stop semantics are resolved, this CLI must not offer an ARM
or a real WayPoint path. In particular, ``--control local-only`` is a scope
assertion, not permission to move.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path
from typing import Mapping, TextIO

from robot_runtime.real_config import RealRobotConfig, load_real_config

from .huayan.real_probe import _save_probe_result, probe_once, validate_probe_config


# Local software caps for the *first* 1 mm trial. The YAML may retain the
# controller's higher readback maxima; a future writer must use the lower of
# the two, and must enforce zero rotation independently of its YAML ceiling.
FIRST_MOTION_CAPS = {
    "max_speed_mm_s": 5.0,
    "max_acceleration_mm_s2": 20.0,
    "max_step_mm": 1.0,
}


def first_motion_config_blockers(config: RealRobotConfig) -> tuple[str, ...]:
    """Report configuration blockers without treating a filled YAML as Gate C."""
    blockers = list(config.blocking_fields())
    if config.allowed_control != "observe-only":
        blockers.append("allowed_control must remain observe-only")
    if config.tool.setup != "flange_only_no_tool":
        blockers.append("Step 11 currently supports only a verified bare flange")
    return tuple(blockers)


def effective_first_motion_caps(config: RealRobotConfig) -> dict[str, float | None]:
    """Intersect controller-configured maxima with hard local trial limits."""
    result: dict[str, float | None] = {
        name: min(value, cap) if value is not None else None
        for name, cap in FIRST_MOTION_CAPS.items()
        for value in (getattr(config.limits, name),)
    }
    result["rotation_deg"] = 0.0
    return result


def require_local_mac_terminal(
    *, environment: Mapping[str, str] | None = None,
    system: str | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> None:
    """Reject server, SSH and noninteractive local-only commissioning."""
    environment = os.environ if environment is None else environment
    system = platform.system() if system is None else system
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    if system != "Darwin":
        raise PermissionError("commissioning must run on the Mac beside the robot")
    if any(environment.get(key) for key in ("SSH_CLIENT", "SSH_CONNECTION", "SSH_TTY")):
        raise PermissionError("commissioning cannot run through SSH")
    if not stdin.isatty() or not stdout.isatty():
        raise PermissionError("commissioning requires a local interactive terminal")


def _report(
    config: RealRobotConfig, *, record: Path | None = None,
    probe_summary: dict[str, object] | None = None,
) -> dict[str, object]:
    blockers = first_motion_config_blockers(config)
    return {
        "mode": "local-only-read-only-preflight",
        "config_sha256": config.digest(),
        "device_sn": config.controller.device_sn,
        "first_motion_config_blockers": blockers,
        "effective_first_motion_caps": effective_first_motion_caps(config),
        "read_only_record": str(record) if record is not None else None,
        "no_tool_readback_verified": (
            probe_summary.get("no_tool_readback_verified") is True
            if probe_summary is not None else None
        ),
        "three_position_enable_verified": False,
        "motion_authorized": False,
        "message": "No real-motion writer or ARM is exposed by this command",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Step 11 Mac-local READ-ONLY preparation")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--control", choices=("local-only",))
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check-config", action="store_true", help="offline, no controller connection")
    action.add_argument("--preflight-read-only", action="store_true", help="fixed read-only controller probe")
    parser.add_argument("--byte-order", choices=("little", "big"))
    parser.add_argument("--operator-ready", action="store_true")
    parser.add_argument("--vendor-compatibility-confirmed", action="store_true")
    args = parser.parse_args(argv)

    try:
        config = load_real_config(args.config)
    except (OSError, ValueError) as exc:
        print(f"CONFIG BLOCKED: {exc}", file=sys.stderr)
        return 2

    if args.check_config:
        print(json.dumps(_report(config), ensure_ascii=False, indent=2))
        return 2 if first_motion_config_blockers(config) else 0

    if args.control != "local-only":
        parser.error("read-only preflight requires --control local-only")
    if not (args.byte_order and args.operator_ready and args.vendor_compatibility_confirmed):
        parser.error("real read-only preflight requires byte order, operator readiness and vendor compatibility")
    try:
        require_local_mac_terminal()
        validate_probe_config(config)
        result = probe_once(config, byte_order=args.byte_order, scope="private-read-only")
        record = _save_probe_result(result)
    except (OSError, ValueError, RuntimeError, PermissionError) as exc:
        print(f"READ-ONLY PREFLIGHT BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(_report(config, record=record, probe_summary=result.summary),
                     ensure_ascii=False, indent=2))
    return 0  # Read-only preflight succeeded; real motion remains closed.


if __name__ == "__main__":
    raise SystemExit(main())
