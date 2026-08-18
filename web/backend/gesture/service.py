"""InternS2-backed fixed gesture recognition and deterministic mapping."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
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
5. forward：食指直接指向摄像头。
6. backward：大拇指指向操作者自己的胸口。
7. stop：拇指和食指组成清晰圆圈。
8. estop：五指张开且掌心正对摄像头。

规则：
- 输入图片是原始未镜像摄像头帧；不要根据网页镜像预览反转左右。
- 只能从上述八种手势、none、uncertain 中选择一个。
- 没有检测到手时选择 none，hand_detected=false。
- 有手但无法明确匹配一个协议手势时选择 uncertain。
- 不要把普通 OK、比心、握拳等动作强行解释成协议手势。
- stop 与 estop 是安全指令，只有形态明确匹配时才能输出。
- confidence 表示你对固定协议分类的置信度，范围 0~1。
- 必须且只能调用 classify_fixed_gesture 一次，不输出机械臂坐标、关节角或控制量。
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


@dataclass(frozen=True)
class GestureSettings:
    minimum_confidence: float = 0.85
    safety_minimum_confidence: float = 0.80
    cooldown_s: float = 1.0
    voice_conflict_window_s: float = 1.5
    maximum_frame_age_s: float = 2.0


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
                tools=[build_gesture_tool()],
                temperature=0.0,
                top_p=0.95,
                max_tokens=256,
                extra_body={"spaces_between_special_tokens": False},
            )
        except Exception as error:
            raise GestureRecognitionError(
                f"InternS2 gesture recognition failed: {type(error).__name__}"
            ) from error

        choices = getattr(response, "choices", None)
        if not choices:
            raise GestureRecognitionError("InternS2 returned no gesture completion choice")
        message = getattr(choices[0], "message", None)
        tool_calls = getattr(message, "tool_calls", None) if message is not None else None
        if not tool_calls or len(tool_calls) != 1:
            raise GestureRecognitionError(
                "InternS2 must return exactly one classify_fixed_gesture tool call"
            )
        tool_call = tool_calls[0]
        function = getattr(tool_call, "function", None)
        if getattr(function, "name", None) != GESTURE_TOOL_NAME:
            raise GestureRecognitionError("InternS2 returned an unauthorized gesture tool")
        arguments = getattr(function, "arguments", None)
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError as error:
                raise GestureRecognitionError("gesture tool arguments are not valid JSON") from error
        if not isinstance(arguments, dict):
            raise GestureRecognitionError("gesture tool arguments must be a JSON object")
        try:
            gesture = GestureName(arguments["gesture"])
            confidence = float(arguments["confidence"])
            hand_detected = bool(arguments["hand_detected"])
        except (KeyError, TypeError, ValueError) as error:
            raise GestureRecognitionError("gesture tool arguments failed validation") from error
        if not 0.0 <= confidence <= 1.0:
            raise GestureRecognitionError("gesture confidence must be between 0 and 1")
        if gesture == GestureName.NONE:
            hand_detected = False
        return GestureRecognition(
            gesture=gesture,
            confidence=confidence,
            hand_detected=hand_detected,
            model=self.model,
            latency_ms=max(0, round((time.monotonic() - started) * 1000)),
            tool_call_id=getattr(tool_call, "id", None),
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
