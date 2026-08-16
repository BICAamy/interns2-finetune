"""MJPEG encoding and streaming helpers."""

from __future__ import annotations

from io import BytesIO
import time
from typing import Any, Iterator


MJPEG_BOUNDARY = "frame"


def encode_jpeg(frame: Any, *, quality: int = 85) -> bytes:
    from PIL import Image

    image = Image.fromarray(frame, mode="RGB")
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=False)
    return buffer.getvalue()


def mjpeg_chunk(jpeg: bytes) -> bytes:
    return (
        f"--{MJPEG_BOUNDARY}\r\n"
        "Content-Type: image/jpeg\r\n"
        f"Content-Length: {len(jpeg)}\r\n\r\n"
    ).encode("ascii") + jpeg + b"\r\n"


def mjpeg_stream(worker: Any, *, maximum_fps: float = 10.0) -> Iterator[bytes]:
    minimum_interval = 1.0 / max(1.0, maximum_fps)
    sequence = -1
    latest_jpeg: bytes | None = None
    worker.register_client()
    try:
        while True:
            started = time.monotonic()
            sequence, frame = worker.wait_for_frame(
                sequence,
                timeout_s=minimum_interval,
            )
            if frame is not None:
                latest_jpeg = encode_jpeg(frame)
            if latest_jpeg is None:
                continue
            # Repeat the most recent frame while the scene is static. Besides
            # making MJPEG behave like a normal video source, the periodic
            # yield lets the ASGI server observe client disconnects promptly.
            yield mjpeg_chunk(latest_jpeg)
            delay = minimum_interval - (time.monotonic() - started)
            if delay > 0.0:
                time.sleep(delay)
    finally:
        worker.unregister_client()
