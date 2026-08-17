"""Validated temporary-audio lifecycle and lazy local ASR inference."""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import math
from pathlib import Path
from threading import Lock
import tempfile
import time
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .config import ASRSettings


SUPPORTED_AUDIO_TYPES: dict[str, str] = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
}

REQUIRED_MODEL_FILES = (
    "config.json",
    "model.bin",
    "tokenizer.json",
)


class ASRModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ASRStatus(ASRModel):
    backend: str
    model: str
    available: bool
    loaded: bool
    language: str
    device: str
    compute_type: str
    max_audio_bytes: int = Field(gt=0)
    max_duration_s: float = Field(gt=0)
    low_confidence_threshold: float = Field(ge=0, le=1)
    supported_mime_types: list[str]
    unavailable_reason: str | None = None


class TranscriptionResult(ASRModel):
    text: str = Field(min_length=1, max_length=8000)
    language: str
    language_probability: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    low_confidence: bool
    duration_ms: int = Field(ge=0)
    audio_bytes: int = Field(gt=0)
    asr_latency_ms: int = Field(ge=0)
    end_to_end_latency_ms: int | None = Field(default=None, ge=0)
    backend: str
    model: str
    safety_action: Literal["stop", "estop"] | None = None


@dataclass(frozen=True)
class RawTranscription:
    text: str
    language: str
    language_probability: float
    confidence: float
    duration_s: float


class SpeechTranscriber(Protocol):
    @property
    def loaded(self) -> bool: ...

    def transcribe(self, audio_path: Path) -> RawTranscription: ...


class ASRError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "details": self.details,
        }


class FasterWhisperTranscriber:
    """Load a CTranslate2 Whisper model only on the first speech request."""

    def __init__(self, settings: ASRSettings) -> None:
        self.settings = settings
        self._model: Any | None = None
        self._load_lock = Lock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def transcribe(self, audio_path: Path) -> RawTranscription:
        model = self._get_model()
        try:
            segments, info = model.transcribe(
                str(audio_path),
                language=self.settings.language,
                beam_size=self.settings.beam_size,
                temperature=0.0,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 300},
                condition_on_previous_text=False,
                initial_prompt=(
                    "手术机器人语音指令。入点，靶点，基座坐标系，X轴，Y轴，Z轴，"
                    "毫米，向上，向下，向左，向右，向前，向后，停止，急停。"
                ),
            )
            completed = list(segments)
        except Exception as error:
            raise ASRError(
                "ASR_TRANSCRIPTION_FAILED",
                f"语音转写失败：{type(error).__name__}",
                status_code=422,
            ) from error

        text = "".join(str(segment.text) for segment in completed).strip()
        if not text:
            raise ASRError(
                "ASR_NO_SPEECH",
                "未检测到清晰语音，请靠近麦克风后重试。",
                status_code=422,
            )
        confidence = _segment_confidence(completed)
        return RawTranscription(
            text=text,
            language=str(info.language or self.settings.language),
            language_probability=_bounded_probability(info.language_probability),
            confidence=confidence,
            duration_s=max(0.0, float(info.duration)),
        )

    def _get_model(self) -> Any:
        if self._model is not None:
            return self._model
        with self._load_lock:
            if self._model is not None:
                return self._model
            try:
                from faster_whisper import WhisperModel
            except ImportError as error:
                raise ASRError(
                    "ASR_DEPENDENCY_MISSING",
                    "agent-web 镜像未安装 faster-whisper。",
                    status_code=503,
                ) from error
            try:
                self._model = WhisperModel(
                    str(self.settings.model_path),
                    device=self.settings.device,
                    compute_type=self.settings.compute_type,
                    cpu_threads=self.settings.cpu_threads,
                    local_files_only=True,
                )
            except Exception as error:
                raise ASRError(
                    "ASR_MODEL_LOAD_FAILED",
                    f"本地 ASR 模型加载失败：{type(error).__name__}",
                    status_code=503,
                    details={"model_path": str(self.settings.model_path)},
                ) from error
            return self._model


class ASRService:
    def __init__(
        self,
        settings: ASRSettings,
        *,
        transcriber: SpeechTranscriber | None = None,
    ) -> None:
        settings.validate()
        self.settings = settings
        self._custom_transcriber = transcriber is not None
        self.transcriber = transcriber or FasterWhisperTranscriber(settings)
        self._inference_lock = Lock()

    def status(self) -> ASRStatus:
        reason = self._unavailable_reason()
        return ASRStatus(
            backend=self.settings.backend,
            model=self.settings.model_name,
            available=reason is None,
            loaded=self.transcriber.loaded,
            language=self.settings.language,
            device=self.settings.device,
            compute_type=self.settings.compute_type,
            max_audio_bytes=self.settings.max_audio_bytes,
            max_duration_s=self.settings.max_duration_s,
            low_confidence_threshold=self.settings.low_confidence_threshold,
            supported_mime_types=list(SUPPORTED_AUDIO_TYPES),
            unavailable_reason=reason,
        )

    def transcribe(
        self,
        audio: bytes,
        *,
        content_type: str,
        reported_duration_ms: int,
    ) -> TranscriptionResult:
        mime_type = content_type.split(";", 1)[0].strip().lower()
        suffix = SUPPORTED_AUDIO_TYPES.get(mime_type)
        if suffix is None:
            raise ASRError(
                "ASR_UNSUPPORTED_AUDIO_TYPE",
                "仅支持 WebM、Ogg、MP4/M4A、MP3 或 WAV 音频。",
                status_code=415,
                details={"content_type": mime_type or "missing"},
            )
        if not audio:
            raise ASRError("ASR_EMPTY_AUDIO", "录音内容为空。", status_code=422)
        if len(audio) > self.settings.max_audio_bytes:
            raise ASRError(
                "ASR_AUDIO_TOO_LARGE",
                "录音文件超过大小限制。",
                status_code=413,
                details={"max_audio_bytes": self.settings.max_audio_bytes},
            )
        reported_duration_s = reported_duration_ms / 1000.0
        if reported_duration_s < self.settings.min_duration_s:
            raise ASRError(
                "ASR_AUDIO_TOO_SHORT",
                "录音时间过短，请至少说满 0.25 秒。",
                status_code=422,
            )
        if reported_duration_s > self.settings.max_duration_s:
            raise ASRError(
                "ASR_AUDIO_TOO_LONG",
                "录音超过 30 秒限制。",
                status_code=413,
                details={"max_duration_s": self.settings.max_duration_s},
            )

        unavailable = self._unavailable_reason()
        if unavailable is not None:
            raise ASRError(
                "ASR_UNAVAILABLE",
                unavailable,
                status_code=503,
                details={"model_path": str(self.settings.model_path)},
            )

        started = time.monotonic()
        path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix="interns2-asr-",
                suffix=suffix,
                delete=False,
            ) as stream:
                stream.write(audio)
                path = Path(stream.name)
            with self._inference_lock:
                raw = self.transcriber.transcribe(path)
        finally:
            if path is not None:
                path.unlink(missing_ok=True)

        if raw.duration_s > self.settings.max_duration_s + 0.5:
            raise ASRError(
                "ASR_AUDIO_TOO_LONG",
                "解码后的录音超过 30 秒限制。",
                status_code=413,
                details={"decoded_duration_s": round(raw.duration_s, 3)},
            )
        confidence = _bounded_probability(raw.confidence)
        return TranscriptionResult(
            text=raw.text,
            language=raw.language,
            language_probability=_bounded_probability(raw.language_probability),
            confidence=confidence,
            low_confidence=confidence < self.settings.low_confidence_threshold,
            duration_ms=round(raw.duration_s * 1000),
            audio_bytes=len(audio),
            asr_latency_ms=round((time.monotonic() - started) * 1000),
            backend=self.settings.backend,
            model=self.settings.model_name,
        )

    def _unavailable_reason(self) -> str | None:
        if self._custom_transcriber:
            return None
        if importlib.util.find_spec("faster_whisper") is None:
            return "agent-web 镜像未安装 faster-whisper。"
        if not self.settings.model_path.is_dir():
            return "未挂载本地 ASR 模型目录。"
        missing = [
            name
            for name in REQUIRED_MODEL_FILES
            if not (self.settings.model_path / name).is_file()
        ]
        if missing:
            return f"ASR 模型目录缺少文件：{', '.join(missing)}"
        return None


def _bounded_probability(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(numeric):
        return 0.0
    return round(max(0.0, min(1.0, numeric)), 4)


def _segment_confidence(segments: list[Any]) -> float:
    if not segments:
        return 0.0
    weighted = 0.0
    total_weight = 0.0
    for segment in segments:
        duration = max(0.05, float(segment.end) - float(segment.start))
        probability = math.exp(min(0.0, float(segment.avg_logprob)))
        no_speech = _bounded_probability(getattr(segment, "no_speech_prob", 0.0))
        weighted += probability * (1.0 - no_speech) * duration
        total_weight += duration
    return _bounded_probability(weighted / total_weight if total_weight else 0.0)
