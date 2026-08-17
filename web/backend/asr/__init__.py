"""Offline speech-to-text support for the agent-web service."""

from .config import ASRSettings
from .service import (
    ASRError,
    ASRService,
    ASRStatus,
    SpeechTranscriber,
    TranscriptionResult,
)

__all__ = [
    "ASRError",
    "ASRService",
    "ASRSettings",
    "ASRStatus",
    "SpeechTranscriber",
    "TranscriptionResult",
]
