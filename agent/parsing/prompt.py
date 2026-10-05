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
4. 所有机械臂运动都使用 move_sequence，即使只有一个动作也必须只生成一个 motion_steps
   元素；不得使用 move_relative 或 move_to_entry。穿刺仍使用 puncture，上层将在执行时把
   “移动到入点”编译成只有一个 cartesian_absolute 步骤的 MotionSequence。
5. 相对笛卡尔移动使用 cartesian_relative。自然方向词固定按照 robot_base 坐标系映射：
   “前/向前/前进” = +X，
   “后/向后/后退” = -X，
   “左/向左” = +Y，
   “右/向右” = -Y，
   “上/向上/抬高” = +Z，
   “下/向下/降低” = -Z。
   这些方向词已经由系统明确定义，不得因为用户没有显式说 X/Y/Z 而返回 clarify。
   只有用户表达本身确实无法确定方向时才返回 clarify。
   单轴相对移动在步骤中填写 axis、direction、distance_mm。两个或三个轴同时移动时，
   使用 delta_mm=[dX,dY,dZ]，各分量保留正负号，未移动的轴填 0。
6. 相对移动距离规则：
   - 明确距离填写 distance_mm，value_source=user_provided。
   - “一点/一些/稍微”省略 distance_mm，value_source=configured_default；运行时采用
     {settings.default_relative_step_mm:g} mm，不要自行猜测其他距离。
   - 只有方向但没有距离或模糊距离词时选择 clarify，missing_fields 加 motion_sequence。
   - “快速”“慢速”“最大速度”等速度描述不能替代移动距离，也不得据此自行推断 relative_distance_mm。
7. 绝对笛卡尔位置使用 cartesian_absolute，target_position_mm=[X,Y,Z]，frame=robot_base；
   执行该步骤时保持当时实际 TCP 姿态不变。
8. 相对关节旋转使用 joint_relative。“左转/向左转/增加”是正角度，
   “右转/向右转/减少”是负角度。
   - 用户未指定关节时 joint_index 填 {settings.default_rotation_joint_index}，即配置的
     J{settings.default_rotation_joint_index}；明确指定 J1～J6 时使用对应编号。
   - “转动一点/一些/稍微”省略 rotation_deg，并把 value_source 设为 configured_default；
     运行时使用 {settings.default_relative_rotation_deg:g} 度。
9. 绝对关节角使用 joint_absolute；“J3 到 30 度”填写 joint_index=3、
   target_angle_deg=30，表示控制器关节坐标中的绝对目标角，不是增量。
10. TCP 相对姿态使用 tcp_rotation_relative；必须明确 Base RPY 的 X/Y/Z 轴，填写 axis、
    direction、rotation_deg。它只增减该 RPY 分量，执行时保持实际 XYZ 和另外两个 RPY 分量。
11. TCP 绝对姿态使用 tcp_rotation_absolute；必须明确 Base RPY 的 X/Y/Z 轴，填写 axis、
    target_angle_deg。它只设置该 RPY 分量，执行时保持实际 XYZ 和另外两个 RPY 分量。
    “TCP 转到 30 度”若没有说明 Base X/Y/Z 轴，必须 clarify，missing_fields 加
    motion_sequence.rotation_axis，不能猜测。
12. 多动作必须按原始先后顺序填写 motion_steps，不能合并、重排或遗漏。
13. stop 表示停止或“不要移动”；emergency_stop 只用于明确的急停、紧急停止。
14. 不得生成速度轨迹、力矩、逆运动学结果或穿刺轨迹。
15. 坐标数值缺少单位或坐标系时不要编造。{coordinate_default_rule}
16. 多组坐标只有在“入点/靶点”标签和 XYZ 顺序都明确时才能提取；顺序含糊、
    内容矛盾、字段不完整或与机械臂无关时必须选择 clarify。XYZ 顺序或坐标标签
    不明确时，在 missing_fields 中统一使用 coordinate_order。
17. clarify 必须在 missing_fields 中列出要补充或确认的字段，并在 summary 中给出
    清楚、简短的中文问题。停止和急停不需要坐标。
18. 所有显式距离换算成毫米。坐标来源按实际情况填写 user_text、asr_text、
    image_annotation、structured_data 或 gesture。
19. 不得调用任何其他函数，不得返回底层工具名或服务地址。
20. 用户明确要求穿刺、进针或针刺时不得改写成普通运动；如果缺少靶点，
    必须选择 clarify，并在 missing_fields 中加入 target_point。

当前运行模式：{settings.runtime_mode.value}
默认距离单位：{settings.default_distance_unit.value}
默认坐标系：{settings.default_coordinate_frame.value}
默认模糊相对步长：{settings.default_relative_step_mm:g} mm
默认模糊关节转角：{settings.default_relative_rotation_deg:g} 度
默认旋转关节：J{settings.default_rotation_joint_index}
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
                            "move_sequence",
                            "stop",
                            "emergency_stop",
                            "clarify",
                        ],
                    },
                    "entry_point": _point_schema("Three-dimensional puncture entry point"),
                    "target_point": _point_schema("Three-dimensional puncture target point"),
                    "motion_steps": {
                        "anyOf": [
                            {
                                "type": "array",
                                "minItems": 1,
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "kind": {
                                            "type": "string",
                                            "enum": [
                                                "cartesian_relative",
                                                "cartesian_absolute",
                                                "joint_relative",
                                                "joint_absolute",
                                                "tcp_rotation_relative",
                                                "tcp_rotation_absolute",
                                            ],
                                        },
                                        "axis": {"type": "string", "enum": ["x", "y", "z"]},
                                        "direction": {
                                            "type": "string",
                                            "enum": ["positive", "negative"],
                                        },
                                        "distance_mm": {"type": "number", "exclusiveMinimum": 0},
                                        "delta_mm": {
                                            "type": "array",
                                            "items": {"type": "number"},
                                            "minItems": 3,
                                            "maxItems": 3,
                                        },
                                        "target_position_mm": {
                                            "type": "array",
                                            "items": {"type": "number"},
                                            "minItems": 3,
                                            "maxItems": 3,
                                        },
                                        "frame": {"type": "string", "enum": ["robot_base"]},
                                        "joint_index": {"type": "integer", "minimum": 1, "maximum": 6},
                                        "rotation_deg": {"type": "number", "exclusiveMinimum": 0},
                                        "target_angle_deg": {"type": "number"},
                                        "value_source": {
                                            "type": "string",
                                            "enum": ["user_provided", "configured_default"],
                                        },
                                    },
                                    "required": ["kind", "value_source"],
                                    "additionalProperties": False,
                                },
                            },
                            {"type": "null"},
                        ],
                        "description": (
                            "All robot motion as ordered, typed MotionSequence steps"
                        ),
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
                                "relative_motion.distance_mm",
                                "relative_motion.delta_mm",
                                "motion_sequence",
                                "motion_sequence.rotation_axis",
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
                    "motion_steps",
                    "missing_fields",
                    "needs_confirmation",
                    "confidence",
                    "summary",
                ],
                "additionalProperties": False,
            },
        },
    }
