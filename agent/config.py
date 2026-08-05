"""Environment-backed configuration for the agent runtime."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _as_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {value!r}") from exc


def _as_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc


def load_environment(env_file: str | Path | None = None) -> Path:
    """Load the project .env without overriding explicitly exported variables."""

    try:
        from dotenv import load_dotenv
    except ImportError as exc:  # pragma: no cover - depends on deployment environment
        raise RuntimeError(
            "python-dotenv is not installed; run `pip install -r agent/requirements.txt`"
        ) from exc

    path = Path(env_file).expanduser().resolve() if env_file else PROJECT_ROOT / ".env"
    load_dotenv(path, override=False)
    return path


@dataclass(frozen=True)
class AgentSettings:
    """Settings for the OpenAI-compatible InternS2 inference endpoint."""

    base_url: str
    api_key: str
    model: str | None
    timeout: float
    max_retries: int
    max_tokens: int
    temperature: float
    top_p: float
    max_tool_rounds: int

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> "AgentSettings":
        load_environment(env_file)
        model = os.getenv("INTERNS2_MODEL", "").strip() or None
        settings = cls(
            base_url=os.getenv("INTERNS2_BASE_URL", "http://127.0.0.1:23333/v1").strip(),
            api_key=os.getenv("INTERNS2_API_KEY", "EMPTY").strip(),
            model=model,
            timeout=_as_float("INTERNS2_TIMEOUT", 300.0),
            max_retries=_as_int("INTERNS2_MAX_RETRIES", 2),
            max_tokens=_as_int("INTERNS2_MAX_TOKENS", 2048),
            temperature=_as_float("INTERNS2_TEMPERATURE", 0.2),
            top_p=_as_float("INTERNS2_TOP_P", 0.95),
            max_tool_rounds=_as_int("INTERNS2_MAX_TOOL_ROUNDS", 3),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not self.base_url:
            raise ValueError("INTERNS2_BASE_URL cannot be empty")
        if not self.api_key:
            raise ValueError("INTERNS2_API_KEY cannot be empty; use EMPTY for a local server")
        if self.timeout <= 0:
            raise ValueError("INTERNS2_TIMEOUT must be greater than zero")
        if self.max_retries < 0:
            raise ValueError("INTERNS2_MAX_RETRIES cannot be negative")
        if self.max_tokens <= 0:
            raise ValueError("INTERNS2_MAX_TOKENS must be greater than zero")
        if self.max_tool_rounds <= 0:
            raise ValueError("INTERNS2_MAX_TOOL_ROUNDS must be greater than zero")
