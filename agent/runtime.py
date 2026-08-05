"""Tool-calling runtime that uses InternS2 as the user-facing base model."""

from __future__ import annotations

import base64
import json
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import AgentSettings
from .tools.NavGPT.nav_src.nav_tool import NAVGPT_TOOL_SCHEMA, NavGPTTool


SYSTEM_PROMPT = """You are an embodied navigation assistant based on InternS2.
The user provides an image and a navigation request. Inspect the image carefully.
When the request requires navigation planning or a next movement decision, call the
navgpt_navigation tool. Pass it a grounded textual observation of the image and the
user's actual instruction. Never invent simulator viewpoint IDs: if no candidate IDs
were supplied by the user or environment, pass an empty navigable_viewpoints list.
After receiving the tool result, explain the recommended action clearly and mention
any uncertainty or missing environmental information. Answer directly without
describing the internal tool protocol.
"""


@dataclass
class ToolEvent:
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "arguments": self.arguments,
            "result": self.result,
        }


@dataclass
class InvocationResult:
    answer: str
    model: str
    tool_events: list[ToolEvent] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "model": self.model,
            "tool_events": [event.as_dict() for event in self.tool_events],
        }


class InternS2NavigationAgent:
    """Run an InternS2 -> NavGPT -> InternS2 tool-calling conversation."""

    def __init__(
        self,
        settings: AgentSettings,
        navgpt_tool: NavGPTTool | None = None,
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
        self.navgpt_tool = navgpt_tool or NavGPTTool.from_env()
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
    def _assistant_message(message: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "role": "assistant",
            "content": message.content or "",
        }
        tool_calls = getattr(message, "tool_calls", None) or []
        if tool_calls:
            payload["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in tool_calls
            ]
        reasoning_content = getattr(message, "reasoning_content", None)
        if reasoning_content:
            payload["reasoning_content"] = reasoning_content
        return payload

    def _execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name != NAVGPT_TOOL_SCHEMA["function"]["name"]:
            return {"ok": False, "error": f"Unknown tool: {name}"}
        try:
            result = self.navgpt_tool.navigate(**arguments)
            return {"ok": True, **result}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def run(self, image_path: str | Path, prompt: str) -> InvocationResult:
        if not prompt.strip():
            raise ValueError("The user prompt cannot be empty")

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": self._image_data_url(image_path)},
                    },
                    {"type": "text", "text": prompt.strip()},
                ],
            },
        ]
        tool_events: list[ToolEvent] = []

        for _ in range(self.settings.max_tool_rounds + 1):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=[NAVGPT_TOOL_SCHEMA],
                tool_choice="auto",
                temperature=self.settings.temperature,
                top_p=self.settings.top_p,
                max_tokens=self.settings.max_tokens,
                extra_body={"spaces_between_special_tokens": False},
            )
            if not response.choices:
                raise RuntimeError("InternS2 returned no completion choices")

            message = response.choices[0].message
            tool_calls = getattr(message, "tool_calls", None) or []
            if not tool_calls:
                answer = (message.content or "").strip()
                if not answer:
                    raise RuntimeError("InternS2 returned neither text nor a tool call")
                return InvocationResult(answer=answer, model=self.model, tool_events=tool_events)

            if len(tool_events) >= self.settings.max_tool_rounds:
                raise RuntimeError(
                    f"InternS2 exceeded INTERNS2_MAX_TOOL_ROUNDS={self.settings.max_tool_rounds}"
                )

            messages.append(self._assistant_message(message))
            for call in tool_calls:
                try:
                    arguments = json.loads(call.function.arguments or "{}")
                    if not isinstance(arguments, dict):
                        raise ValueError("tool arguments must be a JSON object")
                except (json.JSONDecodeError, ValueError) as exc:
                    arguments = {}
                    result = {"ok": False, "error": f"Invalid tool arguments: {exc}"}
                else:
                    result = self._execute_tool(call.function.name, arguments)

                tool_events.append(
                    ToolEvent(name=call.function.name, arguments=arguments, result=result)
                )
                messages.append(
                    {
                        "role": "tool",
                        "name": call.function.name,
                        "tool_call_id": call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

        raise RuntimeError("Agent loop ended without a final answer")
