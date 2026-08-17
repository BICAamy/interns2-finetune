"""Environment-backed configuration for the agent runtime."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from surgical_contracts import CoordinateFrame, DistanceUnit, RuntimeMode


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _as_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {value!r}") from exc


def _as_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc


def _as_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(
        f"{name} must be one of true/false, 1/0, yes/no, or on/off; got {value!r}"
    )


def load_environment(env_file: str | Path | None = None) -> Path:
    """Load the project .env without overriding explicitly exported variables."""

    try:
        from dotenv import load_dotenv
    except ImportError as exc:  # pragma: no cover - depends on deployment environment
        raise RuntimeError(
            "python-dotenv is not installed; run `pip install -r agent/requirements.txt`"
        ) from exc

    path = Path(env_file).expanduser().resolve() if env_file else PROJECT_ROOT / ".env"
    load_dotenv(path, override=False)
    return path


@dataclass(frozen=True)
class AgentSettings:
    """Settings for the OpenAI-compatible InternS2 inference endpoint."""

    base_url: str
    api_key: str
    model: str | None
    timeout: float
    max_retries: int
    max_tokens: int
    temperature: float
    top_p: float
    max_tool_rounds: int
    runtime_mode: RuntimeMode = RuntimeMode.SIMULATION
    default_coordinate_frame: CoordinateFrame = CoordinateFrame.ROBOT_BASE
    default_distance_unit: DistanceUnit = DistanceUnit.MILLIMETER
    default_relative_step_mm: float = 5.0
    entry_tolerance_mm: float = 1.0
    max_relative_translation_mm: float = 20.0
    robot_move_speed_mm_s: float = 5.0
    max_robot_speed_mm_s: float = 10.0
    robot_simulation_base_url: str = "http://127.0.0.1:8001"
    planner_adapter_base_url: str = "http://127.0.0.1:8002"
    robot_simulation_http_timeout: float = 10.0
    robot_simulation_command_timeout: float = 120.0
    robot_simulation_poll_interval: float = 0.05
    planner_adapter_timeout: float = 15.0
    puncture_execution_enabled: bool = False

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> "AgentSettings":
        load_environment(env_file)
        model = os.getenv("INTERNS2_MODEL", "").strip() or None
        settings = cls(
            base_url=os.getenv("INTERNS2_BASE_URL", "http://127.0.0.1:23333/v1").strip(),
            api_key=os.getenv("INTERNS2_API_KEY", "EMPTY").strip(),
            model=model,
            timeout=_as_float("INTERNS2_TIMEOUT", 300.0),
            max_retries=_as_int("INTERNS2_MAX_RETRIES", 2),
            max_tokens=_as_int("INTERNS2_MAX_TOKENS", 2048),
            temperature=_as_float("INTERNS2_TEMPERATURE", 0.0),
            top_p=_as_float("INTERNS2_TOP_P", 0.95),
            max_tool_rounds=_as_int("INTERNS2_MAX_TOOL_ROUNDS", 3),
            runtime_mode=RuntimeMode(
                os.getenv("RUNTIME_MODE", RuntimeMode.SIMULATION.value).strip()
            ),
            default_coordinate_frame=CoordinateFrame(
                os.getenv(
                    "DEFAULT_COORDINATE_FRAME",
                    CoordinateFrame.ROBOT_BASE.value,
                ).strip()
            ),
            default_distance_unit=DistanceUnit(
                os.getenv(
                    "DEFAULT_DISTANCE_UNIT",
                    DistanceUnit.MILLIMETER.value,
                ).strip()
            ),
            default_relative_step_mm=_as_float("DEFAULT_RELATIVE_STEP_MM", 5.0),
            entry_tolerance_mm=_as_float("ENTRY_TOLERANCE_MM", 1.0),
            max_relative_translation_mm=_as_float(
                "MAX_TRANSLATION_PER_COMMAND_MM",
                20.0,
            ),
            robot_move_speed_mm_s=_as_float("ROBOT_MOVE_SPEED_MM_S", 5.0),
            max_robot_speed_mm_s=_as_float("MAX_ROBOT_SPEED_MM_S", 10.0),
            robot_simulation_base_url=os.getenv(
                "ROBOT_SIMULATION_BASE_URL",
                "http://127.0.0.1:8001",
            ).strip(),
            planner_adapter_base_url=os.getenv(
                "PLANNER_ADAPTER_BASE_URL",
                "http://127.0.0.1:8002",
            ).strip(),
            robot_simulation_http_timeout=_as_float(
                "ROBOT_SIMULATION_HTTP_TIMEOUT",
                10.0,
            ),
            robot_simulation_command_timeout=_as_float(
                "ROBOT_SIMULATION_COMMAND_TIMEOUT",
                120.0,
            ),
            robot_simulation_poll_interval=_as_float(
                "ROBOT_SIMULATION_POLL_INTERVAL",
                0.05,
            ),
            planner_adapter_timeout=_as_float("PLANNER_ADAPTER_TIMEOUT", 15.0),
            puncture_execution_enabled=_as_bool(
                "PUNCTURE_EXECUTION_ENABLED",
                False,
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not self.base_url:
            raise ValueError("INTERNS2_BASE_URL cannot be empty")
        if not self.api_key:
            raise ValueError("INTERNS2_API_KEY cannot be empty; use EMPTY for a local server")
        if self.timeout <= 0:
            raise ValueError("INTERNS2_TIMEOUT must be greater than zero")
        if self.max_retries < 0:
            raise ValueError("INTERNS2_MAX_RETRIES cannot be negative")
        if self.max_tokens <= 0:
            raise ValueError("INTERNS2_MAX_TOKENS must be greater than zero")
        if not 0 <= self.temperature <= 2:
            raise ValueError("INTERNS2_TEMPERATURE must be between 0 and 2")
        if not 0 < self.top_p <= 1:
            raise ValueError("INTERNS2_TOP_P must be greater than 0 and at most 1")
        if self.max_tool_rounds <= 0:
            raise ValueError("INTERNS2_MAX_TOOL_ROUNDS must be greater than zero")
        if self.default_distance_unit != DistanceUnit.MILLIMETER:
            raise ValueError("DEFAULT_DISTANCE_UNIT must be mm in schema version 1.0")
        if self.default_coordinate_frame != CoordinateFrame.ROBOT_BASE:
            raise ValueError(
                "DEFAULT_COORDINATE_FRAME must be robot_base in the first implementation"
            )
        if self.default_relative_step_mm <= 0:
            raise ValueError("DEFAULT_RELATIVE_STEP_MM must be greater than zero")
        if self.entry_tolerance_mm <= 0:
            raise ValueError("ENTRY_TOLERANCE_MM must be greater than zero")
        if self.max_relative_translation_mm <= 0:
            raise ValueError("MAX_TRANSLATION_PER_COMMAND_MM must be greater than zero")
        if self.robot_move_speed_mm_s <= 0:
            raise ValueError("ROBOT_MOVE_SPEED_MM_S must be greater than zero")
        if self.max_robot_speed_mm_s <= 0:
            raise ValueError("MAX_ROBOT_SPEED_MM_S must be greater than zero")
        if self.robot_move_speed_mm_s > self.max_robot_speed_mm_s:
            raise ValueError("ROBOT_MOVE_SPEED_MM_S cannot exceed MAX_ROBOT_SPEED_MM_S")
        if not self.robot_simulation_base_url:
            raise ValueError("ROBOT_SIMULATION_BASE_URL cannot be empty")
        if not self.planner_adapter_base_url:
            raise ValueError("PLANNER_ADAPTER_BASE_URL cannot be empty")
        if self.robot_simulation_http_timeout <= 0:
            raise ValueError("ROBOT_SIMULATION_HTTP_TIMEOUT must be greater than zero")
        if self.robot_simulation_command_timeout <= 0:
            raise ValueError("ROBOT_SIMULATION_COMMAND_TIMEOUT must be greater than zero")
        if self.robot_simulation_poll_interval <= 0:
            raise ValueError("ROBOT_SIMULATION_POLL_INTERVAL must be greater than zero")
        if self.planner_adapter_timeout <= 0:
            raise ValueError("PLANNER_ADAPTER_TIMEOUT must be greater than zero")
        if self.puncture_execution_enabled:
            raise ValueError(
                "PUNCTURE_EXECUTION_ENABLED must remain false: this project does not "
                "implement puncture execution"
            )
