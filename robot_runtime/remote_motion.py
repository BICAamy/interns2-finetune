"""Server-side proposal store for authenticated, web-confirmed remote motion.

The store never emits Huayan ASCII.  It creates immutable high-level
proposals, binds the browser confirmation to their canonical fingerprint and
hands each confirmed proposal to the active Mac session at most once.
"""

from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass
import math
from threading import RLock
import time
from typing import Callable

from surgical_contracts import (
    CommandExecutionStatus,
    CoordinateFrame,
    CoordinateSource,
    DistanceUnit,
    ErrorCode,
    ErrorResponse,
    GatewayCommandFrame,
    GatewayCommandKind,
    LinkState,
    MotionSafetyLimits,
    MoveRelativeRequest,
    MoveRelativeResult,
    Point3D,
    RobotCommandEnvelope,
    RobotCommandKind,
    RobotCommandRecord,
    RobotCommandResult,
    RobotMotionProposal,
    RobotTelemetry,
    SetEnabledRequest,
    SetEnabledResult,
    SourceFreshness,
    ToolStatus,
    command_fingerprint,
)

from .provider import RobotRuntimeServiceError


@dataclass(frozen=True)
class RemoteMotionPolicy:
    tcp_name: str
    ucs_name: str
    max_speed_mm_s: float
    max_step_mm: float
    proposal_ttl_ms: int = 30_000

    def __post_init__(self) -> None:
        numeric = (self.max_speed_mm_s, self.max_step_mm)
        if not self.tcp_name or self.ucs_name != "Base":
            raise ValueError("remote motion requires an explicit TCP and Base UCS")
        if any(not math.isfinite(value) or value <= 0 for value in numeric):
            raise ValueError("remote motion limits must be finite and positive")
        if not 1_000 <= self.proposal_ttl_ms <= 300_000:
            raise ValueError("proposal_ttl_ms must be 1000..300000")


class RemoteMotionStore:
    """Bounded, in-memory command lifecycle with at-most-once dispatch."""

    def __init__(
        self,
        policy: RemoteMotionPolicy,
        *,
        telemetry: Callable[[], RobotTelemetry],
        max_records: int = 1024,
    ) -> None:
        self.policy = policy
        self._telemetry = telemetry
        self._max_records = max_records
        self._lock = RLock()
        self._records: OrderedDict[str, RobotCommandRecord] = OrderedDict()
        self._proposals: dict[str, RobotMotionProposal] = {}
        self._frames: dict[str, GatewayCommandFrame] = {}
        self._pending: deque[str] = deque()
        self._dispatched: set[str] = set()

    @staticmethod
    def _request_key(request: MoveRelativeRequest) -> dict[str, object]:
        return request.model_dump(mode="json")

    def _require_proposable_state(self) -> RobotTelemetry:
        state = self._telemetry()
        links = state.connections
        if (
            state.freshness != SourceFreshness.FRESH
            or state.gateway_session_id is None
            or state.actual_pose_robot_base is None
            or state.actual_pose_robot_base.frame != CoordinateFrame.ROBOT_BASE
            or state.actual_pose_robot_base.unit != DistanceUnit.MILLIMETER
            or state.enabled is not True
            or state.moving is not False
            or state.potentially_moving is not False
            or state.in_position is not True
            or state.vendor_fault is not None
            or state.physical_estop_active is not False
            or state.emergency_stop_circuit_fault is not False
            or state.safeguard_active is not False
            or state.safeguard_circuit_fault is not False
            or any(
                link != LinkState.CONNECTED
                for link in (
                    links.gateway,
                    links.datasheet,
                    links.command_socket,
                    links.controller_box,
                )
            )
        ):
            raise RobotRuntimeServiceError(
                ErrorCode.OPERATION_NOT_ENABLED,
                "real feedback is not ready to create a motion proposal",
                status_code=409,
            )
        return state

    def propose(self, request: MoveRelativeRequest) -> tuple[RobotCommandRecord, bool]:
        translation = tuple(float(value) for value in request.translation_mm)
        distance = math.dist((0.0, 0.0, 0.0), translation)
        if request.frame != CoordinateFrame.ROBOT_BASE:
            raise RobotRuntimeServiceError(
                ErrorCode.INVALID_COORDINATE_FRAME,
                "remote move_relative currently requires robot_base",
                status_code=422,
                command_id=request.command_id,
            )
        if sum(abs(value) > 1e-12 for value in translation) != 1:
            raise RobotRuntimeServiceError(
                ErrorCode.OPERATION_NOT_ENABLED,
                "remote move_relative currently allows one Cartesian axis per proposal",
                status_code=422,
                command_id=request.command_id,
            )
        if distance > self.policy.max_step_mm or request.speed_mm_s > self.policy.max_speed_mm_s:
            raise RobotRuntimeServiceError(
                ErrorCode.OUT_OF_WORKSPACE,
                "proposal exceeds configured remote motion limits",
                status_code=422,
                command_id=request.command_id,
            )
        with self._lock:
            existing = self._records.get(request.command_id)
            if existing is not None:
                if existing.request != self._request_key(request):
                    raise RobotRuntimeServiceError(
                        ErrorCode.COMMAND_CONFLICT,
                        "command_id was already used with different arguments",
                        status_code=409,
                        command_id=request.command_id,
                    )
                return existing.model_copy(deep=True), False
            if len(self._records) >= self._max_records:
                raise RobotRuntimeServiceError(
                    ErrorCode.COMMAND_CONFLICT,
                    "remote motion idempotency ledger is full",
                    status_code=503,
                    command_id=request.command_id,
                )

            state = self._require_proposable_state()
            now_ms = time.time_ns() // 1_000_000
            envelope = RobotCommandEnvelope(
                gateway_session_id=state.gateway_session_id,
                command_id=request.command_id,
                command_kind=GatewayCommandKind.MOVE_RELATIVE,
                created_at_ms=now_ms,
                expires_at_ms=now_ms + self.policy.proposal_ttl_ms,
                based_on_robot_state_sequence=state.sequence,
                expected_start_pose_robot_base=state.actual_pose_robot_base,
                expected_tcp_name=self.policy.tcp_name,
                expected_ucs_name=self.policy.ucs_name,
                payload=request,
                safety_limits=MotionSafetyLimits(
                    max_speed_mm_s=self.policy.max_speed_mm_s,
                    max_step_mm=self.policy.max_step_mm,
                ),
                operator_confirmation_id=(
                    "web-" + request.command_id
                    if len(request.command_id) <= 124
                    else "web-" + command_fingerprint_from_id(request.command_id)
                ),
            )
            proposal = RobotMotionProposal(
                command_id=request.command_id,
                fingerprint=command_fingerprint(envelope),
                envelope=envelope,
            )
            record = RobotCommandRecord(
                command_id=request.command_id,
                kind=RobotCommandKind.MOVE_RELATIVE,
                status=CommandExecutionStatus.QUEUED,
                submitted_at_ms=now_ms,
                updated_at_ms=now_ms,
                request=self._request_key(request),
                result={"proposal": proposal.model_dump(mode="json")},
            )
            self._records[request.command_id] = record
            self._proposals[request.command_id] = proposal
            self._frames[request.command_id] = GatewayCommandFrame(
                fingerprint=proposal.fingerprint,
                envelope=envelope,
            )
            return record.model_copy(deep=True), True

    def set_enabled(self, request: SetEnabledRequest) -> tuple[RobotCommandRecord, bool]:
        """Queue one authenticated group enable/disable request from the web UI."""
        with self._lock:
            existing = self._records.get(request.command_id)
            request_key = request.model_dump(mode="json")
            if existing is not None:
                if existing.request != request_key:
                    raise RobotRuntimeServiceError(
                        ErrorCode.COMMAND_CONFLICT,
                        "command_id was already used with different arguments",
                        status_code=409,
                        command_id=request.command_id,
                    )
                return existing.model_copy(deep=True), False
            if len(self._records) >= self._max_records:
                raise RobotRuntimeServiceError(
                    ErrorCode.COMMAND_CONFLICT,
                    "remote command idempotency ledger is full",
                    status_code=503,
                    command_id=request.command_id,
                )
            if any(
                record.status == CommandExecutionStatus.RUNNING
                for record in self._records.values()
            ):
                raise RobotRuntimeServiceError(
                    ErrorCode.COMMAND_CONFLICT,
                    "another remote robot command is active",
                    status_code=409,
                    command_id=request.command_id,
                )
            state = self._telemetry()
            links = state.connections
            if (
                state.freshness != SourceFreshness.FRESH
                or state.gateway_session_id is None
                or state.vendor_fault is not None
                or state.physical_estop_active is not False
                or state.emergency_stop_circuit_fault is not False
                or state.safeguard_active is not False
                or state.safeguard_circuit_fault is not False
                or any(
                    link != LinkState.CONNECTED
                    for link in (
                        links.gateway, links.datasheet,
                        links.command_socket, links.controller_box,
                    )
                )
            ):
                raise RobotRuntimeServiceError(
                    ErrorCode.OPERATION_NOT_ENABLED,
                    "real feedback is not ready to change robot enable state",
                    status_code=409,
                    command_id=request.command_id,
                )
            if not request.enabled and (
                state.moving is not False
                or state.potentially_moving is not False
                or state.in_position is not True
            ):
                raise RobotRuntimeServiceError(
                    ErrorCode.OPERATION_NOT_ENABLED,
                    "robot must be confirmed stationary before disable",
                    status_code=409,
                    command_id=request.command_id,
                )
            now_ms = time.time_ns() // 1_000_000
            if state.enabled is request.enabled:
                result = SetEnabledResult(
                    command_id=request.command_id,
                    status=ToolStatus.SUCCESS,
                    requested_enabled=request.enabled,
                    confirmed_enabled=request.enabled,
                    message="Robot feedback already reports the requested enable state",
                )
                record = RobotCommandRecord(
                    command_id=request.command_id,
                    kind=RobotCommandKind.SET_ENABLED,
                    status=CommandExecutionStatus.SUCCEEDED,
                    submitted_at_ms=now_ms,
                    updated_at_ms=now_ms,
                    request=request_key,
                    result=result.model_dump(mode="json"),
                )
                self._records[request.command_id] = record
                return record.model_copy(deep=True), True
            envelope = RobotCommandEnvelope(
                gateway_session_id=state.gateway_session_id,
                command_id=request.command_id,
                command_kind=GatewayCommandKind.SET_ENABLED,
                created_at_ms=now_ms,
                expires_at_ms=now_ms + self.policy.proposal_ttl_ms,
                based_on_robot_state_sequence=state.sequence,
                payload=request,
            )
            frame = GatewayCommandFrame(
                fingerprint=command_fingerprint(envelope),
                envelope=envelope,
            )
            record = RobotCommandRecord(
                command_id=request.command_id,
                kind=RobotCommandKind.SET_ENABLED,
                status=CommandExecutionStatus.RUNNING,
                submitted_at_ms=now_ms,
                updated_at_ms=now_ms,
                request=request_key,
            )
            self._records[request.command_id] = record
            self._frames[request.command_id] = frame
            self._pending.append(request.command_id)
            return record.model_copy(deep=True), True

    def confirm(self, command_id: str, fingerprint: str) -> RobotCommandRecord:
        with self._lock:
            record = self._get_locked(command_id)
            proposal = self._proposals.get(command_id)
            if proposal is None:
                raise RobotRuntimeServiceError(
                    ErrorCode.OPERATION_NOT_ENABLED,
                    "only a motion proposal can be confirmed by fingerprint",
                    status_code=409,
                    command_id=command_id,
                )
            if fingerprint != proposal.fingerprint:
                raise RobotRuntimeServiceError(
                    ErrorCode.COMMAND_CONFLICT,
                    "web confirmation fingerprint does not match proposal",
                    status_code=409,
                    command_id=command_id,
                )
            if record.status != CommandExecutionStatus.QUEUED:
                return record.model_copy(deep=True)
            if any(
                other_id != command_id
                and other.status == CommandExecutionStatus.RUNNING
                for other_id, other in self._records.items()
            ):
                raise RobotRuntimeServiceError(
                    ErrorCode.COMMAND_CONFLICT,
                    "another remote motion command is active",
                    status_code=409,
                    command_id=command_id,
                )
            now_ms = time.time_ns() // 1_000_000
            if now_ms >= proposal.envelope.expires_at_ms:
                self._fail_locked(command_id, ErrorCode.COMMAND_EXPIRED, "proposal expired before confirmation")
                return self._records[command_id].model_copy(deep=True)
            state = self._require_proposable_state()
            if state.gateway_session_id != proposal.envelope.gateway_session_id:
                self._fail_locked(command_id, ErrorCode.COMMAND_EXPIRED, "gateway session changed before confirmation")
                return self._records[command_id].model_copy(deep=True)
            confirmed = proposal.model_copy(update={"web_confirmed": True})
            self._proposals[command_id] = confirmed
            self._records[command_id] = record.model_copy(update={
                "status": CommandExecutionStatus.RUNNING,
                "updated_at_ms": now_ms,
                "result": {"proposal": confirmed.model_dump(mode="json")},
            })
            self._pending.append(command_id)
            return self._records[command_id].model_copy(deep=True)

    def take_for_gateway(self, session_id: str) -> GatewayCommandFrame | None:
        with self._lock:
            while self._pending:
                command_id = self._pending.popleft()
                record = self._records.get(command_id)
                frame = self._frames.get(command_id)
                if record is None or frame is None or record.status != CommandExecutionStatus.RUNNING:
                    continue
                if command_id in self._dispatched:
                    continue
                if frame.envelope.gateway_session_id != session_id:
                    self._fail_locked(
                        command_id, ErrorCode.COMMAND_EXPIRED,
                        "proposal belongs to an inactive gateway session",
                    )
                    continue
                self._dispatched.add(command_id)
                return frame.model_copy(deep=True)
        return None

    def finish(self, fingerprint: str, result: RobotCommandResult) -> None:
        with self._lock:
            record = self._get_locked(result.command_id)
            frame = self._frames[result.command_id]
            if (
                record.status != CommandExecutionStatus.RUNNING
                or result.command_id not in self._dispatched
                or fingerprint != frame.fingerprint
                or result.gateway_session_id != frame.envelope.gateway_session_id
                or result.command_kind != frame.envelope.command_kind
            ):
                raise RobotRuntimeServiceError(
                    ErrorCode.COMMAND_CONFLICT,
                    "gateway result does not match the dispatched proposal",
                    status_code=409,
                    command_id=result.command_id,
                )
            now_ms = time.time_ns() // 1_000_000
            if (
                result.command_kind == GatewayCommandKind.SET_ENABLED
                and result.status == ToolStatus.SUCCESS
            ):
                requested = frame.envelope.payload
                assert isinstance(requested, SetEnabledRequest)
                if result.confirmed_enabled is not requested.enabled:
                    raise RobotRuntimeServiceError(
                        ErrorCode.INTERNAL_ERROR,
                        "Mac enable result disagrees with the requested state",
                        command_id=result.command_id,
                    )
                payload = SetEnabledResult(
                    command_id=result.command_id,
                    status=ToolStatus.SUCCESS,
                    requested_enabled=requested.enabled,
                    confirmed_enabled=result.confirmed_enabled,
                    message="10003 and a newer 10004 frame confirmed the requested state",
                )
                status = CommandExecutionStatus.SUCCEEDED
                error = None
            elif result.status == ToolStatus.SUCCESS:
                pose = result.final_pose_robot_base
                if pose is None:
                    raise RobotRuntimeServiceError(
                        ErrorCode.INTERNAL_ERROR,
                        "successful gateway motion result is missing actual final pose",
                        command_id=result.command_id,
                    )
                payload = MoveRelativeResult(
                    command_id=result.command_id,
                    status=ToolStatus.SUCCESS,
                    completed=True,
                    final_tcp_position=Point3D(
                        x=pose.translation_mm[0],
                        y=pose.translation_mm[1],
                        z=pose.translation_mm[2],
                        frame=CoordinateFrame.ROBOT_BASE,
                        unit=DistanceUnit.MILLIMETER,
                        source=CoordinateSource.STRUCTURED_DATA,
                    ),
                    trajectory_id=result.controller_waypoint_id,
                    message="Mac confirmed arrival from actual controller feedback",
                )
                status = CommandExecutionStatus.SUCCEEDED
                error = None
            else:
                code = result.error_code or ErrorCode.INTERNAL_ERROR
                payload = None
                status = CommandExecutionStatus.FAILED
                error = ErrorResponse(
                    code=code,
                    command_id=result.command_id,
                    message="Mac rejected or failed the dispatched robot command",
                )
            self._records[result.command_id] = record.model_copy(update={
                "status": status,
                "updated_at_ms": now_ms,
                "result": None if payload is None else payload.model_dump(mode="json"),
                "error": error,
            })

    def gateway_disconnected(self, session_id: str) -> None:
        """A dispatched motion has unknown transport outcome and is never replayed."""
        with self._lock:
            for command_id in tuple(self._dispatched):
                frame = self._frames.get(command_id)
                record = self._records.get(command_id)
                if (
                    frame is not None
                    and record is not None
                    and frame.envelope.gateway_session_id == session_id
                    and record.status == CommandExecutionStatus.RUNNING
                ):
                    self._fail_locked(
                        command_id,
                        ErrorCode.INTERNAL_ERROR,
                        "gateway disconnected after dispatch; outcome unknown and command will not replay",
                    )

    def get(self, command_id: str) -> RobotCommandRecord:
        with self._lock:
            return self._get_locked(command_id).model_copy(deep=True)

    def _get_locked(self, command_id: str) -> RobotCommandRecord:
        record = self._records.get(command_id)
        if record is None:
            raise RobotRuntimeServiceError(
                ErrorCode.COMMAND_NOT_FOUND,
                f"unknown command_id: {command_id}",
                status_code=404,
                command_id=command_id,
            )
        return record

    def _fail_locked(self, command_id: str, code: ErrorCode, message: str) -> None:
        record = self._records[command_id]
        self._records[command_id] = record.model_copy(update={
            "status": CommandExecutionStatus.FAILED,
            "updated_at_ms": time.time_ns() // 1_000_000,
            "result": None,
            "error": ErrorResponse(code=code, command_id=command_id, message=message),
        })


def command_fingerprint_from_id(command_id: str) -> str:
    """Keep an operator confirmation identifier within the wire contract bound."""
    import hashlib

    return hashlib.sha256(command_id.encode("utf-8")).hexdigest()[:32]
