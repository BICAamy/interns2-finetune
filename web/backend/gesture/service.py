"""InternS2-backed fixed gesture recognition and deterministic mapping."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import time
from typing import Any

from surgical_contracts import (
    Axis,
    CommandIntent,
    CoordinateFrame,
    Direction,
    DistanceSource,
    ParsedCommand,
    RelativeMotion,
)

from agent.config import AgentSettings

from .models import GestureName, GestureRecognition


GESTURE_TOOL_NAME = "classify_fixed_gesture"

_GESTURE_SYSTEM_PROMPT = """你是手术机器人科研仿真系统中的固定手势分类器。
你只负责判断摄像头图片里的操作者是否明确做出了以下一个固定手势，不执行任何动作。

手势协议采用“操作者自身视角”，不是屏幕镜像视角：
1. up：食指向上。
2. down：食指向下。
3. left：食指指向操作者自己的左侧。
4. right：食指指向操作者自己的右侧。
5. forward：握拳，其余手指收拢，大拇指明显向上，即 Thumbs Up（👍）；不要因为拇指朝上而分类为 up，up 必须是食指向上。
6. backward：握拳，其余手指收拢，大拇指明显向下，即 Thumbs Down（👎）；不要因为拇指朝下而分类为 down，down 必须是食指向下。
7. stop：拇指和食指组成清晰圆圈；即使这个形态在日常语境中类似 OK，本系统也固定解释为 stop。
8. estop：五指张开且掌心正对摄像头。

规则：
- 输入图片是原始未镜像摄像头帧；不要根据网页镜像预览反转左右。
- 只能从上述八种手势、none、uncertain 中选择一个。
- 没有检测到手时选择 none。
- 有手但无法明确匹配一个协议手势时选择 uncertain。
- 不要把比心、握拳或其他未明确匹配协议形态的动作强行解释成协议手势。
- stop 与 estop 是安全指令，只有形态明确匹配时才能输出。
- confidence 表示你对固定协议分类的置信度，范围 0~1。
- 最终只输出一个符合给定 JSON Schema 的 JSON 对象，不输出解释、Markdown 或其他文本。
"""


def build_gesture_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": GESTURE_TOOL_NAME,
            "description": "Classify exactly one fixed operator-view gesture from a camera frame.",
            "parameters": {
                "type": "object",
                "properties": {
                    "gesture": {
                        "type": "string",
                        "enum": [gesture.value for gesture in GestureName],
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                    },
                    "hand_detected": {"type": "boolean"},
                },
                "required": ["gesture", "confidence", "hand_detected"],
                "additionalProperties": False,
            },
        },
    }


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()
    return default if not value else float(value)


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    return default if not value else int(value)


@dataclass(frozen=True)
class GestureSettings:
    minimum_confidence: float = 0.85
    safety_minimum_confidence: float = 0.80
    stable_frames: int = 2
    cooldown_s: float = 1.0
    voice_conflict_window_s: float = 1.5

    @classmethod
    def from_env(cls) -> "GestureSettings":
        settings = cls(
            minimum_confidence=_float_env("GESTURE_MIN_CONFIDENCE", 0.85),
            safety_minimum_confidence=_float_env(
                "GESTURE_SAFETY_MIN_CONFIDENCE", 0.80
            ),
            stable_frames=_int_env("GESTURE_STABLE_FRAMES", 2),
            cooldown_s=_float_env("GESTURE_COOLDOWN_SECONDS", 1.0),
            voice_conflict_window_s=_float_env(
                "GESTURE_VOICE_CONFLICT_WINDOW_SECONDS", 1.5
            ),
        )
        if not 0.0 <= settings.minimum_confidence <= 1.0:
            raise ValueError("GESTURE_MIN_CONFIDENCE must be between 0 and 1")
        if not 0.0 <= settings.safety_minimum_confidence <= 1.0:
            raise ValueError("GESTURE_SAFETY_MIN_CONFIDENCE must be between 0 and 1")
        if settings.stable_frames < 1:
            raise ValueError("GESTURE_STABLE_FRAMES must be at least 1")
        if settings.cooldown_s < 0:
            raise ValueError("GESTURE_COOLDOWN_SECONDS cannot be negative")
        if settings.voice_conflict_window_s < 0:
            raise ValueError("GESTURE_VOICE_CONFLICT_WINDOW_SECONDS cannot be negative")
        return settings


class GestureRecognitionError(RuntimeError):
    pass


class InternS2GestureRecognizer:
    """Call the already deployed InternS2 VLM once for each sampled frame."""

    def __init__(
        self,
        settings: AgentSettings,
        client: Any,
        *,
        model: str,
    ) -> None:
        self.settings = settings
        self.client = client
        self.model = model

    def recognize(self, image_data_url: str) -> GestureRecognition:
        started = time.monotonic()
        messages = [
            {"role": "system", "content": _GESTURE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                    {
                        "type": "text",
                        "text": "请按固定手势协议判断这一个摄像头帧。",
                    },
                ],
            },
        ]
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.0,
                top_p=0.95,
                max_tokens=128,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "fixed_gesture",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "gesture": {
                                    "type": "string",
                                    "enum": [gesture.value for gesture in GestureName],
                                },
                                "confidence": {
                                    "type": "number",
                                    "minimum": 0,
                                    "maximum": 1,
                                },
                            },
                            "required": ["gesture", "confidence"],
                            "additionalProperties": False,
                        },
                    },
                },
                extra_body={
                    "spaces_between_special_tokens": False,
                    "chat_template_kwargs": {
                        "enable_thinking": False,
                    },
                },
            )
        except Exception as error:
            raise GestureRecognitionError(
                f"InternS2 gesture recognition failed: {type(error).__name__}"
            ) from error
        choice0 = response.choices[0] if getattr(response, "choices", None) else None
        message0 = getattr(choice0, "message", None)

        print("\n========== STEP14 GESTURE DEBUG ==========", flush=True)
        print(
            "finish_reason =",
            repr(getattr(choice0, "finish_reason", None)),
            flush=True,
        )
        print(
            "content =",
            repr(getattr(message0, "content", None)),
            flush=True,
        )
        print(
            "reasoning_content =",
            repr(getattr(message0, "reasoning_content", None)),
            flush=True,
        )
        print(
            "tool_calls =",
            repr(getattr(message0, "tool_calls", None)),
            flush=True,
        )
        print("========== END GESTURE DEBUG ==========\n", flush=True)
        choices = getattr(response, "choices", None)
        if not choices:
            raise GestureRecognitionError(
                "InternS2 returned no gesture completion choice"
            )

        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None) if message is not None else None

        if not isinstance(content, str) or not content.strip():
            raise GestureRecognitionError(
                "InternS2 returned empty gesture JSON"
            )

        try:
            arguments = json.loads(content)
        except json.JSONDecodeError as error:
            raise GestureRecognitionError(
                "gesture response is not valid JSON"
            ) from error

        if not isinstance(arguments, dict):
            raise GestureRecognitionError(
                "gesture response must be a JSON object"
            )
        print("STEP14 parsed arguments =", repr(arguments), flush=True)
        try:
            gesture = GestureName(arguments["gesture"])
            confidence = float(arguments["confidence"])
        except (KeyError, TypeError, ValueError) as error:
            raise GestureRecognitionError(
                "gesture response failed validation"
            ) from error

        if not 0.0 <= confidence <= 1.0:
            raise GestureRecognitionError(
                "gesture confidence must be between 0 and 1"
            )

        hand_detected = gesture != GestureName.NONE

        return GestureRecognition(
            gesture=gesture,
            confidence=confidence,
            hand_detected=hand_detected,
            model=self.model,
            latency_ms=max(0, round((time.monotonic() - started) * 1000)),
            tool_call_id=None,
        )


def gesture_to_command(
    gesture: GestureName,
    *,
    distance_mm: float,
    command_id: str,
) -> ParsedCommand | None:
    """Map operator-view semantics to the simulation robot_base frame.

    The Step 12 canonical front view looks from robot_base -Y toward +Y, with
    screen/operator right aligned to +X and world up aligned to +Z. Therefore
    the simulation mapping is deterministic: left/right -> -/+X,
    forward/backward -> +/-Y, up/down -> +/-Z.
    """

    if gesture == GestureName.STOP:
        return ParsedCommand(command_id=command_id, intent=CommandIntent.STOP)
    if gesture == GestureName.ESTOP:
        return ParsedCommand(command_id=command_id, intent=CommandIntent.EMERGENCY_STOP)

    directions: dict[GestureName, tuple[Axis, Direction]] = {
        GestureName.UP: (Axis.Z, Direction.POSITIVE),
        GestureName.DOWN: (Axis.Z, Direction.NEGATIVE),
        GestureName.LEFT: (Axis.X, Direction.NEGATIVE),
        GestureName.RIGHT: (Axis.X, Direction.POSITIVE),
        GestureName.FORWARD: (Axis.Y, Direction.POSITIVE),
        GestureName.BACKWARD: (Axis.Y, Direction.NEGATIVE),
    }
    selected = directions.get(gesture)
    if selected is None:
        return None
    axis, direction = selected
    motion = RelativeMotion(
        axis=axis,
        direction=direction,
        distance_mm=distance_mm,
        frame=CoordinateFrame.ROBOT_BASE,
        distance_source=DistanceSource.CONFIGURED_DEFAULT,
    )
    return ParsedCommand(
        command_id=command_id,
        intent=CommandIntent.MOVE_RELATIVE,
        relative_motion=motion,
        needs_confirmation=True,
        confidence=1.0,
        summary=f"手势相对移动：{gesture.value}，{distance_mm:g} mm",
    )
