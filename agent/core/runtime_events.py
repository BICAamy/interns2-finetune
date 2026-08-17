"""Build a compact, ordered Step 10 execution timeline for CLI consumers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from surgical_contracts import EventPhase, ToolName

from .orchestrator import OrchestrationResult
from .state_machine import AgentTaskState


@dataclass(frozen=True)
class RuntimeEvent:
    sequence: int
    event: str
    timestamp_ms: int
    status: str
    duration_ms: int | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "sequence": self.sequence,
            "event": self.event,
            "timestamp_ms": self.timestamp_ms,
            "status": self.status,
            "details": self.details,
        }
        if self.duration_ms is not None or self.status == "completed":
            value["duration_ms"] = max(0, self.duration_ms or 0)
        return value


def build_runtime_events(
    *,
    parse_started_ms: int,
    parse_finished_ms: int,
    orchestration: OrchestrationResult | None,
) -> list[RuntimeEvent]:
    """Normalize parser, state-machine, and tool timestamps into one sequence."""

    events: list[RuntimeEvent] = []

    def append(
        event: str,
        timestamp_ms: int,
        status: str,
        *,
        duration_ms: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        events.append(
            RuntimeEvent(
                sequence=len(events) + 1,
                event=event,
                timestamp_ms=timestamp_ms,
                status=status,
                duration_ms=duration_ms,
                details=details or {},
            )
        )

    append(
        "command.parsed",
        parse_finished_ms,
        "completed",
        duration_ms=max(0, parse_finished_ms - parse_started_ms),
    )
    if orchestration is None:
        return events

    state_timestamps = {
        event.to_state: event.timestamp_ms for event in orchestration.state_events
    }
    validated_at = state_timestamps.get(
        AgentTaskState.VALIDATING,
        parse_finished_ms,
    )
    append(
        "command.validated",
        validated_at,
        "completed",
        duration_ms=max(0, validated_at - parse_finished_ms),
    )

    started_at: dict[ToolName, int] = {}
    last_state_query_started_at: int | None = None
    entry_verified_emitted = False
    for tool_event in orchestration.tool_events:
        if (
            tool_event.tool == ToolName.PLANNER_PLAN_PUNCTURE
            and not entry_verified_emitted
            and AgentTaskState.AT_ENTRY in state_timestamps
        ):
            append(
                "robot.entry_verified",
                state_timestamps[AgentTaskState.AT_ENTRY],
                "completed",
                duration_ms=max(
                    0,
                    state_timestamps[AgentTaskState.AT_ENTRY]
                    - (
                        last_state_query_started_at
                        if last_state_query_started_at is not None
                        else state_timestamps[AgentTaskState.AT_ENTRY]
                    ),
                ),
                details={
                    "position_error_mm": orchestration.verified_position_error_mm,
                },
            )
            entry_verified_emitted = True

        event_base = (
            "planner"
            if tool_event.tool == ToolName.PLANNER_PLAN_PUNCTURE
            else tool_event.tool.value
        )
        event_name = f"{event_base}.{tool_event.phase.value}"
        duration_ms = None
        if tool_event.phase == EventPhase.STARTED:
            started_at[tool_event.tool] = tool_event.timestamp_ms
            if tool_event.tool == ToolName.ROBOT_GET_STATE:
                last_state_query_started_at = tool_event.timestamp_ms
        else:
            start = started_at.pop(tool_event.tool, None)
            if start is not None:
                duration_ms = max(0, tool_event.timestamp_ms - start)
        details = (
            {"arguments": tool_event.arguments}
            if tool_event.phase == EventPhase.STARTED
            else {"result": tool_event.result}
        )
        append(
            event_name,
            tool_event.timestamp_ms,
            tool_event.phase.value,
            duration_ms=duration_ms,
            details=details,
        )

    if (
        not entry_verified_emitted
        and AgentTaskState.AT_ENTRY in state_timestamps
    ):
        append(
            "robot.entry_verified",
            state_timestamps[AgentTaskState.AT_ENTRY],
            "completed",
            duration_ms=max(
                0,
                state_timestamps[AgentTaskState.AT_ENTRY]
                - (
                    last_state_query_started_at
                    if last_state_query_started_at is not None
                    else state_timestamps[AgentTaskState.AT_ENTRY]
                ),
            ),
            details={"position_error_mm": orchestration.verified_position_error_mm},
        )

    final_timestamp = (
        orchestration.state_events[-1].timestamp_ms
        if orchestration.state_events
        else parse_finished_ms
    )
    append(
        f"task.{orchestration.final_state.value}",
        final_timestamp,
        "completed"
        if orchestration.final_state
        in {
            AgentTaskState.COMPLETED,
            AgentTaskState.PLAN_READY,
            AgentTaskState.STOPPED,
            AgentTaskState.ESTOP,
        }
        else "failed",
        duration_ms=max(0, final_timestamp - validated_at),
        details={
            "message": orchestration.message,
            "error_code": (
                orchestration.error_code.value if orchestration.error_code else None
            ),
        },
    )
    return events
