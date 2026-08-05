"""Legacy LangChain adapter backed by the modern OpenAI-compatible chat API."""

from __future__ import annotations

import os
from typing import Any, List, Mapping, Optional

from langchain.callbacks.manager import CallbackManagerForLLMRun
from langchain.llms.base import LLM
from pydantic import PrivateAttr

try:  # Supports both `python NavGPT.py` and package imports.
    from ..llm_client import OpenAICompatibleChatClient
except ImportError:  # pragma: no cover - legacy script execution path
    from llm_client import OpenAICompatibleChatClient


class OpenAICompatibleLLM(LLM):
    """Expose a DeepSeek-compatible chat endpoint as a LangChain 0.0.x LLM."""

    model_name: str
    base_url: str
    api_key_env: str = "DEEPSEEK_API_KEY"
    temperature: float = 0.0
    max_tokens: int = 1200
    timeout: float = 120.0
    max_retries: int = 2
    _chat_client: Any = PrivateAttr()

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        api_key = os.getenv(self.api_key_env, "").strip()
        self._chat_client = OpenAICompatibleChatClient(
            api_key=api_key,
            base_url=self.base_url,
            model=self.model_name,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
            max_retries=self.max_retries,
        )

    @classmethod
    def from_config(cls, config: Any) -> "OpenAICompatibleLLM":
        return cls(
            model_name=config.llm_model_name,
            base_url=config.llm_base_url,
            api_key_env=config.llm_api_key_env,
            temperature=config.temperature,
            max_tokens=config.llm_max_tokens,
            timeout=config.llm_timeout,
            max_retries=config.llm_max_retries,
        )

    @classmethod
    def from_env(cls, temperature: float = 0.0) -> "OpenAICompatibleLLM":
        return cls(
            model_name=os.getenv("DEEPSEEK_MODEL", ""),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            api_key_env="DEEPSEEK_API_KEY",
            temperature=temperature,
            max_tokens=int(os.getenv("DEEPSEEK_MAX_TOKENS", "1200")),
            timeout=float(os.getenv("DEEPSEEK_TIMEOUT", "120")),
            max_retries=int(os.getenv("DEEPSEEK_MAX_RETRIES", "2")),
        )

    @property
    def _llm_type(self) -> str:
        return "openai_compatible_chat"

    def _call(
        self,
        prompt: str,
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> str:
        return self._chat_client.chat(
            [
                {
                    "role": "system",
                    "content": "You are the language reasoning component of NavGPT.",
                },
                {"role": "user", "content": prompt},
            ],
            stop=stop,
        )

    @property
    def _identifying_params(self) -> Mapping[str, Any]:
        return {
            "model_name": self.model_name,
            "base_url": self.base_url,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
