"""Run a finite, rendered smoke test on sofa_env's controllable example."""

from __future__ import annotations

import argparse
import faulthandler
import json
import os
import platform
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np
import sofa_env.scenes.controllable_object_example.controllable_env as upstream_controllable
from sofa_env.base import RenderFramework, RenderMode, SofaEnv
from sofa_env.scenes.controllable_object_example.controllable_env import ControllableEnv


def _progress(stage: str, **details: Any) -> None:
    suffix = ""
    if details:
        suffix = " " + json.dumps(details, ensure_ascii=False, sort_keys=True)
    print(f"[step4-smoke] {stage}{suffix}", file=sys.stderr, flush=True)


class SmokeControllableEnv(ControllableEnv):
    """Compatibility wrapper around the pinned upstream example.

    The fixed upstream commit references an undefined ``done`` variable in
    ``step`` and increments the quaternion while translating. The smoke test
    corrects those two example-level defects without modifying vendored code.
    """

    def _do_action(self, action: np.ndarray) -> None:
        action = np.asarray(action, dtype=np.float32)
        if action.shape != (3,):
            raise ValueError(f"Expected action shape (3,), got {action.shape}")

        old_pose = np.asarray(
            self.scene_creation_result["controllable_sphere"].get_pose(),
            dtype=np.float64,
        ).copy()
        new_pose = old_pose.copy()
        new_pose[:3] += action * self.time_step * self.maximum_velocity
        self.scene_creation_result["controllable_sphere"].set_pose(new_pose)

    def step(self, action: np.ndarray) -> tuple[Any, float, bool, bool, dict[str, Any]]:
        rgb_observation = SofaEnv.step(self, action)
        position = np.asarray(
            self.scene_creation_result["controllable_sphere"].get_pose()[:3],
            dtype=np.float64,
        )
        terminated = bool(position[0] <= -130.0)
        return (
            rgb_observation,
            10.0 if terminated else 0.0,
            terminated,
            False,
            {"sphere_position": position},
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, default=10)
    parser.add_argument(
        "--render-backend",
        choices=("xvfb", "egl", "none"),
        default="xvfb",
        help="xvfb is the required Step 4 path; egl is an optional host-dependent check",
    )
    return parser.parse_args()


def _render_mode(backend: str) -> RenderMode:
    if backend == "xvfb":
        if not os.environ.get("DISPLAY"):
            raise RuntimeError(
                "The xvfb backend requires DISPLAY. Run this script through "
                "`xvfb-run --server-num=99 --error-file=/dev/stderr`."
            )
        return RenderMode.HUMAN
    if backend == "egl":
        return RenderMode.HEADLESS
    return RenderMode.NONE


def _frame_summary(frame: Any) -> dict[str, Any]:
    if frame is None:
        return {"generated": False}

    array = np.asarray(frame)
    if array.ndim != 3 or array.shape[2] != 3:
        raise RuntimeError(f"Expected an HxWx3 RGB frame, got shape {array.shape}")
    if array.dtype != np.uint8:
        raise RuntimeError(f"Expected uint8 RGB data, got {array.dtype}")
    if int(np.ptp(array)) == 0:
        raise RuntimeError("Rendered frame is uniform; OpenGL did not produce a useful RGB image")

    return {
        "generated": True,
        "shape": list(array.shape),
        "dtype": str(array.dtype),
        "minimum": int(array.min()),
        "maximum": int(array.max()),
        "mean": round(float(array.mean()), 4),
    }


def _gl_string(env: SmokeControllableEnv, name: str) -> str | None:
    if not hasattr(env, "opengl_gl"):
        return None
    value = env.opengl_gl.glGetString(getattr(env.opengl_gl, name))
    if value is None:
        return None
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)


def run_smoke_test(steps: int, backend: str) -> dict[str, Any]:
    if steps <= 0:
        raise ValueError("--steps must be greater than zero")

    render_mode = _render_mode(backend)
    _progress("create_environment", backend=backend, steps=steps)
    env = SmokeControllableEnv(
        scene_path=Path(upstream_controllable.__file__).resolve().with_name(
            "scene_description.py"
        ),
        render_mode=render_mode,
        render_framework=RenderFramework.PYGLET,
    )

    started_at = time.perf_counter()
    try:
        _progress("reset_start")
        reset_frame, reset_info = env.reset(seed=0)
        _progress(
            "reset_complete",
            elapsed_seconds=round(time.perf_counter() - started_at, 4),
        )
        initial_position = np.asarray(
            env.scene_creation_result["controllable_sphere"].get_pose()[:3],
            dtype=np.float64,
        ).copy()
        action = np.asarray([-0.25, 0.10, 0.0], dtype=np.float32)
        if not env.action_space.contains(action):
            raise RuntimeError(f"Smoke-test action is outside action space: {action}")

        last_frame = reset_frame
        last_info: dict[str, Any] = dict(reset_info)
        terminated = False
        truncated = False
        completed_steps = 0
        for step_number in range(1, steps + 1):
            _progress("step_start", step=step_number)
            last_frame, _, terminated, truncated, last_info = env.step(action)
            completed_steps = step_number
            _progress(
                "step_complete",
                step=step_number,
                terminated=terminated,
                truncated=truncated,
            )
            if terminated or truncated:
                break

        final_position = np.asarray(last_info["sphere_position"], dtype=np.float64)
        displacement = final_position - initial_position
        if float(np.linalg.norm(displacement)) <= 0.0:
            raise RuntimeError("The controllable object did not move during the smoke test")

        _progress("frame_validation_start")
        frame = _frame_summary(last_frame)
        if backend != "none" and not frame["generated"]:
            raise RuntimeError("Rendered backend did not return an RGB frame")

        result = {
            "status": "ok",
            "python": platform.python_version(),
            "environment": "controllable_object_example",
            "render_backend": backend,
            "display": os.environ.get("DISPLAY"),
            "requested_steps": steps,
            "completed_steps": completed_steps,
            "terminated": terminated,
            "truncated": truncated,
            "initial_position": initial_position.round(6).tolist(),
            "final_position": final_position.round(6).tolist(),
            "displacement": displacement.round(6).tolist(),
            "rgb": frame,
            "opengl": {
                "vendor": _gl_string(env, "GL_VENDOR"),
                "renderer": _gl_string(env, "GL_RENDERER"),
                "version": _gl_string(env, "GL_VERSION"),
            },
            "elapsed_seconds": round(time.perf_counter() - started_at, 4),
            "upstream_compatibility_workarounds": [
                "replace undefined done variable in ControllableEnv.step",
                "preserve quaternion during Cartesian translation",
            ],
        }
        _progress("smoke_test_complete")
        return result
    finally:
        _progress("close_start")
        env.close()
        _progress("close_complete")


def main() -> int:
    args = _parse_args()
    faulthandler.enable()
    faulthandler.dump_traceback_later(60, repeat=True)
    try:
        result = run_smoke_test(args.steps, args.render_backend)
    except Exception as error:  # pragma: no cover - exercised inside the image
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": type(error).__name__,
                    "message": str(error),
                    "render_backend": args.render_backend,
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
