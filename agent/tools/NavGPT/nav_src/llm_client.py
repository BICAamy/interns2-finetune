"""Small OpenAI-compatible chat client shared by NavGPT integrations."""

from __future__ import annotations

from typing import Any


class OpenAICompatibleChatClient:
    """Call DeepSeek or another service that implements OpenAI chat completions."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 1200,
        timeout: float = 120.0,
        max_retries: int = 2,
        client: Any | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY is missing or empty")
        if not base_url:
            raise ValueError("DEEPSEEK_BASE_URL is missing or empty")
        if not model:
            raise ValueError("DEEPSEEK_MODEL is missing or empty")

        if client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - deployment dependent
                raise RuntimeError(
                    "openai is not installed; run `pip install -r agent/requirements.txt`"
                ) from exc
            client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=timeout,
                max_retries=max_retries,
            )

        self.client = client
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        stop: list[str] | None = None,
        json_mode: bool = False,
    ) -> str:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        if stop:
            request["stop"] = stop
        if json_mode:
            request["response_format"] = {"type": "json_object"}

        response = self.client.chat.completions.create(**request)
        if not response.choices:
            raise RuntimeError("The DeepSeek-compatible endpoint returned no choices")
        content = response.choices[0].message.content
        if not content or not content.strip():
            raise RuntimeError("The DeepSeek-compatible endpoint returned empty content")
        return content.strip()

