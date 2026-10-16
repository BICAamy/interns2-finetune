"""Validate remote MJPEG, telemetry, and an optional relative-motion loop."""

from __future__ import annotations

import argparse
import json
import time
from typing import Any
from urllib.request import Request, urlopen


def request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout_s: float,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=timeout_s) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} returned non-object JSON")
    return value


def open_video(
    base_url: str,
    session_id: str,
    *,
    timeout_s: float,
):
    response = urlopen(
        f"{base_url.rstrip('/')}/api/sessions/{session_id}/simulation/stream.mjpeg",
        timeout=timeout_s,
    )
    content_type = response.headers.get("Content-Type", "")
    if not content_type.lower().startswith("multipart/x-mixed-replace"):
        response.close()
        raise RuntimeError(f"unexpected video Content-Type: {content_type}")
    captured = bytearray()
    while len(captured) < 2 * 1024 * 1024:
        chunk = response.read(4096)
        if not chunk:
            break
        captured.extend(chunk)
        start = captured.find(b"\xff\xd8")
        end = captured.find(b"\xff\xd9", max(0, start + 2))
        if start >= 0 and end > start:
            return response, end - start + 2
    response.close()
    raise RuntimeError("agent-web MJPEG proxy did not return a complete JPEG frame")


def wait_for_terminal(
    base_url: str,
    session_id: str,
    *,
    timeout_s: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    terminal = {"completed", "plan_ready", "failed", "stopped", "estop"}
    while time.monotonic() < deadline:
        session = request_json(
            base_url,
            f"/api/sessions/{session_id}",
            timeout_s=min(timeout_s, 10.0),
        )
        if session.get("status") in terminal:
            return session
        time.sleep(0.1)
    raise TimeoutError("agent-web task did not reach a terminal state")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--execute-relative", action="store_true")
    args = parser.parse_args()

    health = request_json(args.base_url, "/health", timeout_s=10.0)
    if health.get("runtime_mode") != "simulation":
        raise RuntimeError("agent-web is not in simulation mode")
    if health.get("puncture_execution_enabled") is not False:
        raise RuntimeError("puncture execution must remain disabled")

    session = request_json(
        args.base_url,
        "/api/sessions",
        method="POST",
        payload={},
        timeout_s=10.0,
    )
    session_id = str(session["session_id"])
    telemetry_before = request_json(
        args.base_url,
        f"/api/sessions/{session_id}/simulation/telemetry",
        timeout_s=10.0,
    )
    if not telemetry_before.get("connected"):
        raise RuntimeError("simulation telemetry is not connected")
    if len(telemetry_before.get("joint_positions_deg", [])) != 6:
        raise RuntimeError("telemetry did not contain six E05-Pro joints")

    checked_presets: list[str] = []
    for preset in ("front", "left", "right", "top", "isometric", "front"):
        camera = request_json(
            args.base_url,
            f"/api/sessions/{session_id}/simulation/camera",
            method="PUT",
            payload={"action": "preset", "preset": preset},
            timeout_s=10.0,
        )
        if camera.get("preset") != preset:
            raise RuntimeError(f"camera preset {preset!r} was not applied")
        checked_presets.append(preset)
    if float(camera.get("yaw_deg", 1.0)) != 0.0 or float(
        camera.get("pitch_deg", 1.0)
    ) != 0.0:
        raise RuntimeError("front camera is not the expected upright orbit state")
    target = camera.get("target_m", [])
    position = camera.get("position_m", [])
    if len(target) != 3 or len(position) != 3 or abs(float(position[2]) - float(target[2])) > 1e-6:
        raise RuntimeError("front camera does not keep world Z upright")
    telemetry_after_camera = request_json(
        args.base_url,
        f"/api/sessions/{session_id}/simulation/telemetry",
        timeout_s=10.0,
    )
    if int(telemetry_after_camera.get("frame_sequence", 0)) <= int(
        telemetry_before.get("frame_sequence", 0)
    ):
        raise RuntimeError("camera controls did not render a new frame")

    video, jpeg_bytes = open_video(
        args.base_url,
        session_id,
        timeout_s=30.0,
    )
    result: dict[str, Any] = {
        "status": "ok",
        "session_id": session_id,
        "jpeg_bytes": jpeg_bytes,
        "telemetry_sequence": telemetry_before.get("sequence"),
        "frame_sequence": telemetry_before.get("frame_sequence"),
        "camera_presets": checked_presets,
        "camera_frame_sequence": telemetry_after_camera.get("frame_sequence"),
    }
    try:
        if args.execute_relative:
            before = telemetry_after_camera["current_tcp"]
            preview = request_json(
                args.base_url,
                f"/api/sessions/{session_id}/commands/text",
                method="POST",
                payload={
                    "prompt": "机械臂沿基座坐标系 Z 轴正方向移动 8 毫米。"
                },
                timeout_s=args.timeout,
            )
            if preview.get("status") != "awaiting_confirmation":
                raise RuntimeError(
                    f"expected awaiting_confirmation, got {preview.get('status')}"
                )
            request_json(
                args.base_url,
                f"/api/sessions/{session_id}/confirm",
                method="POST",
                payload={},
                timeout_s=10.0,
            )
            terminal = wait_for_terminal(
                args.base_url,
                session_id,
                timeout_s=args.timeout,
            )
            if terminal.get("status") != "completed":
                raise RuntimeError(
                    f"relative task ended as {terminal.get('status')}: "
                    f"{terminal.get('message')}"
                )
            after = request_json(
                args.base_url,
                f"/api/sessions/{session_id}/simulation/telemetry",
                timeout_s=10.0,
            )
            final_tcp = after["current_tcp"]
            delta = [
                float(final_tcp[axis]) - float(before[axis])
                for axis in ("x", "y", "z")
            ]
            if abs(delta[0]) > 0.1 or abs(delta[1]) > 0.1 or abs(delta[2] - 8.0) > 0.1:
                raise RuntimeError(f"unexpected TCP delta: {delta}")
            if int(after.get("frame_sequence", 0)) <= int(
                telemetry_after_camera.get("frame_sequence", 0)
            ):
                raise RuntimeError("video frame sequence did not advance during motion")
            result.update(
                {
                    "relative_motion": "completed",
                    "tcp_delta_mm": [round(value, 4) for value in delta],
                    "final_frame_sequence": after.get("frame_sequence"),
                    "trajectory_total_points": after.get(
                        "trajectory_total_points"
                    ),
                }
            )
    finally:
        video.close()

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
