"""HTTP and session models exposed by agent-web."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class WebModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SessionStatus(str, Enum):
    READY = "ready"
    PARSING = "parsing"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    CLARIFICATION_REQUIRED = "clarification_required"
    EXECUTING = "executing"
    MOVING_TO_ENTRY = "moving_to_entry"
    VERIFYING_ENTRY = "verifying_entry"
    MOVING_RELATIVE = "moving_relative"
    PLANNING = "planning"
    PLAN_READY = "plan_ready"
    COMPLETED = "completed"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ESTOP = "estop"
    CANCELLED = "cancelled"
    FAILED = "failed"


STATUS_LABELS: dict[SessionStatus, str] = {
    SessionStatus.READY: "等待输入",
    SessionStatus.PARSING: "正在解析指令",
    SessionStatus.AWAITING_CONFIRMATION: "已提取任务，等待医生确认",
    SessionStatus.CLARIFICATION_REQUIRED: "需要补充信息",
    SessionStatus.EXECUTING: "任务已确认，准备执行",
    SessionStatus.MOVING_TO_ENTRY: "正在移动到入点",
    SessionStatus.VERIFYING_ENTRY: "正在复核机械臂入点位置",
    SessionStatus.MOVING_RELATIVE: "正在执行相对移动",
    SessionStatus.PLANNING: "正在调用路径规划工具",
    SessionStatus.PLAN_READY: "路径规划结果已返回；当前版本未执行穿刺",
    SessionStatus.COMPLETED: "机械臂任务已完成；当前版本未执行穿刺",
    SessionStatus.STOPPING: "正在停止机械臂",
    SessionStatus.STOPPED: "机械臂已停止",
    SessionStatus.ESTOP: "机械臂处于急停状态",
    SessionStatus.CANCELLED: "待确认任务已取消",
    SessionStatus.FAILED: "任务失败",
}


class TextCommandRequest(WebModel):
    prompt: str = Field(min_length=1, max_length=8000)
    image_data_url: str | None = Field(default=None, max_length=14_000_000)
    image_name: str | None = Field(default=None, max_length=255)


class SessionSnapshot(WebModel):
    schema_version: Literal["1.0"] = "1.0"
    session_id: str
    revision: int = Field(ge=1)
    status: SessionStatus
    status_label: str
    created_at_ms: int = Field(ge=0)
    updated_at_ms: int = Field(ge=0)
    prompt: str | None = None
    image_name: str | None = None
    pending_confirmation: bool = False
    active_command_id: str | None = None
    raw_model_output: dict[str, Any] | None = None
    normalized_command: dict[str, Any] | None = None
    current_tcp: dict[str, Any] | None = None
    execution_events: list[dict[str, Any]] = Field(default_factory=list)
    orchestration: dict[str, Any] | None = None
    message: str = ""
    error: dict[str, Any] | None = None


class HealthResponse(WebModel):
    status: Literal["healthy"] = "healthy"
    service: Literal["agent-web"] = "agent-web"
    runtime_mode: str
    puncture_execution_enabled: Literal[False] = False
    sessions: int = Field(ge=0)
    downstream: dict[str, str]
