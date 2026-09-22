"""Mac-local, one-command commissioning; no cloud/ordinary gateway handler."""

from __future__ import annotations

import argparse
import json
import os
import platform
import secrets
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Mapping, TextIO

from robot_runtime.real_config import RealRobotConfig, load_real_config
from surgical_contracts import (
    CoordinateFrame, GatewayCommandKind, MotionSafetyLimits,
    MoveRelativeRequest, RobotCommandEnvelope,
)

from .command_journal import CommandJournal
from .fake_motion import LocalMotionTiming, LocalMotionTrial
from .huayan.command_codec import validate_identifier
from .huayan.real_probe import _save_probe_result, probe_once, validate_probe_config
from .huayan.real_motion_client import LocalRealMotionClient
from .preflight import LocalArm, MotionLease, fingerprint, safety_state_hash

if TYPE_CHECKING:
    from .commissioning_runtime import LocalDataSheetSampler


# Local software caps for the *first* 1 mm trial. The YAML may retain the
# controller's higher readback maxima; the writer uses the lower of the two.
FIRST_MOTION_CAPS = {
    "max_speed_mm_s": 5.0,
    "max_acceleration_mm_s2": 20.0,
    "max_step_mm": 1.0,
}
FIRST_MOTION_MOTION_TIMEOUT_MS = 10_000


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
        "three_position_enable_required": False,
        "motion_authorized": False,
        "message": "This check/probe sends no motion; --execute-relative is a separate local-only action",
    }


_AXES = {
    "+X": (1.0, 0.0, 0.0), "-X": (-1.0, 0.0, 0.0),
    "+Y": (0.0, 1.0, 0.0), "-Y": (0.0, -1.0, 0.0),
    "+Z": (0.0, 0.0, 1.0), "-Z": (0.0, 0.0, -1.0),
}


def _journal_path() -> Path:
    # Never partition this by date: an ambiguous write at midnight must still
    # block the next day's process. The per-day probe records remain separate.
    root = Path(__file__).resolve().parents[1]
    return root / "artifacts" / "real_robot_commissioning" / "step11" / "commands.journal"


def _require_phrase(prompt: str, expected: str) -> None:
    try:
        response = input(prompt).strip()
    except EOFError as exc:
        raise PermissionError("local operator confirmation was not entered") from exc
    if response != expected:
        raise PermissionError("local operator confirmation did not match")


def _monitor_one_motion(
    trial: LocalMotionTrial, sampler: LocalDataSheetSampler,
    client: LocalRealMotionClient, config: RealRobotConfig, *, session_id: str,
) -> int:
    from .commissioning_runtime import read_motion_feedback

    last_sequence = trial.last_sequence
    while True:
        try:
            if not trial.lease_active and trial.stop_delivery is None:
                delivered = trial.request_stop()
                print(f"Local motion lease expired; stop delivery={delivered}")
            record = sampler.snapshot()
            if record.sequence > last_sequence:
                feedback = read_motion_feedback(config, client, sampler, session_id=session_id)
                last_sequence = feedback.sequence
                outcome = trial.observe(feedback)
                if outcome == "succeeded":
                    print("MOTION SUCCEEDED: owned WayPoint ID, READY, InPos and stable actual pose")
                    return 0
                if outcome in ("stopped", "stop_unconfirmed"):
                    print(f"MOTION {outcome.upper()}: check robot physically before any new trial")
                    return 2
            state = trial.watchdog()
            if state == "stop_unconfirmed":
                print("STOP UNCONFIRMED: use the physical emergency-stop procedure if necessary")
                return 2
            time.sleep(0.01)
        except KeyboardInterrupt:
            delivered = trial.request_stop()
            print(f"Software stop delivery: {delivered}; waiting for actual stop feedback")
        except Exception as exc:
            delivered = trial.request_stop()
            print(f"FEEDBACK FAULT: {type(exc).__name__}; stop delivery={delivered}")
            print("Robot may keep moving, including after 10003 disconnect. Use physical emergency stop if needed.")
            return 2


def _execute_relative(config: RealRobotConfig, args: argparse.Namespace) -> int:
    """Exactly one human-approved Base-axis 1 mm command, then exit."""
    require_local_mac_terminal()
    if args.expected_config_sha256 != config.digest():
        raise ValueError("explicit config SHA-256 does not match the loaded profile")
    if first_motion_config_blockers(config):
        raise ValueError("commissioning config has missing or incompatible fields")
    test_id = validate_identifier(args.test_id)
    axis = _AXES[args.axis]
    caps = effective_first_motion_caps(config)
    if caps["max_step_mm"] < 1.0 or caps["max_speed_mm_s"] < 2.0:
        raise ValueError("configured cap cannot permit the fixed 1 mm / 2 mm/s trial")
    validate_probe_config(config)
    from .commissioning_runtime import (
        LocalDataSheetSampler, make_approval, make_path_ik, observe_stationary,
        read_local_observation, validate_final_observation,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
    ).stdout.strip()
    print(json.dumps({
        "test_id": test_id, "commit": commit, "config_sha256": config.digest(),
        "device_sn": config.controller.device_sn, "axis": args.axis,
        "distance_mm": 1.0, "speed_mm_s": 2.0,
        "acceleration_mm_s2": caps["max_acceleration_mm_s2"],
        "tcp": config.tool.tcp_name, "ucs": "Base", "rotation_deg": 0,
    }, ensure_ascii=False, indent=2))
    print("Gate D: bare flange, empty reachable area, no patient, physical E-stop tested today and reachable.")
    print("Confirm robot enabled/READY, known manual or Auto mode, no other page/pendant/script writer.")
    print("10003 disconnect DOES NOT stop the current WayPoint; GrpStop OK does not prove stopped.")
    _require_phrase("Type GATE-D <test-id> to begin read-only observation: ", f"GATE-D {test_id}")

    # A persistent path ensures an unknown command blocks a later process.
    with CommandJournal(_journal_path()) as journal:
        if journal.unresolved():
            raise RuntimeError("previous command outcome unresolved; reconcile physically before any new motion")
        probe = probe_once(config, byte_order=args.byte_order, scope="private-read-only")
        record_path = _save_probe_result(probe)
        print(f"Fresh bare-flange read-only probe: {record_path}")
        timeout_s = min(config.deadlines.response_ms, config.deadlines.stop_delivery_ms, 500) / 1000
        with LocalRealMotionClient(config, timeout_s=timeout_s) as client:
            session_id = secrets.token_hex(16)
            with LocalDataSheetSampler(config, byte_order=args.byte_order) as sampler:
                print("Observing stationary real feedback for 120 seconds; any motion/change aborts.")
                observe_stationary(sampler, duration_s=120.0)
                proposal = read_local_observation(config, client, sampler, session_id=session_id)
                approval = make_approval(config, package_version=client.package_version)
                pose = proposal.telemetry.actual_pose_robot_base
                target = tuple(a + b for a, b in zip(pose.translation_mm, axis))
                now_ms = time.time_ns() // 1_000_000
                command_id = "C" + secrets.token_hex(12)
                envelope = RobotCommandEnvelope(
                    gateway_session_id=session_id, command_id=command_id,
                    command_kind=GatewayCommandKind.MOVE_RELATIVE,
                    created_at_ms=now_ms, expires_at_ms=now_ms + 60_000,
                    based_on_robot_state_sequence=proposal.telemetry.sequence,
                    expected_start_pose_robot_base=pose,
                    expected_tcp_name=config.tool.tcp_name, expected_ucs_name="Base",
                    payload=MoveRelativeRequest(
                        command_id=command_id, translation_mm=axis,
                        frame=CoordinateFrame.ROBOT_BASE, speed_mm_s=2.0,
                    ),
                    safety_limits=MotionSafetyLimits(
                        max_speed_mm_s=approval.max_speed_mm_s,
                        max_step_mm=approval.max_step_mm,
                    ),
                    operator_confirmation_id=test_id,
                )
                digest = fingerprint(envelope)
                print(json.dumps({
                    "test_id": test_id, "command_id": command_id,
                    "proposal_fingerprint": digest,
                    "source_sequence": proposal.telemetry.sequence,
                    "start_xyz_mm": pose.translation_mm, "target_xyz_mm": target,
                    "joints_deg": proposal.telemetry.joint_positions_deg,
                    "auto_mode": proposal.telemetry.auto_mode,
                    "reduced_mode": proposal.telemetry.reduced_mode,
                    "waypoint_before": proposal.readback.waypoint_id,
                    "speed_mm_s": 2.0,
                    "acceleration_mm_s2": approval.max_acceleration_mm_s2,
                }, ensure_ascii=False, indent=2))
                _require_phrase("Type ARM <full proposal fingerprint>: ", f"ARM {digest}")
                arm = LocalArm(
                    test_id=test_id, command_fingerprint=digest,
                    session_id=session_id, base_sequence=proposal.telemetry.sequence,
                    safety_state_hash=safety_state_hash(proposal.telemetry, proposal.readback),
                    expected_start=pose,
                    expires_monotonic_ns=time.monotonic_ns() + 30_000_000_000,
                )
                _require_phrase("Type SEND <full proposal fingerprint> within 30 s: ", f"SEND {digest}")
                latest = read_local_observation(config, client, sampler, session_id=session_id)
                lease = MotionLease("local", session_id, time.monotonic_ns() + 60_000_000_000)
                timing = LocalMotionTiming(
                    response_ms=config.deadlines.response_ms,
                    start_ms=config.deadlines.startup_ms,
                    motion_ms=min(config.deadlines.motion_ms, FIRST_MOTION_MOTION_TIMEOUT_MS),
                    stop_confirmation_ms=config.deadlines.stop_ack_ms,
                    stable_samples=config.arrival.stable_samples,
                    dwell_ms=config.arrival.dwell_ms,
                    position_tolerance_mm=config.arrival.position_tolerance_mm,
                    orientation_tolerance_deg=config.arrival.orientation_tolerance_deg,
                )
                trial = LocalMotionTrial(
                    client=client, journal=journal, timing=timing, approval=approval,
                    path_ik=make_path_ik(config, latest.telemetry),
                )

                def final_guard() -> None:
                    _require_unchanged_config(args.config, config)
                    validate_final_observation(
                        latest,
                        read_local_observation(config, client, sampler, session_id=session_id),
                        config,
                    )
                    if (
                        time.monotonic_ns() >= arm.expires_monotonic_ns
                        or not lease.active
                        or time.monotonic_ns() >= lease.expires_monotonic_ns
                        or time.time_ns() // 1_000_000 >= envelope.expires_at_ms
                    ):
                        raise TimeoutError("ARM, local lease or proposal expired before WayPoint")

                outcome = trial.submit(
                    envelope, latest.telemetry, latest.readback, arm, (lease,),
                    final_guard=final_guard,
                )
                if outcome == "stopping":
                    print("WayPoint returned Fail; software stop sent, waiting for actual stop feedback")
                    _monitor_one_motion(trial, sampler, client, config, session_id=session_id)
                    return 2
                if outcome != "accepted":
                    print(f"WayPoint {outcome}; physical stop must be verified; no retry")
                    return 2
                print(f"WayPoint accepted, ID={trial.waypoint_id}; waiting for actual feedback")
                return _monitor_one_motion(trial, sampler, client, config, session_id=session_id)


def _require_unchanged_config(path: Path, loaded: RealRobotConfig) -> None:
    if load_real_config(path).digest() != loaded.digest():
        raise ValueError("commissioning configuration changed before WayPoint")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Step 11 Mac-local single-use commissioning")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--control", choices=("local-only",))
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check-config", action="store_true", help="offline, no controller connection")
    action.add_argument("--preflight-read-only", action="store_true", help="fixed read-only controller probe")
    action.add_argument("--execute-relative", action="store_true", help="one local 1 mm Base-axis trial")
    parser.add_argument("--byte-order", choices=("little", "big"))
    parser.add_argument("--operator-ready", action="store_true")
    parser.add_argument("--vendor-compatibility-confirmed", action="store_true")
    parser.add_argument("--axis", choices=tuple(_AXES))
    parser.add_argument("--test-id")
    parser.add_argument("--expected-config-sha256")
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
        parser.error("real local action requires --control local-only")
    if not (args.byte_order and args.operator_ready and args.vendor_compatibility_confirmed):
        parser.error("real local action requires byte order, operator readiness and vendor compatibility")
    if args.execute_relative:
        if not (args.axis and args.test_id and args.expected_config_sha256):
            parser.error("motion requires axis, test ID and explicit matching config SHA-256")
        try:
            return _execute_relative(config, args)
        except KeyboardInterrupt:
            print("LOCAL MOTION INTERRUPTED: a WayPoint may still be moving; check the robot and persistent journal before any new trial.", file=sys.stderr)
            return 2
        except (OSError, ValueError, RuntimeError, PermissionError) as exc:
            print(f"LOCAL MOTION BLOCKED/FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
            print("If any WayPoint may have been sent, check the physical robot and journal before another trial.", file=sys.stderr)
            return 2
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
