"""Check Step 13 ASR readiness and optionally submit one recorded command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import httpx


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--duration-ms", type=int)
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args()

    try:
        result = run_check(
            args.base_url,
            audio=args.audio,
            duration_ms=args.duration_ms,
            timeout=args.timeout,
        )
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": type(error).__name__,
                    "message": str(error),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def run_check(
    base_url: str,
    *,
    audio: Path | None,
    duration_ms: int | None,
    timeout: float,
) -> dict:
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout) as client:
        health = _json_response(client.get("/health"))
        status = _json_response(client.get("/api/asr/status"))
        if not status.get("available"):
            raise RuntimeError(
                f"ASR unavailable: {status.get('unavailable_reason') or 'unknown reason'}"
            )
        result: dict = {
            "status": "ok",
            "service": health.get("service"),
            "asr": status,
        }
        if audio is None:
            return result
        selected = audio.expanduser().resolve()
        if not selected.is_file():
            raise FileNotFoundError(selected)
        if duration_ms is None or duration_ms <= 0:
            raise ValueError("--duration-ms is required with --audio")
        mime_type = {
            ".webm": "audio/webm",
            ".ogg": "audio/ogg",
            ".oga": "audio/ogg",
            ".mp4": "audio/mp4",
            ".m4a": "audio/mp4",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
        }.get(selected.suffix.lower(), "audio/webm")
        session = _json_response(client.post("/api/sessions"))
        submitted = _json_response(
            client.post(
                f"/api/sessions/{session['session_id']}/commands/speech",
                content=selected.read_bytes(),
                headers={
                    "Content-Type": mime_type,
                    "X-Audio-Duration-Ms": str(duration_ms),
                },
            )
        )
        transcription = submitted.get("asr_transcription") or {}
        result["speech"] = {
            "session_id": submitted.get("session_id"),
            "session_status": submitted.get("status"),
            "pending_confirmation": submitted.get("pending_confirmation"),
            "transcript": transcription.get("text"),
            "confidence": transcription.get("confidence"),
            "low_confidence": transcription.get("low_confidence"),
            "asr_latency_ms": transcription.get("asr_latency_ms"),
            "end_to_end_latency_ms": transcription.get("end_to_end_latency_ms"),
            "safety_action": transcription.get("safety_action"),
            "normalized_command": submitted.get("normalized_command"),
        }
        return result


def _json_response(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError as error:
        raise RuntimeError(
            f"HTTP {response.status_code} returned non-JSON content"
        ) from error
    if response.is_error:
        raise RuntimeError(
            f"HTTP {response.status_code}: {payload.get('message') or payload}"
        )
    if not isinstance(payload, dict):
        raise RuntimeError("service response must be a JSON object")
    return payload


if __name__ == "__main__":
    sys.exit(main())
