"""OpenAI-compatible client for the InternS2 base model.

The surgical task schemas and robot/planner tools are introduced in the next
implementation step.  This module deliberately contains no legacy navigation
tool and remains useful as a small, testable InternS2 client during migration.
"""

from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import AgentSettings


SYSTEM_PROMPT = """You are InternS2, the multimodal base model for a surgical
robotics research assistant. Respond to the user's text and optional image directly.
Do not claim that a robot moved, that a path was planned, or that a puncture was
performed: no robot or puncture-planning tool is connected in this migration stage.
"""


@dataclass
class ModelResponse:
    """Text returned by InternS2 and the model ID that produced it."""

    answer: str
    model: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "model": self.model,
        }


class InternS2Agent:
    """Send text and an optional image to an InternS2 inference endpoint."""

    def __init__(
        self,
        settings: AgentSettings,
        client: Any | None = None,
    ) -> None:
        self.settings = settings
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - deployment dependent
                raise RuntimeError(
                    "openai is not installed; run `pip install -r agent/requirements.txt`"
                ) from exc
            client = OpenAI(
                api_key=settings.api_key,
                base_url=settings.base_url,
                timeout=settings.timeout,
                max_retries=settings.max_retries,
            )
        self.client = client
        self.model = settings.model or self._discover_model()

    def _discover_model(self) -> str:
        try:
            models = self.client.models.list().data
        except Exception as exc:
            raise RuntimeError(
                "Could not query the InternS2 endpoint. Start the LMDeploy API server "
                "or set INTERNS2_MODEL explicitly in .env."
            ) from exc
        if not models:
            raise RuntimeError("The InternS2 endpoint returned an empty model list")
        return models[0].id

    @staticmethod
    def _image_data_url(image_path: str | Path) -> str:
        path = Path(image_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Image does not exist: {path}")
        mime_type, _ = mimetypes.guess_type(path.name)
        if not mime_type or not mime_type.startswith("image/"):
            raise ValueError(f"Unsupported image file type: {path.suffix or '<none>'}")
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    @staticmethod
    def _user_content(prompt: str, image_path: str | Path | None) -> Any:
        if image_path is None:
            return prompt
        return [
            {
                "type": "image_url",
                "image_url": {"url": InternS2Agent._image_data_url(image_path)},
            },
            {"type": "text", "text": prompt},
        ]

    def run(
        self,
        prompt: str,
        image_path: str | Path | None = None,
    ) -> ModelResponse:
        if not prompt.strip():
            raise ValueError("The user prompt cannot be empty")

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": self._user_content(prompt.strip(), image_path),
            },
        ]
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.settings.temperature,
            top_p=self.settings.top_p,
            max_tokens=self.settings.max_tokens,
            extra_body={"spaces_between_special_tokens": False},
        )
        if not response.choices:
            raise RuntimeError("InternS2 returned no completion choices")

        answer = (response.choices[0].message.content or "").strip()
        if not answer:
            raise RuntimeError("InternS2 returned an empty response")
        return ModelResponse(answer=answer, model=self.model)
