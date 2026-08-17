"""Prompt and single high-level tool exposed to InternS2."""

from __future__ import annotations

from typing import Any

from agent.config import AgentSettings


SUBMIT_SURGICAL_TASK_NAME = "submit_surgical_task"


def build_system_prompt(settings: AgentSettings) -> str:
    """Build the extraction prompt with runtime-owned defaults made explicit."""

    coordinate_default_rule = (
        "当前是 simulation 模式：用户未说明坐标单位或坐标系时，在坐标对象中省略相应字段，"
        f"且不要把它加入 missing_fields；运行时会采用页面可见的 "
        f"{settings.default_distance_unit.value} 和 "
        f"{settings.default_coordinate_frame.value} 默认值。"
        if settings.runtime_mode.value == "simulation"
        else "当前是 real 模式：用户未说明坐标单位或坐标系时必须选择 clarify，并把缺失项加入 missing_fields。"
    )
    return f"""你是手术机器人科研仿真系统中的非结构化指令解析器。
你的唯一任务是理解用户的文本和可选图像，然后恰好调用一次
`{SUBMIT_SURGICAL_TASK_NAME}`。你只做信息提取和意图分类，不执行任何动作。

必须遵守以下规则：
1. 绝对不得编造入点、靶点、距离、坐标系或单位。
2. 不能把图像中的二维像素坐标当作三维机器人坐标。图片若没有经过三维标定，
   只能用于理解语义；需要三维坐标时返回 clarify。
3. puncture 表示“准备完整穿刺任务”，必须同时有明确的入点和靶点。
4. move_to_entry 只将针尖移动到入点，只要求入点，不要求靶点。
5. move_relative 表示相对移动。第一版“上/抬高”映射为 robot_base +Z，
   “下/降低”映射为 robot_base -Z；其他含糊方向返回 clarify。相对移动必须使用
   relative_axis、relative_direction、relative_distance_mm、relative_frame 和
   relative_distance_source 这些扁平函数参数；不要生成 relative_motion 参数。
6. “一点/一些/稍微”没有明确距离时，省略 relative_distance_mm；运行时会采用配置值
   {settings.default_relative_step_mm:g} mm，不要自己猜另一个数值。
7. stop 表示停止或“不要移动”；emergency_stop 只用于明确的急停、紧急停止。
8. 不能生成关节角、速度轨迹、力矩、逆运动学结果或穿刺轨迹。
9. 坐标数值缺少单位或坐标系时不要编造。{coordinate_default_rule}
10. 多组坐标只有在“入点/靶点”标签和 XYZ 顺序都明确时才能提取；顺序含糊、
    内容矛盾、字段不完整或与机械臂无关时必须选择 clarify。XYZ 顺序或坐标标签
    不明确时，在 missing_fields 中统一使用 coordinate_order。
11. clarify 必须在 missing_fields 中列出要补充或确认的字段，并在 summary 中给出
    清楚、简短的中文问题。停止和急停不需要坐标。
12. 所有显式距离换算成毫米。坐标来源按实际情况填写 user_text、asr_text、
    image_annotation、structured_data 或 gesture。
13. 不得调用任何其他函数，不得返回底层工具名或服务地址。
14. 用户明确要求穿刺、进针或针刺时，不得改写成 move_to_entry；如果缺少靶点，
    必须选择 clarify，并在 missing_fields 中加入 target_point。

当前运行模式：{settings.runtime_mode.value}
默认距离单位：{settings.default_distance_unit.value}
默认坐标系：{settings.default_coordinate_frame.value}
默认模糊相对步长：{settings.default_relative_step_mm:g} mm
"""


def _point_schema(description: str) -> dict[str, Any]:
    return {
        "anyOf": [
            {
                "type": "object",
                "description": description,
                "properties": {
                    "x": {"type": "number", "description": "X coordinate"},
                    "y": {"type": "number", "description": "Y coordinate"},
                    "z": {"type": "number", "description": "Z coordinate"},
                    "unit": {
                        "type": "string",
                        "enum": ["mm"],
                        "description": "Always millimetres; omit when the user gave no unit",
                    },
                    "frame": {
                        "type": "string",
                        "enum": [
                            "robot_base",
                            "tool_center_point",
                            "needle_tip",
                            "simulation_world",
                            "scene_camera",
                        ],
                        "description": "Omit when the user gave no coordinate frame",
                    },
                    "source": {
                        "type": "string",
                        "enum": [
                            "user_text",
                            "asr_text",
                            "structured_data",
                            "image_annotation",
                            "gesture",
                        ],
                    },
                },
                "required": ["x", "y", "z"],
                "additionalProperties": False,
            },
            {"type": "null"},
        ]
    }


def build_submit_surgical_task_tool() -> dict[str, Any]:
    """Return a model-friendly schema; command_id is deliberately runtime-owned."""

    return {
        "type": "function",
        "function": {
            "name": SUBMIT_SURGICAL_TASK_NAME,
            "description": (
                "Submit exactly one parsed high-level surgical robot task. This function "
                "only describes intent and coordinates; it never moves a robot."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "enum": [
                            "puncture",
                            "move_to_entry",
                            "move_relative",
                            "stop",
                            "emergency_stop",
                            "clarify",
                        ],
                    },
                    "entry_point": _point_schema("Three-dimensional puncture entry point"),
                    "target_point": _point_schema("Three-dimensional puncture target point"),
                    "relative_axis": {
                        "type": "string",
                        "enum": ["x", "y", "z"],
                        "description": "Axis for move_relative; omit for other intents",
                    },
                    "relative_direction": {
                        "type": "string",
                        "enum": ["positive", "negative"],
                        "description": "Direction for move_relative; omit for other intents",
                    },
                    "relative_distance_mm": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                        "description": (
                            "Positive distance for move_relative in mm; omit for vague "
                            "words such as 一点 or 稍微, and omit for other intents"
                        ),
                    },
                    "relative_frame": {
                        "type": "string",
                        "enum": ["robot_base"],
                        "description": (
                            "Reference frame for move_relative; omit when not explicit "
                            "or for other intents"
                        ),
                    },
                    "relative_distance_source": {
                        "type": "string",
                        "enum": ["user_provided", "configured_default"],
                        "description": "Distance source for move_relative; omit otherwise",
                    },
                    "missing_fields": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "intent",
                                "entry_point",
                                "target_point",
                                "relative_motion",
                                "coordinate_order",
                                "entry_point.x",
                                "entry_point.y",
                                "entry_point.z",
                                "entry_point.unit",
                                "entry_point.frame",
                                "entry_point.coordinate_transform",
                                "target_point.x",
                                "target_point.y",
                                "target_point.z",
                                "target_point.unit",
                                "target_point.frame",
                                "target_point.coordinate_transform",
                                "relative_motion.axis",
                                "relative_motion.direction",
                                "relative_motion.frame",
                                "entry_point_3d",
                                "target_point_3d",
                            ],
                        },
                        "description": "Fields needing clarification; empty for executable intents",
                    },
                    "needs_confirmation": {"type": "boolean"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "summary": {
                        "type": "string",
                        "description": "Chinese task summary or clarification question",
                    },
                },
                "required": [
                    "intent",
                    "entry_point",
                    "target_point",
                    "missing_fields",
                    "needs_confirmation",
                    "confidence",
                    "summary",
                ],
                "additionalProperties": False,
            },
        },
    }
