from __future__ import annotations

from pathlib import Path

import pytest

from web.backend.asr import ASRError, ASRService, ASRSettings
from web.backend.asr.service import RawTranscription


class RecordingTranscriber:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.paths: list[Path] = []

    @property
    def loaded(self) -> bool:
        return True

    def transcribe(self, audio_path: Path) -> RawTranscription:
        assert audio_path.read_bytes() == b"voice-audio"
        self.paths.append(audio_path)
        if self.fail:
            raise RuntimeError("inference failed")
        return RawTranscription(
            text="入点为X二十Y三十五Z八十毫米",
            language="zh",
            language_probability=0.98,
            confidence=0.61,
            duration_s=1.2,
        )


def test_asr_service_returns_bounded_metadata_and_deletes_temporary_audio():
    transcriber = RecordingTranscriber()
    service = ASRService(
        ASRSettings(low_confidence_threshold=0.65),
        transcriber=transcriber,
    )
    result = service.transcribe(
        b"voice-audio",
        content_type="audio/webm;codecs=opus",
        reported_duration_ms=1200,
    )
    assert result.text.startswith("入点")
    assert result.language == "zh"
    assert result.confidence == 0.61
    assert result.low_confidence is True
    assert result.duration_ms == 1200
    assert result.audio_bytes == len(b"voice-audio")
    assert result.asr_latency_ms >= 0
    assert transcriber.paths and not transcriber.paths[0].exists()


def test_temporary_audio_is_deleted_when_transcriber_fails():
    transcriber = RecordingTranscriber(fail=True)
    service = ASRService(ASRSettings(), transcriber=transcriber)
    with pytest.raises(RuntimeError, match="inference failed"):
        service.transcribe(
            b"voice-audio",
            content_type="audio/wav",
            reported_duration_ms=1200,
        )
    assert transcriber.paths and not transcriber.paths[0].exists()


@pytest.mark.parametrize(
    ("content_type", "duration_ms", "expected_code"),
    [
        ("text/plain", 1000, "ASR_UNSUPPORTED_AUDIO_TYPE"),
        ("audio/webm", 100, "ASR_AUDIO_TOO_SHORT"),
        ("audio/webm", 31_000, "ASR_AUDIO_TOO_LONG"),
    ],
)
def test_invalid_audio_is_rejected_before_inference(
    content_type: str,
    duration_ms: int,
    expected_code: str,
):
    transcriber = RecordingTranscriber()
    service = ASRService(ASRSettings(), transcriber=transcriber)
    with pytest.raises(ASRError) as caught:
        service.transcribe(
            b"voice-audio",
            content_type=content_type,
            reported_duration_ms=duration_ms,
        )
    assert caught.value.code == expected_code
    assert transcriber.paths == []


def test_asr_settings_reject_unsafe_or_unbounded_values():
    with pytest.raises(ValueError, match="ASR_BACKEND"):
        ASRSettings(backend="remote-api").validate()
    with pytest.raises(ValueError, match="ASR_MAX_DURATION_SECONDS"):
        ASRSettings(max_duration_s=0.2).validate()
    with pytest.raises(ValueError, match="ASR_LOW_CONFIDENCE_THRESHOLD"):
        ASRSettings(low_confidence_threshold=1.2).validate()
