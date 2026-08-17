"""Normalize untrusted model tool arguments into a strict ParsedCommand."""

from __future__ import annotations

import json
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
    ParsedCommand,
    RuntimeMode,
)

from .errors import CommandParsingError


TOP_LEVEL_FIELDS = {
    "intent",
    "entry_point",
    "target_point",
    "relative_motion",
    "missing_fields",
    "needs_confirmation",
    "confidence",
    "summary",
}
IGNORED_MODEL_FIELDS = {"command_id", "schema_version"}
POINT_FIELDS = {"x", "y", "z", "unit", "frame", "source"}
RELATIVE_FIELDS = {"axis", "direction", "distance_mm", "frame", "distance_source"}
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
    "entry_point_3d",
}
MISSING_FIELD_ALIASES = {
    "coordinate_labels": "coordinate_order",
    "entry_point.coordinate_labels": "coordinate_order",
    "entry_point.coordinate_order": "coordinate_order",
    "target_point.coordinate_labels": "coordinate_order",
    "target_point.coordinate_order": "coordinate_order",
}
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

        relative = self._embedded_json_parameter(
            raw.get("relative_motion"),
            "relative_motion",
        )
        if relative is not None:
            motion, motion_missing = self._normalize_relative(relative)
            if motion_missing:
                missing.extend(motion_missing)
            else:
                normalized["relative_motion"] = motion

        self._append_intent_requirements(intent, normalized, missing)
        missing = list(dict.fromkeys(missing))

        if intent == CommandIntent.CLARIFY or missing:
            normalized["intent"] = CommandIntent.CLARIFY
            normalized["relative_motion"] = None
            normalized["missing_fields"] = missing or ["intent"]
            normalized["needs_confirmation"] = True
            if not normalized["summary"] or intent != CommandIntent.CLARIFY:
                normalized["summary"] = self._clarification_summary(
                    normalized["missing_fields"]
                )
        else:
            normalized["missing_fields"] = []
            if intent in {CommandIntent.PUNCTURE, CommandIntent.MOVE_TO_ENTRY}:
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

        source_value = value.get("source", input_source.value)
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
        try:
            axis = Axis(value.get("axis"))
        except (TypeError, ValueError):
            axis = None
            missing.append("relative_motion.axis")
        try:
            direction = Direction(value.get("direction"))
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
        if distance is None:
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
        assert axis is not None and direction is not None and frame is not None
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

        flattened_fields = set(raw) & RELATIVE_FIELDS
        if not flattened_fields:
            return
        if intent != CommandIntent.MOVE_RELATIVE:
            raise cls._invalid(
                "Tool arguments contain unsupported fields",
                details={"fields": sorted(flattened_fields)},
            )

        relative_value = raw.get("relative_motion")
        if (
            isinstance(relative_value, str)
            and relative_value.strip().lower() in {axis.value for axis in Axis}
        ):
            # InternS2 can emit <parameter=relative_motion>z</parameter>
            # followed by direction/distance/frame as sibling parameters.
            relative = {"axis": relative_value.strip().lower()}
        else:
            relative = cls._embedded_json_parameter(
                relative_value,
                "relative_motion",
            )
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

        conflicts = [
            field
            for field in flattened_fields
            if field in relative and relative[field] != raw[field]
        ]
        if conflicts:
            raise cls._invalid(
                "Flattened relative motion conflicts with relative_motion",
                details={"fields": sorted(conflicts)},
            )

        for field in flattened_fields:
            relative[field] = raw.pop(field)
        raw["relative_motion"] = relative

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
        elif intent in {CommandIntent.STOP, CommandIntent.EMERGENCY_STOP}:
            normalized["entry_point"] = None
            normalized["target_point"] = None
            normalized["relative_motion"] = None

    @classmethod
    def _missing_fields(cls, value: Any) -> list[str]:
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
            return "解析到入点；仅移动针尖到入点。"
        if intent == CommandIntent.MOVE_RELATIVE:
            motion = payload["relative_motion"]
            sign = "+" if motion["direction"] == Direction.POSITIVE else "-"
            return (
                f"机械臂沿 {motion['frame'].value} {sign}{motion['axis'].value.upper()} "
                f"移动 {motion['distance_mm']:g} 毫米。"
            )
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
