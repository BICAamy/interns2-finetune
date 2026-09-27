"""Observe-only Mac state and bounded rejection/idempotency memory."""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict, deque
from dataclasses import dataclass
from enum import Enum
from threading import RLock

from surgical_contracts import (
    ErrorCode,
    GatewayAcknowledgementStatus,
    RobotCommandAcknowledgement,
    RobotCommandEnvelope,
)

from .huayan.models import DatasheetSample


class EdgeMode(str, Enum):
    DISCONNECTED = "disconnected" # Mac 还没连上服务器
    OBSERVE_ONLY = "observe-only"
    DEGRADED = "degraded" # 有1条连接出现问题
    FAULT = "fault" # 发现安全/协议异常


@dataclass(frozen=True)
class SampleRecord:
    # 给一帧 DatasheetSample 再套一个我们自己的编号。
    sequence: int # sequence 就是编号，也就是mac收到并处理的第几帧状态
    sample: DatasheetSample


class EdgeState:
    """A one-slot pose buffer plus a bounded, non-dropping alert queue."""

    def __init__(self, *, max_events: int = 256) -> None:
        if max_events < 1:
            raise ValueError("max_events must be positive")
        self._lock = RLock()
        self._latest: SampleRecord | None = None # 最新一帧的机械臂状态，这是会被覆盖的
        self._events: deque[SampleRecord] = deque() # 记录不能被覆盖掉的重要事件。
        self._max_events = max_events # 最多允许积压的重要事件数。
        self._sequence = 0
        self.cloud_connected = False # Mac ↔ Server WebSocket 是否正常
        self.command_connected = False # Mac ↔ E05-Pro:10003 是否正常
        self.datasheet_connected = False # Mac ↔ E05-Pro:10004 是否正常
        self.fault = False # 有没有发生严重错误，需要整个 gateway 停止正常工作
        self.session_id: str | None = None # 当前 Mac ↔ Server 的 gateway session ID

    @property
    def mode(self) -> EdgeMode:
        # 计算当前mac网关所看到的机械臂的状态
        with self._lock:
            if self.fault:
                return EdgeMode.FAULT
            if not self.cloud_connected:
                return EdgeMode.DISCONNECTED
            if not self.command_connected or not self.datasheet_connected:
                return EdgeMode.DEGRADED
            return EdgeMode.OBSERVE_ONLY

    @property
    def motion_enabled(self) -> bool:
        # 这里现在硬编码了不允许移动
        return False

    def start_cloud_session(self, session_id: str) -> None:
        # Mac 成功连上 server 以后更新状态。
        with self._lock:
            self.cloud_connected = True
            self.session_id = session_id

    def cloud_lost(self) -> None:
        # 断开连接之后更新状态
        with self._lock:
            self.cloud_connected = False
            self.session_id = None

    def observe(self, sample: DatasheetSample) -> SampleRecord:
        # 10004 每收到一帧 DataSheet，就把它交给 EdgeState.observe()
        with self._lock:
            self._sequence += 1
            record = SampleRecord(self._sequence, sample)
            # previous 是上一帧率，接下来要拿上一帧与这一帧进行比较
            previous = self._latest.sample if self._latest else None
            # 这里的changed得到的是个bool值，为true就是改变了：要么上一帧为空，要么previous不等于当前帧sample
            changed = previous is None or (
                previous.fsm_code, previous.enabled, previous.moving,
                previous.paused, previous.error_code, previous.error_axis,
            ) != (
                sample.fsm_code, sample.enabled, sample.moving,
                sample.paused, sample.error_code, sample.error_axis,
            )
            if changed or sample.error_code or any(sample.axis_error_codes):
                if len(self._events) >= self._max_events:
                    self.fault = True
                    raise RuntimeError("edge alert queue full; refusing to discard safety changes")
                self._events.append(record)
            self._latest = record # 更新最新机械臂状态
            self.datasheet_connected = True
            return record

    def snapshot(self) -> tuple[SampleRecord | None, tuple[SampleRecord, ...]]:
        # snapshot的作用：main.py 想上传数据时，给它当前“最新状态 + 尚未确认的重要事件”。
        with self._lock:
            return self._latest, tuple(self._events)

    def acknowledged_through(self, sequence: int) -> None:
        with self._lock:
            while self._events and self._events[0].sequence <= sequence:
                self._events.popleft()


class RejectOnlyLedger:
    """No command can be accepted in Step 5; duplicate IDs remain deterministic."""

    def __init__(self, *, max_records: int = 1024) -> None:
        if max_records < 1:
            raise ValueError("max_records must be positive")
        self._lock = RLock()
        self._max_records = max_records
        self._records: OrderedDict[str, tuple[str, RobotCommandAcknowledgement]] = OrderedDict()

    def reject(self, envelope: RobotCommandEnvelope, *, active_session_id: str | None) -> RobotCommandAcknowledgement:
        canonical = json.dumps(envelope.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        with self._lock:
            existing = self._records.get(envelope.command_id)
            if existing is not None:
                code = (
                    existing[1].error_code if existing[0] == fingerprint
                    else ErrorCode.COMMAND_CONFLICT
                )
            else:
                code = (
                    ErrorCode.OPERATION_NOT_ENABLED
                    if envelope.gateway_session_id == active_session_id and active_session_id is not None
                    else ErrorCode.COMMAND_EXPIRED
                )
            result = RobotCommandAcknowledgement(
                gateway_session_id=envelope.gateway_session_id,
                command_id=envelope.command_id,
                status=GatewayAcknowledgementStatus.REJECTED,
                error_code=code,
            )
            if existing is None:
                self._records[envelope.command_id] = (fingerprint, result)
                if len(self._records) > self._max_records:
                    self._records.popitem(last=False)
            return result
