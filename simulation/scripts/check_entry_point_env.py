"""Run the Step 5 absolute, relative, trajectory, and RGB acceptance smoke test."""

from __future__ import annotations

import faulthandler
import json
import os
import sys
import traceback
from math import dist
from typing import Any

import numpy as np

from simulation.entry_point_env import EntryPointEnvConfig
from simulation.entry_point_env.environment import EntryPointReachEnv
from sofa_env.base import RenderMode
from surgical_contracts import MotionState, Point3D


def _progress(stage: str, **details: Any) -> None:
    suffix = ""
    if details:
        suffix = " " + json.dumps(details, ensure_ascii=False, sort_keys=True)
    print(f"[step5-smoke] {stage}{suffix}", file=sys.stderr, flush=True)


def _run_until_settled(env: EntryPointReachEnv, maximum_steps: int) -> tuple[Any, int]:
    for step_number in range(1, maximum_steps + 1):
        step = env.step()
        if step_number == 1 or step_number % 25 == 0:
            _progress(
                "motion_progress",
                step=step_number,
                state=step.state.motion_state.value,
                error_mm=step.position_error_mm,
            )
        if step.state.motion_state != MotionState.MOVING:
            return step, step_number
    raise RuntimeError(f"motion did not settle within {maximum_steps} steps")


def run_check() -> dict[str, Any]:
    if not os.environ.get("DISPLAY"):
        raise RuntimeError("Step 5 RGB validation must run through run-with-xvfb")

    config = EntryPointEnvConfig.from_yaml()
    if config.robot.model_name != "E05-Pro" or not config.robot.force_control_variant:
        raise RuntimeError("Step 5 must run the E05-Pro force-control model")
    if config.real_robot_ready:
        raise RuntimeError("provisional needle TCP must keep real robot motion disabled")
    env = EntryPointReachEnv(config=config, render_mode=RenderMode.HUMAN)
    try:
        _progress("reset_start")
        observation = env.reset(seed=2026)
        initial_position = observation.state.tcp_position
        initial_joint_positions_deg = observation.joint_positions_deg
        entry_point = Point3D(x=500.0, y=0.0, z=500.0)
        entry_speed_mm_s = 25.0

        _progress("move_to_entry_start", entry_point=entry_point.as_tuple())
        entry_command_id = env.move_to_entry(entry_point, speed_mm_s=entry_speed_mm_s)
        entry_step, entry_steps = _run_until_settled(env, maximum_steps=250)
        if not entry_step.reached or entry_step.state.motion_state != MotionState.AT_ENTRY:
            raise RuntimeError("entry-point command did not finish in AT_ENTRY state")
        if entry_step.position_error_mm is None or entry_step.position_error_mm > config.reach_tolerance_mm:
            raise RuntimeError("entry-point error exceeds configured tolerance")
        np.testing.assert_allclose(
            env.scene_tcp_position_mm(),
            entry_point.as_tuple(),
            atol=config.reach_tolerance_mm,
        )

        _progress("relative_motion_start", delta_mm=(0.0, 0.0, 5.0))
        relative_start = np.asarray(env.scene_tcp_position_mm())
        relative_command_id = env.move_relative((0.0, 0.0, 5.0))
        relative_step, relative_steps = _run_until_settled(env, maximum_steps=50)
        expected_final = relative_start + np.asarray([0.0, 0.0, 5.0])
        np.testing.assert_allclose(
            env.scene_tcp_position_mm(),
            expected_final,
            atol=config.reach_tolerance_mm,
        )

        frame = env.render()
        if frame.shape != config.image_shape + (3,) or frame.dtype != np.uint8:
            raise RuntimeError(f"unexpected RGB frame: shape={frame.shape}, dtype={frame.dtype}")
        if int(np.ptp(frame)) == 0:
            raise RuntimeError("rendered RGB frame is uniform")
        if np.linalg.norm(
            np.asarray(relative_step.joint_positions_deg)
            - np.asarray(initial_joint_positions_deg)
        ) <= 1.0:
            raise RuntimeError("TCP moved without a meaningful E05-Pro joint change")

        trajectory = env.controller.trajectory_mm
        jumps = [dist(start, end) for start, end in zip(trajectory, trajectory[1:])]
        maximum_jump = max(jumps, default=0.0)
        allowed_jump = max(entry_speed_mm_s, config.default_speed_mm_s) * config.time_step_s
        if maximum_jump > allowed_jump + 1e-9:
            raise RuntimeError("trajectory contains an instantaneous jump")

        _progress("smoke_test_complete")
        return {
            "status": "ok",
            "environment": "EntryPointReachEnv",
            "robot_model": config.robot.model_name,
            "force_control_variant": config.robot.force_control_variant,
            "model_source_commit": config.robot.source_commit,
            "tcp": config.tcp_name,
            "tcp_transform_provisional": config.robot.tool_transform.provisional,
            "real_robot_ready": config.real_robot_ready,
            "coordinate_frame": config.coordinate_frame.value,
            "units": "mm",
            "initial_position_mm": initial_position.as_tuple(),
            "initial_joint_positions_deg": initial_joint_positions_deg,
            "entry_point_mm": entry_point.as_tuple(),
            "entry_command_id": entry_command_id,
            "entry_steps": entry_steps,
            "entry_error_mm": entry_step.position_error_mm,
            "reached_entry_position_mm": entry_step.state.tcp_position.as_tuple(),
            "relative_command_id": relative_command_id,
            "relative_delta_mm": [0.0, 0.0, 5.0],
            "relative_steps": relative_steps,
            "final_position_mm": relative_step.state.tcp_position.as_tuple(),
            "final_joint_positions_deg": relative_step.joint_positions_deg,
            "trajectory_points": len(trajectory),
            "maximum_step_mm": round(maximum_jump, 9),
            "allowed_maximum_step_mm": allowed_jump,
            "rgb": {
                "generated": True,
                "shape": list(frame.shape),
                "dtype": str(frame.dtype),
                "minimum": int(frame.min()),
                "maximum": int(frame.max()),
                "mean": round(float(frame.mean()), 4),
            },
            "motion_state": relative_step.state.motion_state.value,
            "puncture_logic_present": False,
        }
    finally:
        _progress("close_start")
        env.close()
        _progress("close_complete")


def main() -> int:
    faulthandler.enable()
    faulthandler.dump_traceback_later(60, repeat=True)
    try:
        result = run_check()
    except Exception as error:  # pragma: no cover - exercised inside the image
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": type(error).__name__,
                    "message": str(error),
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        traceback.print_exc()
        return 1
    finally:
        faulthandler.cancel_dump_traceback_later()

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
