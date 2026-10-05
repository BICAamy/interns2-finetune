"""Normalize untrusted model tool arguments into a strict ParsedCommand."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from math import isfinite
from typing import Any, Callable
from uuid import uuid4

from pydantic import ValidationError

from agent.config import AgentSettings
from surgical_contracts import (
    Axis,
    CommandIntent,
    CoordinateFrame,
    CoordinateSource,
    Direction,
    DistanceSource,
    ErrorCode,
    MotionSequenceStep,
    MotionStepKind,
    ParsedCommand,
    RelativeMotion,
    RuntimeMode,
)

from .errors import CommandParsingError


MODEL_RELATIVE_FIELD_MAP = {
    "relative_axis": "axis",
    "relative_direction": "direction",
    "relative_distance_mm": "distance_mm",
    "relative_frame": "frame",
    "relative_distance_source": "distance_source",
    "relative_delta_mm": "delta_mm",
}
TOP_LEVEL_FIELDS = {
    "intent",
    "entry_point",
    "target_point",
    "relative_motion",
    "motion_steps",
    "missing_fields",
    "needs_confirmation",
    "confidence",
    "summary",
} | set(MODEL_RELATIVE_FIELD_MAP)
IGNORED_MODEL_FIELDS = {"command_id", "schema_version"}
POINT_FIELDS = {"x", "y", "z", "unit", "frame", "source"}
RELATIVE_FIELDS = {
    "axis", "direction", "distance_mm", "delta_mm", "frame", "distance_source",
}
# Demo-only phrase expansion.  Keep the geometry explicit and deterministic;
# it is still validated and confirmed like every other MotionSequence.
DEMO_HEART_DELTAS_MM = (
    (20.0, 0.0, 30.0),
    (40.0, 0.0, 0.0),
    (30.0, 0.0, -30.0),
    (0.0, 0.0, -50.0),
    (-40.0, 0.0, -50.0),
    (-50.0, 0.0, -50.0),
    (-50.0, 0.0, 50.0),
    (-40.0, 0.0, 50.0),
    (0.0, 0.0, 50.0),
    (30.0, 0.0, 30.0),
    (40.0, 0.0, 0.0),
    (20.0, 0.0, -30.0),
)
DEMO_HEART_PRESET_ID = "heart_180mm_xz"
DEMO_HEART_PROMPT = re.compile(
    r"(?:请)?(?:(?:给我|帮我))?画(?:一个|个|一颗)?爱心[。.!！]?"
)
ALLOWED_MISSING_FIELDS = {
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
}
MISSING_FIELD_ALIASES = {
    "coordinate_labels": "coordinate_order",
    "entry_point.coordinate_labels": "coordinate_order",
    "entry_point.coordinate_order": "coordinate_order",
    "target_point.coordinate_labels": "coordinate_order",
    "target_point.coordinate_order": "coordinate_order",
}


def identify_demo_motion_preset(text: str) -> str | None:
    """Return the exact demo preset selected by a narrowly matched phrase."""

    compact_text = re.sub(r"\s+", "", text.strip())
    if DEMO_HEART_PROMPT.fullmatch(compact_text):
        return DEMO_HEART_PRESET_ID
    return None
MAX_EMBEDDED_JSON_CHARS = 32_768
MAX_EMBEDDED_JSON_DEPTH = 2

FRAME_ALIASES = {
    "robot_base": CoordinateFrame.ROBOT_BASE,
    "base": CoordinateFrame.ROBOT_BASE,
    "基座": CoordinateFrame.ROBOT_BASE,
    "基座坐标系": CoordinateFrame.ROBOT_BASE,
    "tool_center_point": CoordinateFrame.TOOL_CENTER_POINT,
    "tcp": CoordinateFrame.TOOL_CENTER_POINT,
    "needle_tip": CoordinateFrame.NEEDLE_TIP,
    "simulation_world": CoordinateFrame.SIMULATION_WORLD,
    "scene_camera": CoordinateFrame.SCENE_CAMERA,
}
UNIT_SCALE_TO_MM = {
    "mm": 1.0,
    "millimeter": 1.0,
    "millimeters": 1.0,
    "毫米": 1.0,
    "cm": 10.0,
    "centimeter": 10.0,
    "centimeters": 10.0,
    "厘米": 10.0,
    "m": 1000.0,
    "meter": 1000.0,
    "meters": 1000.0,
    "米": 1000.0,
}


class CommandNormalizer:
    """Apply runtime-owned IDs/defaults, then enforce the shared contract."""

    def __init__(
        self,
        settings: AgentSettings,
        *,
        command_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.settings = settings
        self._command_id_factory = command_id_factory or (
            lambda: f"cmd-{uuid4().hex}"
        )

    def normalize(
        self,
        arguments: dict[str, Any],
        *,
        input_source: CoordinateSource = CoordinateSource.USER_TEXT,
        input_text: str | None = None,
    ) -> ParsedCommand:
        if not isinstance(arguments, dict):
            raise self._invalid("Tool arguments must be a JSON object")

        raw = deepcopy(arguments)
        for field in IGNORED_MODEL_FIELDS:
            raw.pop(field, None)

        try:
            intent = CommandIntent(raw.get("intent"))
        except (TypeError, ValueError) as error:
            raise self._invalid("Tool arguments contain an invalid intent") from error

        self._repair_flattened_relative_motion(raw, intent)
        unknown = set(raw) - TOP_LEVEL_FIELDS
        if unknown:
            raise self._invalid(
                "Tool arguments contain unsupported fields",
                details={"fields": sorted(unknown)},
            )

        missing = self._missing_fields(raw.get("missing_fields", []))
        normalized: dict[str, Any] = {
            "command_id": self._trusted_command_id(),
            "intent": intent,
            "entry_point": None,
            "target_point": None,
            "relative_motion": None,
            "motion_sequence": None,
            "missing_fields": missing,
            "needs_confirmation": self._boolean_parameter(
                raw.get("needs_confirmation", False),
                "needs_confirmation",
            ),
            "confidence": self._confidence_parameter(raw.get("confidence", 0.0)),
            "summary": str(raw.get("summary") or "").strip(),
        }

        for name in ("entry_point", "target_point"):
            value = self._embedded_json_parameter(raw.get(name), name)
            if value is None:
                continue
            point, point_missing = self._normalize_point(value, name, input_source)
            if point_missing:
                missing.extend(point_missing)
            else:
                normalized[name] = point

        relative = self._relative_object_parameter(
            raw.get("relative_motion"),
        )
        if relative is not None:
            motion, motion_missing = self._normalize_relative(relative)
            if motion_missing:
                missing.extend(motion_missing)
            else:
                normalized["relative_motion"] = motion

        motion_steps = self._embedded_json_parameter(
            raw.get("motion_steps"),
            "motion_steps",
        )
        if motion_steps is not None:
            if intent != CommandIntent.MOVE_SEQUENCE:
                raise self._invalid("motion_steps is valid only for move_sequence")
            sequence, sequence_missing = self._normalize_motion_steps(motion_steps)
            if sequence_missing:
                missing.extend(sequence_missing)
            else:
                normalized["motion_sequence"] = sequence

        if self._must_preserve_incomplete_puncture(intent, normalized, input_text):
            # Never reinterpret an explicit puncture request that lacks a target
            # as an executable move-to-entry command.
            intent = CommandIntent.CLARIFY
            normalized["summary"] = ""
            missing.append("target_point")

        if not missing and intent == CommandIntent.MOVE_RELATIVE:
            motion = normalized["relative_motion"]
            if motion is not None:
                translation = RelativeMotion.model_validate(motion).translation_mm()
                normalized["motion_sequence"] = {
                    "steps": [MotionSequenceStep(
                        kind=MotionStepKind.CARTESIAN_RELATIVE,
                        translation_mm=translation,
                        frame=self.settings.default_coordinate_frame,
                        value_source=motion["distance_source"],
                    ).model_dump(mode="python")]
                }
                normalized["relative_motion"] = None
                intent = CommandIntent.MOVE_SEQUENCE
        elif not missing and intent == CommandIntent.MOVE_TO_ENTRY:
            point = normalized["entry_point"]
            if point is not None:
                normalized["motion_sequence"] = {
                    "steps": [MotionSequenceStep(
                        kind=MotionStepKind.CARTESIAN_ABSOLUTE,
                        target_position_mm=(point["x"], point["y"], point["z"]),
                        frame=point["frame"],
                    ).model_dump(mode="python")]
                }
                normalized["entry_point"] = None
                intent = CommandIntent.MOVE_SEQUENCE

        self._append_intent_requirements(intent, normalized, missing)
        missing = list(dict.fromkeys(missing))
        normalized["intent"] = intent

        if intent == CommandIntent.CLARIFY or missing:
            normalized["intent"] = CommandIntent.CLARIFY
            normalized["relative_motion"] = None
            normalized["motion_sequence"] = None
            normalized["missing_fields"] = missing or ["intent"]
            normalized["needs_confirmation"] = True
            if not normalized["summary"] or intent != CommandIntent.CLARIFY:
                normalized["summary"] = self._clarification_summary(
                    normalized["missing_fields"]
                )
        else:
            normalized["missing_fields"] = []
            if intent in {
                CommandIntent.PUNCTURE,
                CommandIntent.MOVE_TO_ENTRY,
                CommandIntent.MOVE_SEQUENCE,
            }:
                # Absolute medical coordinates must be shown for confirmation by
                # the Step 8 state machine before any future real execution.
                normalized["needs_confirmation"] = True
            if not normalized["summary"]:
                normalized["summary"] = self._default_summary(normalized)

        try:
            return ParsedCommand.model_validate(normalized)
        except ValidationError as error:
            raise self._invalid(
                "InternS2 tool arguments failed ParsedCommand validation",
                details={
                    "errors": error.errors(
                        include_url=False,
                        include_context=False,
                        include_input=False,
                    )
                },
            ) from error

    def try_normalize_sequence_text(
        self,
        text: str,
        *,
        input_source: CoordinateSource = CoordinateSource.USER_TEXT,
    ) -> ParsedCommand | None:
        """Parse only explicit, unambiguous ordered Chinese motion phrases.

        The accepted grammar is deliberately narrow so callers may use this
        as a fast path before invoking InternS2 without guessing user intent.
        """

        compact_text = re.sub(r"\s+", "", text.strip())
        if identify_demo_motion_preset(compact_text) == DEMO_HEART_PRESET_ID:
            return self.normalize(
                {
                    "intent": CommandIntent.MOVE_SEQUENCE.value,
                    "motion_steps": [
                        {
                            "kind": MotionStepKind.CARTESIAN_RELATIVE.value,
                            "delta_mm": list(delta),
                            "frame": CoordinateFrame.ROBOT_BASE.value,
                            "value_source": DistanceSource.CONFIGURED_DEFAULT.value,
                        }
                        for delta in DEMO_HEART_DELTAS_MM
                    ],
                    "missing_fields": [],
                    "needs_confirmation": True,
                    "confidence": 1.0,
                    "summary": "演示预设：在 Base X-Z 平面绘制 180×180 mm 爱心轨迹",
                },
                input_source=input_source,
                input_text=text,
            )

        absolute_position = re.fullmatch(
            r"(?:机械臂|TCP)?(?:移动)?(?:到|至)?(?:Base|base|基座)(?:坐标系)?(?:下)?"
            r"[（(]?X[=:：]?(-?\d+(?:\.\d+)?)[,，]"
            r"Y[=:：]?(-?\d+(?:\.\d+)?)[,，]"
            r"Z[=:：]?(-?\d+(?:\.\d+)?)[）)]?(?:毫米|mm)?",
            compact_text,
            flags=re.IGNORECASE,
        )
        if absolute_position is not None:
            return self.normalize(
                {
                    "intent": CommandIntent.MOVE_SEQUENCE.value,
                    "motion_steps": [{
                        "kind": MotionStepKind.CARTESIAN_ABSOLUTE.value,
                        "target_position_mm": [
                            float(absolute_position.group(1)),
                            float(absolute_position.group(2)),
                            float(absolute_position.group(3)),
                        ],
                        "frame": CoordinateFrame.ROBOT_BASE.value,
                        "value_source": DistanceSource.USER_PROVIDED.value,
                    }],
                    "missing_fields": [],
                    "needs_confirmation": True,
                    "confidence": 1.0,
                    "summary": "",
                },
                input_source=input_source,
                input_text=text,
            )

        if re.fullmatch(
            r"(?:把)?TCP(?:(?:旋转|转动|转)?到-?\d+(?:\.\d+)?(?:度|°)"
            r"|(?:向)?(?:左|右)?(?:旋转|转动|转)"
            r"(?:一点|一些|稍微|\d+(?:\.\d+)?(?:度|°)))",
            compact_text,
            flags=re.IGNORECASE,
        ):
            return self.normalize(
                {
                    "intent": CommandIntent.CLARIFY.value,
                    "motion_steps": None,
                    "missing_fields": ["motion_sequence.rotation_axis"],
                    "needs_confirmation": True,
                    "confidence": 1.0,
                    "summary": "请说明 TCP 要绕 Base X、Y、Z 中的哪一轴旋转。",
                },
                input_source=input_source,
                input_text=text,
            )

        # Keep the commas in ``X=...,Y=...,Z=...`` together while ordinary
        # sentence commas remain valid sequence separators.
        coordinate_comma = "__COORD_COMMA__"
        protected_text = re.sub(
            r"(?<=\d)[,，](?=(?:Δ)?[YyZz]\s*[=:：])",
            coordinate_comma,
            text.strip(),
        )
        clauses = [
            part.replace(coordinate_comma, ",").strip()
            for part in re.split(
                r"(?:之后|然后|接着|再|[，,;；])+",
                protected_text,
            )
            if part.strip()
        ]
        if not clauses:
            return None
        direction_map = {
            "前": (Axis.X, Direction.POSITIVE),
            "后": (Axis.X, Direction.NEGATIVE),
            "左": (Axis.Y, Direction.POSITIVE),
            "右": (Axis.Y, Direction.NEGATIVE),
            "上": (Axis.Z, Direction.POSITIVE),
            "下": (Axis.Z, Direction.NEGATIVE),
        }
        vague = {"一点", "一些", "稍微"}

        def distance_mm(number: str, unit: str) -> float:
            scale = UNIT_SCALE_TO_MM.get(unit.lower())
            if scale is None:
                raise ValueError("unsupported distance unit")
            return float(number) * scale

        steps: list[dict[str, Any]] = []
        for clause in clauses:
            compact = re.sub(r"\s+", "", clause)
            cartesian_delta = re.fullmatch(
                r"(?:第\d+步[::：]?)?(?:沿)?(?:Base|base|基座)(?:坐标系)?(?:下)?"
                r"(?:组合)?(?:相对)?(?:移动|位移)"
                r"Δ?X[=:：]?(-?\d+(?:\.\d+)?)[,，]"
                r"Δ?Y[=:：]?(-?\d+(?:\.\d+)?)[,，]"
                r"Δ?Z[=:：]?(-?\d+(?:\.\d+)?)(?:毫米|mm)",
                compact,
                flags=re.IGNORECASE,
            )
            if cartesian_delta is not None:
                steps.append({
                    "kind": MotionStepKind.CARTESIAN_RELATIVE.value,
                    "delta_mm": [
                        float(cartesian_delta.group(1)),
                        float(cartesian_delta.group(2)),
                        float(cartesian_delta.group(3)),
                    ],
                    "frame": CoordinateFrame.ROBOT_BASE.value,
                    "value_source": DistanceSource.USER_PROVIDED.value,
                })
                continue

            cartesian_absolute = re.fullmatch(
                r"(?:机械臂|TCP)?(?:移动)?(?:到|至)?(?:Base|base|基座)(?:坐标系)?(?:下)?"
                r"[（(]?X[=:：]?(-?\d+(?:\.\d+)?)[,，]"
                r"Y[=:：]?(-?\d+(?:\.\d+)?)[,，]"
                r"Z[=:：]?(-?\d+(?:\.\d+)?)[）)]?(?:毫米|mm)?",
                compact,
                flags=re.IGNORECASE,
            )
            if cartesian_absolute is not None:
                steps.append({
                    "kind": MotionStepKind.CARTESIAN_ABSOLUTE.value,
                    "target_position_mm": [
                        float(cartesian_absolute.group(1)),
                        float(cartesian_absolute.group(2)),
                        float(cartesian_absolute.group(3)),
                    ],
                    "frame": CoordinateFrame.ROBOT_BASE.value,
                    "value_source": DistanceSource.USER_PROVIDED.value,
                })
                continue

            joint_absolute = re.fullmatch(
                r"(?:把)?(?:[Jj]([1-6])|(?:第)?([1-6])(?:轴|关节))"
                r"(?:关节)?(?:旋转|转动|转)?(?:到|至|设为)"
                r"(-?\d+(?:\.\d+)?)(?:度|°)",
                compact,
            )
            if joint_absolute is not None:
                steps.append({
                    "kind": MotionStepKind.JOINT_ABSOLUTE.value,
                    "joint_index": int(
                        joint_absolute.group(1) or joint_absolute.group(2)
                    ),
                    "target_angle_deg": float(joint_absolute.group(3)),
                    "value_source": DistanceSource.USER_PROVIDED.value,
                })
                continue

            tcp_absolute = re.fullmatch(
                r"(?:把)?TCP(?:绕)?(?:Base|base|基座)([XYZxyz])(?:轴)?"
                r"(?:旋转|转动|转)?(?:到|至|设为)"
                r"(-?\d+(?:\.\d+)?)(?:度|°)",
                compact,
            )
            if tcp_absolute is not None:
                steps.append({
                    "kind": MotionStepKind.TCP_ROTATION_ABSOLUTE.value,
                    "axis": tcp_absolute.group(1).lower(),
                    "target_angle_deg": float(tcp_absolute.group(2)),
                    "value_source": DistanceSource.USER_PROVIDED.value,
                })
                continue

            tcp_relative = re.fullmatch(
                r"TCP(?:绕)?(?:Base|base|基座)([XYZxyz])(?:轴)?"
                r"(?:(增加|减少|正向|负向|\+|-))?(?:旋转|转动|转)?"
                r"(一点|一些|稍微|(?:\d+(?:\.\d+)?)(?:度|°))",
                compact,
            )
            if tcp_relative is not None:
                amount = tcp_relative.group(3)
                sign_word = tcp_relative.group(2)
                step = {
                    "kind": MotionStepKind.TCP_ROTATION_RELATIVE.value,
                    "axis": tcp_relative.group(1).lower(),
                    "direction": (
                        Direction.NEGATIVE.value
                        if sign_word in {"减少", "负向", "-"}
                        else Direction.POSITIVE.value
                    ),
                    "value_source": (
                        DistanceSource.CONFIGURED_DEFAULT.value
                        if amount in vague
                        else DistanceSource.USER_PROVIDED.value
                    ),
                }
                if amount not in vague:
                    step["rotation_deg"] = float(
                        re.sub(r"(?:度|°)$", "", amount)
                    )
                steps.append(step)
                continue

            rotation = re.fullmatch(
                r"(?:机械臂)?(?:(?:[Jj]([1-6])|(?:第)?([1-6])(?:轴|关节))"
                r"(?:关节)?)?"
                r"(?:(?:向)?(左|右)转(?:动)?|"
                r"(增加|减少|正向|负向)(?:旋转|转动|转)?)"
                r"(一点|一些|稍微|(?:\d+(?:\.\d+)?)(?:度|°))",
                compact,
            )
            if rotation is not None:
                amount = rotation.group(5)
                step: dict[str, Any] = {
                    "kind": MotionStepKind.JOINT_RELATIVE.value,
                    "joint_index": int(
                        rotation.group(1)
                        or rotation.group(2)
                        or self.settings.default_rotation_joint_index
                    ),
                    "direction": (
                        Direction.POSITIVE.value
                        if (
                            rotation.group(3) == "左"
                            or rotation.group(4) in {"增加", "正向"}
                        )
                        else Direction.NEGATIVE.value
                    ),
                    "value_source": (
                        DistanceSource.CONFIGURED_DEFAULT.value
                        if amount in vague
                        else DistanceSource.USER_PROVIDED.value
                    ),
                }
                if amount not in vague:
                    step["rotation_deg"] = float(
                        re.sub(r"(?:度|°)$", "", amount)
                    )
                steps.append(step)
                continue

            translation = re.fullmatch(
                r"(?:机械臂)?(?:往|向)?(前|后|左|右|上|下)"
                r"(?:移动|运动|前进|后退|抬高|降低)?"
                r"(一点|一些|稍微|(?:\d+(?:\.\d+)?)(?:毫米|mm|厘米|cm|米|m))",
                compact,
                flags=re.IGNORECASE,
            )
            if translation is None:
                return None
            axis, direction = direction_map[translation.group(1)]
            amount = translation.group(2)
            step = {
                "kind": MotionStepKind.CARTESIAN_RELATIVE.value,
                "axis": axis.value,
                "direction": direction.value,
                "value_source": (
                    DistanceSource.CONFIGURED_DEFAULT.value
                    if amount in vague
                    else DistanceSource.USER_PROVIDED.value
                ),
            }
            if amount not in vague:
                match = re.fullmatch(
                    r"(\d+(?:\.\d+)?)(毫米|mm|厘米|cm|米|m)",
                    amount,
                    flags=re.IGNORECASE,
                )
                if match is None:
                    return None
                step["distance_mm"] = distance_mm(match.group(1), match.group(2))
            steps.append(step)

        return self.normalize(
            {
                "intent": CommandIntent.MOVE_SEQUENCE.value,
                "motion_steps": steps,
                "missing_fields": [],
                "needs_confirmation": True,
                "confidence": 1.0,
                "summary": f"按原指令顺序执行 {len(steps)} 个动作",
            },
            input_source=input_source,
            input_text=text,
        )

    def _normalize_point(
        self,
        value: Any,
        name: str,
        input_source: CoordinateSource,
    ) -> tuple[dict[str, Any] | None, list[str]]:
        if not isinstance(value, dict):
            raise self._invalid(
                f"{name} must be an object or null",
                details={"field": name, "received_type": type(value).__name__},
            )
        unknown = set(value) - POINT_FIELDS
        if unknown:
            raise self._invalid(
                f"{name} contains unsupported fields",
                details={"fields": sorted(unknown)},
            )

        missing = [f"{name}.{axis}" for axis in ("x", "y", "z") if axis not in value]
        if missing:
            return None, missing

        coordinates: list[float] = []
        for axis in ("x", "y", "z"):
            component = value[axis]
            if isinstance(component, bool):
                raise self._invalid(f"{name}.{axis} must be a finite number")
            try:
                number = float(component)
            except (TypeError, ValueError) as error:
                raise self._invalid(f"{name}.{axis} must be a finite number") from error
            if not isfinite(number):
                raise self._invalid(f"{name}.{axis} must be a finite number")
            coordinates.append(number)

        point_missing: list[str] = []
        unit = value.get("unit")
        if unit is None or not str(unit).strip():
            if self.settings.runtime_mode == RuntimeMode.REAL:
                point_missing.append(f"{name}.unit")
            scale = 1.0
        else:
            scale = UNIT_SCALE_TO_MM.get(str(unit).strip().lower())
            if scale is None:
                point_missing.append(f"{name}.unit")
                scale = 1.0

        frame_value = value.get("frame")
        if frame_value is None or not str(frame_value).strip():
            if self.settings.runtime_mode == RuntimeMode.REAL:
                point_missing.append(f"{name}.frame")
            frame = self.settings.default_coordinate_frame
        else:
            frame = FRAME_ALIASES.get(str(frame_value).strip().lower())
            if frame is None:
                point_missing.append(f"{name}.frame")
                frame = self.settings.default_coordinate_frame

        if frame != self.settings.default_coordinate_frame:
            point_missing.append(f"{name}.coordinate_transform")

        if point_missing:
            return None, point_missing

        # Provenance is runtime-owned. A model must not relabel ASR coordinates
        # as direct user text merely because its tool arguments include source.
        source_value = (
            input_source.value
            if input_source == CoordinateSource.ASR_TEXT
            else value.get("source", input_source.value)
        )
        try:
            source = CoordinateSource(source_value)
        except (TypeError, ValueError) as error:
            raise self._invalid(f"{name}.source is invalid") from error

        return (
            {
                "x": coordinates[0] * scale,
                "y": coordinates[1] * scale,
                "z": coordinates[2] * scale,
                "unit": self.settings.default_distance_unit,
                "frame": frame,
                "source": source,
            },
            [],
        )

    def _normalize_relative(
        self,
        value: Any,
    ) -> tuple[dict[str, Any] | None, list[str]]:
        if not isinstance(value, dict):
            raise self._invalid(
                "relative_motion must be an object or null",
                details={
                    "field": "relative_motion",
                    "received_type": type(value).__name__,
                },
            )
        unknown = set(value) - RELATIVE_FIELDS
        if unknown:
            raise self._invalid(
                "relative_motion contains unsupported fields",
                details={"fields": sorted(unknown)},
            )

        missing: list[str] = []
        vector_value = value.get("delta_mm")
        vector: tuple[float, float, float] | None = None
        if vector_value is not None:
            if any(value.get(name) is not None for name in ("axis", "direction", "distance_mm")):
                raise self._invalid(
                    "relative_motion cannot mix an XYZ vector with axis fields"
                )
            if not isinstance(vector_value, (list, tuple)) or len(vector_value) != 3:
                raise self._invalid("relative_motion.delta_mm must contain [dx, dy, dz]")
            parsed_vector: list[float] = []
            for component in vector_value:
                if isinstance(component, bool):
                    raise self._invalid("relative_motion.delta_mm must contain finite numbers")
                try:
                    number = float(component)
                except (TypeError, ValueError) as error:
                    raise self._invalid(
                        "relative_motion.delta_mm must contain finite numbers"
                    ) from error
                if not isfinite(number):
                    raise self._invalid("relative_motion.delta_mm must contain finite numbers")
                parsed_vector.append(number)
            if all(number == 0.0 for number in parsed_vector):
                raise self._invalid("relative_motion.delta_mm cannot be zero")
            vector = tuple(parsed_vector)

        try:
            axis = None if vector is not None else Axis(value.get("axis"))
        except (TypeError, ValueError):
            axis = None
            missing.append("relative_motion.axis")
        try:
            direction = None if vector is not None else Direction(value.get("direction"))
        except (TypeError, ValueError):
            direction = None
            missing.append("relative_motion.direction")

        frame_value = value.get("frame")
        if frame_value is None or not str(frame_value).strip():
            if self.settings.runtime_mode == RuntimeMode.REAL:
                missing.append("relative_motion.frame")
                frame = None
            else:
                frame = self.settings.default_coordinate_frame
        else:
            frame = FRAME_ALIASES.get(str(frame_value).strip().lower())
            if frame is None or frame != self.settings.default_coordinate_frame:
                missing.append("relative_motion.frame")
                frame = None

        distance = value.get("distance_mm")
        if vector is not None:
            distance_mm = None
            distance_source = DistanceSource.USER_PROVIDED
        elif distance is None:
            distance_mm = self.settings.default_relative_step_mm
            distance_source = DistanceSource.CONFIGURED_DEFAULT
        else:
            if isinstance(distance, bool):
                raise self._invalid("relative_motion.distance_mm must be positive")
            try:
                distance_mm = float(distance)
            except (TypeError, ValueError) as error:
                raise self._invalid("relative_motion.distance_mm must be positive") from error
            if not isfinite(distance_mm) or distance_mm <= 0:
                raise self._invalid("relative_motion.distance_mm must be positive")
            source_value = value.get(
                "distance_source",
                DistanceSource.USER_PROVIDED.value,
            )
            try:
                distance_source = DistanceSource(source_value)
            except (TypeError, ValueError) as error:
                raise self._invalid("relative_motion.distance_source is invalid") from error

        if missing:
            return None, missing
        assert frame is not None
        if vector is not None:
            return (
                {
                    "delta_mm": vector,
                    "frame": frame,
                    "distance_source": distance_source,
                },
                [],
            )
        assert axis is not None and direction is not None
        return (
            {
                "axis": axis,
                "direction": direction,
                "distance_mm": distance_mm,
                "frame": frame,
                "distance_source": distance_source,
            },
            [],
        )

    def _normalize_motion_steps(
        self,
        value: Any,
    ) -> tuple[dict[str, Any] | None, list[str]]:
        if not isinstance(value, list) or not value:
            raise self._invalid("motion_steps must contain at least one step")
        allowed = {
            "kind", "axis", "direction", "distance_mm", "delta_mm",
            "target_position_mm", "frame", "joint_index", "rotation_deg",
            "target_angle_deg", "value_source",
        }

        def vector3(raw: Any, field: str) -> tuple[float, float, float]:
            if not isinstance(raw, (list, tuple)) or len(raw) != 3:
                raise self._invalid(f"{field} must contain three finite numbers")
            values: list[float] = []
            for component in raw:
                if isinstance(component, bool):
                    raise self._invalid(f"{field} must contain three finite numbers")
                try:
                    number = float(component)
                except (TypeError, ValueError) as error:
                    raise self._invalid(
                        f"{field} must contain three finite numbers"
                    ) from error
                if not isfinite(number):
                    raise self._invalid(f"{field} must contain three finite numbers")
                values.append(number)
            return tuple(values)  # type: ignore[return-value]

        def finite_number(raw: Any, field: str) -> float:
            if isinstance(raw, bool):
                raise self._invalid(f"{field} must be a finite number")
            try:
                number = float(raw)
            except (TypeError, ValueError) as error:
                raise self._invalid(f"{field} must be a finite number") from error
            if not isfinite(number):
                raise self._invalid(f"{field} must be a finite number")
            return number

        normalized_steps: list[dict[str, Any]] = []
        for index, step in enumerate(value):
            if not isinstance(step, dict):
                raise self._invalid(
                    "each motion_steps item must be an object",
                    details={"index": index},
                )
            unknown = set(step) - allowed
            if unknown:
                raise self._invalid(
                    "motion step contains unsupported fields",
                    details={"index": index, "fields": sorted(unknown)},
                )
            raw_kind = {
                "translation": MotionStepKind.CARTESIAN_RELATIVE.value,
                "joint_rotation": MotionStepKind.JOINT_RELATIVE.value,
            }.get(step.get("kind"), step.get("kind"))
            try:
                kind = MotionStepKind(raw_kind)
            except (TypeError, ValueError) as error:
                raise self._invalid(
                    "motion step kind is invalid",
                    details={"index": index},
                ) from error
            try:
                source = DistanceSource(
                    step.get("value_source", DistanceSource.USER_PROVIDED.value)
                )
            except (TypeError, ValueError) as error:
                raise self._invalid(
                    "motion step value_source is invalid",
                    details={"index": index},
                ) from error

            frame_value = step.get("frame")
            if frame_value is None or not str(frame_value).strip():
                frame = self.settings.default_coordinate_frame
            else:
                frame = FRAME_ALIASES.get(str(frame_value).strip().lower())
                if frame != CoordinateFrame.ROBOT_BASE:
                    return None, ["motion_sequence"]

            if kind == MotionStepKind.CARTESIAN_RELATIVE:
                if (
                    source == DistanceSource.USER_PROVIDED
                    and step.get("distance_mm") is None
                    and step.get("delta_mm") is None
                ):
                    return None, ["motion_sequence"]
                relative_input = {
                    name: step[name]
                    for name in (
                        "axis", "direction", "distance_mm", "delta_mm", "frame"
                    )
                    if name in step
                }
                relative_input["distance_source"] = source.value
                motion, step_missing = self._normalize_relative(relative_input)
                if step_missing or motion is None:
                    return None, ["motion_sequence"]
                translation = RelativeMotion.model_validate(motion).translation_mm()
                normalized_steps.append(
                    MotionSequenceStep(
                        kind=kind,
                        translation_mm=translation,
                        frame=frame,
                        value_source=source,
                    ).model_dump(mode="python")
                )
                continue

            if kind == MotionStepKind.CARTESIAN_ABSOLUTE:
                raw_target = step.get("target_position_mm")
                if raw_target is None:
                    return None, ["motion_sequence"]
                normalized_steps.append(
                    MotionSequenceStep(
                        kind=kind,
                        target_position_mm=vector3(
                            raw_target,
                            "motion step target_position_mm",
                        ),
                        frame=frame,
                        value_source=source,
                    ).model_dump(mode="python")
                )
                continue

            if kind in {
                MotionStepKind.JOINT_RELATIVE,
                MotionStepKind.TCP_ROTATION_RELATIVE,
            }:
                try:
                    direction = Direction(step.get("direction"))
                except (TypeError, ValueError):
                    return None, ["motion_sequence"]
                raw_rotation = step.get("rotation_deg")
                if raw_rotation is None:
                    if source != DistanceSource.CONFIGURED_DEFAULT:
                        return None, ["motion_sequence"]
                    rotation = self.settings.default_relative_rotation_deg
                else:
                    rotation = finite_number(raw_rotation, "motion step rotation_deg")
                if not isfinite(rotation) or rotation <= 0:
                    raise self._invalid("motion step rotation_deg must be positive")
                if direction == Direction.NEGATIVE:
                    rotation = -rotation
                if kind == MotionStepKind.JOINT_RELATIVE:
                    joint_index = step.get(
                        "joint_index",
                        self.settings.default_rotation_joint_index,
                    )
                    if (
                        isinstance(joint_index, bool)
                        or not isinstance(joint_index, int)
                        or not 1 <= joint_index <= 6
                    ):
                        raise self._invalid(
                            "motion step joint_index must be an integer from 1 to 6"
                        )
                    normalized_steps.append(MotionSequenceStep(
                        kind=kind,
                        joint_index=joint_index,
                        rotation_deg=rotation,
                        value_source=source,
                    ).model_dump(mode="python"))
                else:
                    try:
                        axis = Axis(step.get("axis"))
                    except (TypeError, ValueError):
                        return None, ["motion_sequence.rotation_axis"]
                    normalized_steps.append(MotionSequenceStep(
                        kind=kind,
                        rotation_axis=axis,
                        rotation_deg=rotation,
                        value_source=source,
                    ).model_dump(mode="python"))
                continue

            target_angle = step.get("target_angle_deg")
            if target_angle is None:
                return None, ["motion_sequence"]
            target_angle_deg = finite_number(
                target_angle,
                "motion step target_angle_deg",
            )
            if kind == MotionStepKind.JOINT_ABSOLUTE:
                joint_index = step.get("joint_index")
                if (
                    isinstance(joint_index, bool)
                    or not isinstance(joint_index, int)
                    or not 1 <= joint_index <= 6
                ):
                    return None, ["motion_sequence"]
                normalized_steps.append(MotionSequenceStep(
                    kind=kind,
                    joint_index=joint_index,
                    target_angle_deg=target_angle_deg,
                    value_source=source,
                ).model_dump(mode="python"))
            else:
                try:
                    axis = Axis(step.get("axis"))
                except (TypeError, ValueError):
                    return None, ["motion_sequence.rotation_axis"]
                normalized_steps.append(MotionSequenceStep(
                    kind=kind,
                    rotation_axis=axis,
                    target_angle_deg=target_angle_deg,
                    value_source=source,
                ).model_dump(mode="python"))
        return {"steps": normalized_steps}, []

    @classmethod
    def _repair_flattened_relative_motion(
        cls,
        raw: dict[str, Any],
        intent: CommandIntent,
    ) -> None:
        """Repair one observed InternS2/LMDeploy XML nesting deviation.

        An explicit relative distance can be emitted with ``axis`` inside
        ``relative_motion`` but the remaining relative fields at tool-argument
        top level. Only the exact RelativeMotion field set is eligible, only
        for a move_relative intent, and conflicts are rejected.
        """

        external_field_map = {
            **{field: field for field in RELATIVE_FIELDS},
            **MODEL_RELATIVE_FIELD_MAP,
        }
        flattened_fields = set(raw) & set(external_field_map)
        for field in tuple(flattened_fields):
            value = raw[field]
            if value is None or (
                isinstance(value, str) and value.strip().lower() == "null"
            ):
                raw.pop(field)
                flattened_fields.remove(field)

        if not flattened_fields:
            return
        if intent != CommandIntent.MOVE_RELATIVE:
            raise cls._invalid(
                "Tool arguments contain unsupported fields",
                details={"fields": sorted(flattened_fields)},
            )

        relative = cls._relative_object_parameter(raw.get("relative_motion"))
        if relative is None:
            relative = {}
        if not isinstance(relative, dict):
            raise cls._invalid(
                "relative_motion must be an object or null",
                details={
                    "field": "relative_motion",
                    "received_type": type(relative).__name__,
                },
            )

        conflicts: list[str] = []
        for external_field in flattened_fields:
            internal_field = external_field_map[external_field]
            if (
                internal_field in relative
                and relative[internal_field] != raw[external_field]
            ):
                conflicts.append(external_field)
        if conflicts:
            raise cls._invalid(
                "Flattened relative motion conflicts with relative_motion",
                details={"fields": sorted(conflicts)},
            )

        for external_field in flattened_fields:
            internal_field = external_field_map[external_field]
            relative[internal_field] = raw.pop(external_field)
        raw["relative_motion"] = relative

    @classmethod
    def _relative_object_parameter(cls, value: Any) -> Any:
        if isinstance(value, str):
            marker = value.strip().lower()
            match = re.fullmatch(
                r'(?:["\']?axis["\']?\s*[:=]\s*)?'
                r'["\']?([xyz])["\']?'
                r'(?:\s*(?:[-_ ]?axis|轴))?',
                marker,
            )
            if match:
                return {"axis": match.group(1)}
        return cls._embedded_json_parameter(value, "relative_motion")

    @staticmethod
    def _must_preserve_incomplete_puncture(
        intent: CommandIntent,
        normalized: dict[str, Any],
        input_text: str | None,
    ) -> bool:
        if (
            intent != CommandIntent.MOVE_TO_ENTRY
            or normalized["target_point"] is not None
            or not input_text
        ):
            return False
        text = input_text.strip().lower()
        puncture_requested = bool(
            re.search(r"穿刺|进针|针刺|\bpunctur(?:e|ing)\b|\bneedle insertion\b", text)
        )
        puncture_negated = bool(
            re.search(
                r"(?:不|不要|无需|禁止)(?:进行|执行|做)?(?:穿刺|进针|针刺)"
                r"|\b(?:do not|don't|without) punctur(?:e|ing)\b",
                text,
            )
        )
        return puncture_requested and not puncture_negated

    @staticmethod
    def _append_intent_requirements(
        intent: CommandIntent,
        normalized: dict[str, Any],
        missing: list[str],
    ) -> None:
        if intent == CommandIntent.PUNCTURE:
            if normalized["entry_point"] is None:
                missing.append("entry_point")
            if normalized["target_point"] is None:
                missing.append("target_point")
        elif intent == CommandIntent.MOVE_TO_ENTRY:
            if normalized["entry_point"] is None:
                missing.append("entry_point")
            normalized["target_point"] = None
        elif intent == CommandIntent.MOVE_RELATIVE:
            if normalized["relative_motion"] is None:
                missing.append("relative_motion")
            normalized["entry_point"] = None
            normalized["target_point"] = None
            normalized["motion_sequence"] = None
        elif intent == CommandIntent.MOVE_SEQUENCE:
            if normalized["motion_sequence"] is None:
                missing.append("motion_sequence")
            normalized["entry_point"] = None
            normalized["target_point"] = None
            normalized["relative_motion"] = None
        elif intent in {CommandIntent.STOP, CommandIntent.EMERGENCY_STOP}:
            normalized["entry_point"] = None
            normalized["target_point"] = None
            normalized["relative_motion"] = None
            normalized["motion_sequence"] = None

    @classmethod
    def _missing_fields(cls, value: Any) -> list[str]:
        # LMDeploy's XML tool parser may serialize an empty array parameter as
        # an empty string.  A blank value is unambiguous for missing_fields:
        # it means that the model reported no missing fields.  Keep this
        # compatibility local to this field so blank point/motion JSON still
        # fails closed in _embedded_json_parameter().
        if isinstance(value, str) and not value.strip():
            return []
        value = cls._embedded_json_parameter(value, "missing_fields")
        if value is None:
            return []
        if not isinstance(value, list):
            raise cls._invalid("missing_fields must be an array")
        result: list[str] = []
        for field in value:
            if not isinstance(field, str) or not field.strip():
                raise cls._invalid(
                    "missing_fields must contain non-empty strings"
                )
            stripped = MISSING_FIELD_ALIASES.get(field.strip(), field.strip())
            if stripped not in ALLOWED_MISSING_FIELDS:
                raise cls._invalid(
                    "missing_fields contains an unsupported field",
                    details={"field": stripped},
                )
            if stripped not in result:
                result.append(stripped)
        return result

    @classmethod
    def _embedded_json_parameter(cls, value: Any, name: str) -> Any:
        """Decode JSON values stringified by LMDeploy's XML tool parser.

        InternS2 emits each XML ``<parameter>`` independently. LMDeploy 0.14
        may therefore preserve objects, arrays, booleans and null as strings
        inside the otherwise valid top-level arguments object. Decode only the
        fields whose schema is non-string, with a small depth and size bound.
        """

        if not isinstance(value, str):
            return value
        candidate = value.strip()
        if not candidate:
            raise cls._invalid(f"{name} must not be an empty JSON value")
        if len(candidate) > MAX_EMBEDDED_JSON_CHARS:
            raise cls._invalid(
                f"{name} embedded JSON is too large",
                details={"max_chars": MAX_EMBEDDED_JSON_CHARS},
            )

        decoded: Any = candidate
        for _ in range(MAX_EMBEDDED_JSON_DEPTH):
            if not isinstance(decoded, str):
                return decoded
            candidate = decoded.strip()
            try:
                decoded = json.loads(candidate)
            except json.JSONDecodeError as error:
                raise cls._invalid(
                    f"{name} must contain valid JSON",
                    details={
                        "field": name,
                        "line": error.lineno,
                        "column": error.colno,
                        "reason": error.msg,
                    },
                ) from error
        return decoded

    @classmethod
    def _boolean_parameter(cls, value: Any, name: str) -> bool:
        value = cls._embedded_json_parameter(value, name)
        if not isinstance(value, bool):
            raise cls._invalid(f"{name} must be a boolean")
        return value

    @classmethod
    def _confidence_parameter(cls, value: Any) -> float:
        value = cls._embedded_json_parameter(value, "confidence")
        if isinstance(value, bool):
            raise cls._invalid("confidence must be a finite number from 0 to 1")
        try:
            confidence = float(value)
        except (TypeError, ValueError) as error:
            raise cls._invalid(
                "confidence must be a finite number from 0 to 1"
            ) from error
        if not isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            raise cls._invalid("confidence must be a finite number from 0 to 1")
        return confidence

    def _trusted_command_id(self) -> str:
        command_id = self._command_id_factory()
        if not isinstance(command_id, str) or not command_id.strip():
            raise RuntimeError("command_id_factory returned an invalid identifier")
        return command_id.strip()

    @staticmethod
    def _clarification_summary(missing: list[str]) -> str:
        labels = {
            "intent": "要执行的机械臂任务",
            "entry_point": "完整的三维入点坐标",
            "target_point": "完整的三维靶点坐标",
            "relative_motion": "明确的相对移动方向",
            "motion_sequence": "完整且有顺序的移动/关节旋转步骤",
            "motion_sequence.rotation_axis": "TCP 绕 Base X、Y、Z 中的哪一轴旋转",
            "relative_motion.axis": "相对移动轴",
            "relative_motion.direction": "相对移动正负方向",
            "relative_motion.frame": "相对移动参考坐标系",
        }
        readable = [labels.get(field, field) for field in missing]
        return "请补充或确认：" + "、".join(readable) + "。"

    @staticmethod
    def _default_summary(payload: dict[str, Any]) -> str:
        intent = payload["intent"]
        if intent == CommandIntent.PUNCTURE:
            return "解析到入点和靶点；仅准备入点定位及后续路径规划。"
        if intent == CommandIntent.MOVE_TO_ENTRY:
            return "解析到绝对 XYZ 位置；仅移动机械臂到该位置。"
        if intent == CommandIntent.MOVE_RELATIVE:
            motion = payload["relative_motion"]
            if motion.get("delta_mm") is not None:
                dx, dy, dz = motion["delta_mm"]
                return (
                    f"机械臂沿 {motion['frame'].value} 组合相对移动 "
                    f"[dX={dx:g}, dY={dy:g}, dZ={dz:g}] 毫米。"
                )
            sign = "+" if motion["direction"] == Direction.POSITIVE else "-"
            return (
                f"机械臂沿 {motion['frame'].value} {sign}{motion['axis'].value.upper()} "
                f"移动 {motion['distance_mm']:g} 毫米。"
            )
        if intent == CommandIntent.MOVE_SEQUENCE:
            steps = payload["motion_sequence"]["steps"]
            descriptions = []
            for index, step in enumerate(steps, start=1):
                if step["kind"] == MotionStepKind.CARTESIAN_RELATIVE:
                    dx, dy, dz = step["translation_mm"]
                    descriptions.append(
                        f"{index}. Base 平移 [dX={dx:g}, dY={dy:g}, dZ={dz:g}] mm"
                    )
                elif step["kind"] == MotionStepKind.CARTESIAN_ABSOLUTE:
                    x, y, z = step["target_position_mm"]
                    descriptions.append(
                        f"{index}. Base 绝对位置 [X={x:g}, Y={y:g}, Z={z:g}] mm"
                    )
                elif step["kind"] == MotionStepKind.JOINT_RELATIVE:
                    descriptions.append(
                        f"{index}. J{step['joint_index']} 相对旋转 "
                        f"{step['rotation_deg']:+g}°"
                    )
                elif step["kind"] == MotionStepKind.JOINT_ABSOLUTE:
                    descriptions.append(
                        f"{index}. J{step['joint_index']} 转到 "
                        f"{step['target_angle_deg']:g}°"
                    )
                elif step["kind"] == MotionStepKind.TCP_ROTATION_RELATIVE:
                    descriptions.append(
                        f"{index}. TCP 绕 Base {step['rotation_axis'].value.upper()} "
                        f"相对旋转 {step['rotation_deg']:+g}°"
                    )
                else:
                    descriptions.append(
                        f"{index}. TCP 的 Base RPY "
                        f"{step['rotation_axis'].value.upper()} 分量设为 "
                        f"{step['target_angle_deg']:g}°"
                    )
            return "按顺序执行：" + "；".join(descriptions) + "。"
        if intent == CommandIntent.STOP:
            return "停止机械臂运动。"
        if intent == CommandIntent.EMERGENCY_STOP:
            return "触发机械臂急停。"
        return "需要补充任务信息。"

    @staticmethod
    def _invalid(
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> CommandParsingError:
        return CommandParsingError(
            ErrorCode.MODEL_INVALID_OUTPUT,
            message,
            details=details,
        )
