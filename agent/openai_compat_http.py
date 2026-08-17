"""Small OpenAI-compatible HTTP facade for the standalone agent-web image.

The LMDeploy container already has the official OpenAI SDK.  The separate
agent-web container only needs model listing and chat completions, so this
facade keeps its offline Python image small while preserving InternS2Agent's
tested client interface.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx

from .config import AgentSettings


def _namespace(value: Any) -> Any:
    if isinstance(value, dict):
        return SimpleNamespace(**{key: _namespace(item) for key, item in value.items()})
    if isinstance(value, list):
        return [_namespace(item) for item in value]
    return value


class _ModelsResource:
    def __init__(self, owner: "OpenAICompatibleHTTPClient") -> None:
        self._owner = owner

    def list(self) -> Any:
        return _namespace(self._owner._request("GET", "models"))


class _CompletionsResource:
    def __init__(self, owner: "OpenAICompatibleHTTPClient") -> None:
        self._owner = owner

    def create(self, **kwargs: Any) -> Any:
        extra_body = kwargs.pop("extra_body", None)
        payload = dict(kwargs)
        if isinstance(extra_body, dict):
            payload.update(extra_body)
        return _namespace(
            self._owner._request("POST", "chat/completions", json=payload)
        )


class _ChatResource:
    def __init__(self, owner: "OpenAICompatibleHTTPClient") -> None:
        self.completions = _CompletionsResource(owner)


class OpenAICompatibleHTTPClient:
    """Expose the subset of the OpenAI SDK used by :class:`InternS2Agent`."""

    def __init__(
        self,
        settings: AgentSettings,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        # Keep a trailing slash so httpx resolves relative resources below
        # an OpenAI-compatible prefix such as ``/v1/`` rather than at root.
        self.base_url = settings.base_url.rstrip("/") + "/"
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=self.base_url,
            timeout=settings.timeout,
            headers={
                "Authorization": f"Bearer {settings.api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            trust_env=False,
        )
        self.models = _ModelsResource(self)
        self.chat = _ChatResource(self)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self._client.request(method, path, **kwargs)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"InternS2 returned non-object JSON for {path}")
        return payload
