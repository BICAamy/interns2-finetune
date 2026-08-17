"""InternS2 OpenAI-compatible client for structured surgical task parsing."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import mimetypes
from pathlib import Path
from typing import Any, Callable

from surgical_contracts import (
    CommandIntent,
    CoordinateSource,
    ErrorCode,
    ParsedCommand,
)

from .config import AgentSettings
from .parsing import (
    CommandNormalizer,
    CommandParsingError,
    SUBMIT_SURGICAL_TASK_NAME,
    build_submit_surgical_task_tool,
    build_system_prompt,
)


@dataclass(frozen=True)
class ParsedCommandResponse:
    """Validated command plus non-executable model metadata."""

    command: ParsedCommand
    model: str
    tool_call_id: str | None = None

    @property
    def clarification(self) -> str | None:
        if self.command.intent == CommandIntent.CLARIFY:
            return self.command.summary
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "model": self.model,
            "parsed_command": self.command.model_dump(mode="json"),
            "clarification": self.clarification,
        }


class InternS2Agent:
    """Extract one high-level ParsedCommand from text and an optional image."""

    def __init__(
        self,
        settings: AgentSettings,
        client: Any | None = None,
        *,
        command_id_factory: Callable[[], str] | None = None,
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
        self.normalizer = CommandNormalizer(
            settings,
            command_id_factory=command_id_factory,
        )

    def _discover_model(self) -> str:
        try:
            models = self.client.models.list().data
        except Exception as exc:
            raise CommandParsingError(
                ErrorCode.MODEL_UNAVAILABLE,
                "无法查询 InternS2 模型列表；请确认 LMDeploy 服务已启动，或配置 INTERNS2_MODEL。",
            ) from exc
        if not models:
            raise CommandParsingError(
                ErrorCode.MODEL_UNAVAILABLE,
                "InternS2 服务返回了空模型列表。",
            )
        model_id = getattr(models[0], "id", None)
        if not isinstance(model_id, str) or not model_id.strip():
            raise CommandParsingError(
                ErrorCode.MODEL_UNAVAILABLE,
                "InternS2 服务返回了无效模型 ID。",
            )
        return model_id

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
        # InternS2's model card places vision content before the text prompt.
        return [
            {
                "type": "image_url",
                "image_url": {"url": InternS2Agent._image_data_url(image_path)},
            },
            {"type": "text", "text": prompt},
        ]

    def parse_command(
        self,
        prompt: str,
        image_path: str | Path | None = None,
        *,
        input_source: CoordinateSource = CoordinateSource.USER_TEXT,
    ) -> ParsedCommandResponse:
        """Call InternS2 once and validate its sole high-level tool call."""

        normalized_prompt = prompt.strip()
        if not normalized_prompt:
            raise ValueError("The user prompt cannot be empty")

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": build_system_prompt(self.settings)},
            {
                "role": "user",
                "content": self._user_content(normalized_prompt, image_path),
            },
        ]
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=[build_submit_surgical_task_tool()],
                temperature=self.settings.temperature,
                top_p=self.settings.top_p,
                max_tokens=self.settings.max_tokens,
                extra_body={"spaces_between_special_tokens": False},
            )
        except Exception as exc:
            if self._is_timeout(exc):
                raise CommandParsingError(
                    ErrorCode.MODEL_TIMEOUT,
                    "InternS2 解析请求超时，未生成任何可执行命令。",
                ) from exc
            raise CommandParsingError(
                ErrorCode.MODEL_UNAVAILABLE,
                "InternS2 解析服务调用失败，未生成任何可执行命令。",
                details={"exception_type": type(exc).__name__},
            ) from exc

        if not getattr(response, "choices", None):
            raise CommandParsingError(
                ErrorCode.MODEL_INVALID_OUTPUT,
                "InternS2 返回了空 completion choices。",
            )
        message = getattr(response.choices[0], "message", None)
        tool_calls = getattr(message, "tool_calls", None) if message is not None else None
        if not tool_calls:
            raise CommandParsingError(
                ErrorCode.MODEL_NO_TOOL_CALL,
                "InternS2 没有调用 submit_surgical_task，未生成任何可执行命令。",
            )
        if len(tool_calls) != 1:
            raise CommandParsingError(
                ErrorCode.MODEL_INVALID_OUTPUT,
                "InternS2 必须且只能返回一个 submit_surgical_task 调用。",
                details={"tool_call_count": len(tool_calls)},
            )

        tool_call = tool_calls[0]
        function = getattr(tool_call, "function", None)
        name = getattr(function, "name", None)
        if name != SUBMIT_SURGICAL_TASK_NAME:
            raise CommandParsingError(
                ErrorCode.MODEL_INVALID_OUTPUT,
                "InternS2 调用了未授权的函数。",
                details={"function_name": name},
            )
        arguments = self._decode_arguments(getattr(function, "arguments", None))
        command = self.normalizer.normalize(
            arguments,
            input_source=input_source,
            input_text=normalized_prompt,
        )
        return ParsedCommandResponse(
            command=command,
            model=self.model,
            tool_call_id=getattr(tool_call, "id", None),
        )

    # Step 7 keeps run() as a compatibility alias, but its meaning is now
    # structured parsing rather than free-form chat.
    def run(
        self,
        prompt: str,
        image_path: str | Path | None = None,
    ) -> ParsedCommandResponse:
        return self.parse_command(prompt, image_path=image_path)

    @staticmethod
    def _decode_arguments(arguments: Any) -> dict[str, Any]:
        if isinstance(arguments, dict):
            return arguments
        if not isinstance(arguments, str) or not arguments.strip():
            raise CommandParsingError(
                ErrorCode.MODEL_INVALID_OUTPUT,
                "submit_surgical_task arguments 不是有效 JSON 对象。",
            )
        try:
            decoded = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise CommandParsingError(
                ErrorCode.MODEL_INVALID_OUTPUT,
                "submit_surgical_task arguments 不是合法 JSON。",
                details={
                    "line": exc.lineno,
                    "column": exc.colno,
                    "reason": exc.msg,
                },
            ) from exc
        if not isinstance(decoded, dict):
            raise CommandParsingError(
                ErrorCode.MODEL_INVALID_OUTPUT,
                "submit_surgical_task arguments 必须是 JSON 对象。",
            )
        return decoded

    @staticmethod
    def _is_timeout(error: Exception) -> bool:
        return isinstance(error, TimeoutError) or type(error).__name__ in {
            "APITimeoutError",
            "ConnectTimeout",
            "ReadTimeout",
            "TimeoutException",
        }
