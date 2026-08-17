"""Environment-backed ASR configuration with bounded upload defaults."""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path


def _as_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return float(value)
    except ValueError as error:
        raise ValueError(f"{name} must be a number, got {value!r}") from error


def _as_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer, got {value!r}") from error


@dataclass(frozen=True)
class ASRSettings:
    backend: str = "faster-whisper"
    model_path: Path = Path("/opt/asr-models/faster-whisper-small")
    model_name: str = "faster-whisper-small"
    device: str = "cpu"
    compute_type: str = "int8"
    language: str = "zh"
    beam_size: int = 5
    cpu_threads: int = 4
    max_audio_bytes: int = 10 * 1024 * 1024
    max_duration_s: float = 30.0
    min_duration_s: float = 0.25
    low_confidence_threshold: float = 0.65

    @classmethod
    def from_env(cls) -> "ASRSettings":
        settings = cls(
            backend=os.getenv("ASR_BACKEND", "faster-whisper").strip().lower(),
            model_path=Path(
                os.getenv(
                    "ASR_MODEL_PATH",
                    "/opt/asr-models/faster-whisper-small",
                ).strip()
            ),
            model_name=os.getenv("ASR_MODEL_NAME", "faster-whisper-small").strip(),
            device=os.getenv("ASR_DEVICE", "cpu").strip().lower(),
            compute_type=os.getenv("ASR_COMPUTE_TYPE", "int8").strip(),
            language=os.getenv("ASR_LANGUAGE", "zh").strip().lower(),
            beam_size=_as_int("ASR_BEAM_SIZE", 5),
            cpu_threads=_as_int("ASR_CPU_THREADS", 4),
            max_audio_bytes=_as_int("ASR_MAX_AUDIO_BYTES", 10 * 1024 * 1024),
            max_duration_s=_as_float("ASR_MAX_DURATION_SECONDS", 30.0),
            min_duration_s=_as_float("ASR_MIN_DURATION_SECONDS", 0.25),
            low_confidence_threshold=_as_float(
                "ASR_LOW_CONFIDENCE_THRESHOLD",
                0.65,
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.backend != "faster-whisper":
            raise ValueError("ASR_BACKEND must be faster-whisper")
        if not str(self.model_path):
            raise ValueError("ASR_MODEL_PATH cannot be empty")
        if not self.model_name:
            raise ValueError("ASR_MODEL_NAME cannot be empty")
        if self.device not in {"cpu", "cuda", "auto"}:
            raise ValueError("ASR_DEVICE must be cpu, cuda, or auto")
        if not self.compute_type:
            raise ValueError("ASR_COMPUTE_TYPE cannot be empty")
        if not self.language:
            raise ValueError("ASR_LANGUAGE cannot be empty")
        if self.beam_size <= 0:
            raise ValueError("ASR_BEAM_SIZE must be greater than zero")
        if self.cpu_threads < 0:
            raise ValueError("ASR_CPU_THREADS cannot be negative")
        if self.max_audio_bytes <= 0:
            raise ValueError("ASR_MAX_AUDIO_BYTES must be greater than zero")
        if not math.isfinite(self.min_duration_s) or self.min_duration_s <= 0:
            raise ValueError("ASR_MIN_DURATION_SECONDS must be greater than zero")
        if (
            not math.isfinite(self.max_duration_s)
            or self.max_duration_s <= self.min_duration_s
        ):
            raise ValueError(
                "ASR_MAX_DURATION_SECONDS must exceed ASR_MIN_DURATION_SECONDS"
            )
        if (
            not math.isfinite(self.low_confidence_threshold)
            or not 0 <= self.low_confidence_threshold <= 1
        ):
            raise ValueError("ASR_LOW_CONFIDENCE_THRESHOLD must be between 0 and 1")
