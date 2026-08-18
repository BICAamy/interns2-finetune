"""Real Step 14 smoke check against a running agent-web service.

Examples:
    python3 -m web.backend.scripts.check_step14_gesture \
        --image /tmp/up.jpg --expected up

    python3 -m web.backend.scripts.check_step14_gesture \
        --image /tmp/stop.jpg --expected stop
"""

from __future__ import annotations

import argparse
import base64
import mimetypes
from pathlib import Path
import sys
import time

import httpx


ORDINARY = {"up", "down", "left", "right", "forward", "backward"}
SAFETY = {"stop", "estop"}
ALL = ORDINARY | SAFETY


def image_data_url(path: Path) -> str:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise SystemExit(f"image does not exist: {path}")
    mime, _ = mimetypes.guess_type(path.name)
    if mime not in {"image/jpeg", "image/png", "image/webp"}:
        raise SystemExit("image must be JPEG, PNG, or WebP")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def post_json(client: httpx.Client, path: str, payload: dict) -> dict:
    response = client.post(path, json=payload)
    if response.status_code >= 400:
        raise SystemExit(
            f"POST {path} failed: HTTP {response.status_code}\n{response.text}"
        )
    value = response.json()
    if not isinstance(value, dict):
        raise SystemExit(f"POST {path} returned non-object JSON")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--expected", required=True, choices=sorted(ALL))
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    data_url = image_data_url(Path(args.image))
    with httpx.Client(
        base_url=args.base_url.rstrip("/"),
        timeout=args.timeout,
        trust_env=False,
    ) as client:
        health = client.get("/health")
        health.raise_for_status()
        created = post_json(client, "/api/sessions", {})
        session_id = created["session_id"]
        print(f"session={session_id}")

        attempts = 2 if args.expected in ORDINARY else 1
        latest: dict = {}
        for index in range(attempts):
            latest = post_json(
                client,
                f"/api/sessions/{session_id}/commands/gesture",
                {
                    "image_data_url": data_url,
                    "captured_at_ms": time.time_ns() // 1_000_000,
                },
            )
            recognition = latest.get("recognition") or {}
            print(
                f"attempt={index + 1}/{attempts} "
                f"gesture={recognition.get('gesture')} "
                f"confidence={recognition.get('confidence')} "
                f"decision={latest.get('decision')} "
                f"latency_ms={recognition.get('latency_ms')}"
            )
            print(f"message={latest.get('message')}")

        recognition = latest.get("recognition") or {}
        actual = recognition.get("gesture")
        if actual != args.expected:
            raise SystemExit(
                f"FAIL: expected gesture {args.expected!r}, got {actual!r}"
            )

        expected_decision = (
            "accepted"
            if args.expected in ORDINARY
            else "safety_stop"
            if args.expected == "stop"
            else "safety_estop"
        )
        if latest.get("decision") != expected_decision:
            raise SystemExit(
                f"FAIL: expected decision {expected_decision!r}, "
                f"got {latest.get('decision')!r}"
            )

        if args.expected in ORDINARY:
            snapshot = latest.get("session_snapshot") or {}
            command = latest.get("mapped_command") or {}
            if not snapshot.get("pending_confirmation"):
                raise SystemExit("FAIL: ordinary gesture did not require confirmation")
            if command.get("intent") != "move_relative":
                raise SystemExit("FAIL: ordinary gesture did not map to move_relative")
            print(f"mapped_command={command}")

        print("STEP14_GESTURE_SMOKE_OK")


if __name__ == "__main__":
    main()
