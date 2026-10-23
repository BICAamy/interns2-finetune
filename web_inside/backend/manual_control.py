"""Independent, leased direct motion for the internal control panels.

Manual and gesture control share this single-owner lease.  Real motion still
uses the normal robot-runtime proposal boundary, but the internal direct-control
lease confirms each short-lived proposal itself; it never enters the text
parser or the browser task-confirmation flow.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import math
import secrets
import time
from typing import Literal, TYPE_CHECKING
from uuid import uuid4
import httpx

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat
from surgical_contracts import (
    MotionSequenceStep, MotionStepKind, MoveSequenceRequest, RuntimeMode, ToolStatus,
)
from simulation.runtime_config import load_simulation_motion_policy
from .sessions import SessionConflict

if TYPE_CHECKING:
    from .runtime import WebRuntime

LEASE_SECONDS = 2.0
HOLD_SECONDS = 0.45
GESTURE_HOLD_SECONDS = 2.0
MAX_CONTINUOUS_WAYPOINTS = 128
BUSY = {"parsing", "awaiting_confirmation", "executing", "moving_to_entry",
        "verifying_entry", "moving_relative", "planning", "stopping", "paused"}


class LeaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=16, max_length=128)


class ManualInput(LeaseRequest):
    sequence: int = Field(ge=1)
    kind: Literal["translation", "rotation", "joint"] | None = None
    axis: int = Field(default=0, ge=0, le=5)
    direction: Literal[-1, 1] = 1
    amount: FiniteFloat = Field(default=10, gt=0)
    speed_scale: FiniteFloat = Field(default=1, gt=0, le=1)
    continuous: bool = False


@dataclass
class Lease:
    session_id: str
    token: str
    expires: float
    mode: RuntimeMode = RuntimeMode.SIMULATION
    owner: Literal["manual", "gesture"] = "manual"
    sequence: int = 0
    hold_until: float = 0
    desired: ManualInput | None = None
    task: asyncio.Task | None = None
    stopping: bool = False
    active: bool = False
    fault: str | None = None
    external_stopped: bool = False
    submitted: asyncio.Event = field(default_factory=asyncio.Event)
    stop_done: asyncio.Event = field(default_factory=asyncio.Event)
    transport: object | None = None


class ManualTransport:
    """Submit/ack and completion are separate, so stop cannot overtake submit."""
    def __init__(self, base_url: str, *, confirm_proposals: bool = False):
        self.client = httpx.AsyncClient(base_url=base_url, timeout=2, trust_env=False)
        self.confirm_proposals = confirm_proposals

    async def submit(self, command: MoveSequenceRequest) -> dict:
        response = await self.client.post('/v1/commands/move-sequence', json=command.model_dump(mode='json'))
        response.raise_for_status()
        record = response.json()
        if self.confirm_proposals and record.get('status') == 'queued':
            proposal = (record.get('result') or {}).get('proposal') or {}
            fingerprint = proposal.get('fingerprint')
            if not isinstance(fingerprint, str) or not fingerprint:
                raise RuntimeError('真机点动 proposal 缺少 fingerprint')
            response = await self.client.post(
                f'/v1/commands/{command.command_id}/confirm',
                json={'fingerprint': fingerprint},
            )
            response.raise_for_status()
            record = response.json()
        return record

    async def record(self, command_id: str) -> dict:
        response = await self.client.get('/v1/commands/'+command_id)
        response.raise_for_status()
        return response.json()

    async def stop(self) -> None:
        command_id = 'manual-stop-'+uuid4().hex
        response = await self.client.post('/v1/commands/stop', json={'command_id':command_id})
        response.raise_for_status()
        deadline = time.monotonic()+5
        while time.monotonic()<deadline:
            record = await self.record(command_id)
            if record['status']=='succeeded': return
            if record['status'] in {'failed','rejected','cancelled'}:
                detail = (record.get('error') or {}).get('message')
                raise RuntimeError(
                    '停止请求未成功完成'
                    + (f'：{detail}' if isinstance(detail, str) and detail else '')
                )
            await asyncio.sleep(.03)
        raise TimeoutError('等待仿真停止反馈超时')

    async def close(self):
        await self.client.aclose()


class ManualController:
    def __init__(self, runtime: WebRuntime, *, clock=time.monotonic, transport_factory=None):
        self.runtime = runtime
        self.clock = clock
        self.lease: Lease | None = None
        self.watchdog: asyncio.Task | None = None
        self.policy = load_simulation_motion_policy()
        self.transport_factory = transport_factory

    def _transport(self, mode: RuntimeMode):
        if self.transport_factory is not None:
            # Test/dedicated transports intentionally keep the historical
            # zero-argument factory contract.
            return self.transport_factory()
        robot = self.runtime._robots.get(mode)
        base_url = getattr(robot, 'base_url', None)
        if not isinstance(base_url, str) or not base_url:
            raise SessionConflict(f"{mode.value} 运行时没有可用的控制地址")
        return ManualTransport(
            base_url,
            confirm_proposals=mode == RuntimeMode.REAL,
        )

    def _policy_values(self, mode: RuntimeMode) -> dict[str, float]:
        real_config = getattr(self.runtime, '_real_config', None)
        if mode == RuntimeMode.REAL and real_config is not None:
            real = real_config
            return {
                'translation_step': float(real.limits.max_step_mm),
                'rotation_step': float(real.limits.max_rotation_deg),
                'translation_speed': float(real.motion.speed_mm_s),
                'angular_speed': float(real.motion.joint_speed_deg_s),
                'angular_acceleration': float(real.motion.joint_acceleration_deg_s2),
                'default_step': float(real.motion.default_relative_step_mm),
                'continuous_lookahead': float(
                    real.motion.direct_control_lookahead_mm
                    or real.limits.max_step_mm
                ),
            }
        return {
            'translation_step': float(self.policy.max_relative_translation_mm),
            'rotation_step': float(self.policy.max_rotation_deg),
            'translation_speed': float(self.policy.move_speed_mm_s),
            'angular_speed': float(self.policy.joint_speed_deg_s),
            'angular_acceleration': float(self.policy.joint_acceleration_deg_s2),
            'default_step': float(self.policy.default_relative_step_mm),
            'continuous_lookahead': float(self.policy.direct_control_lookahead_mm),
        }

    def default_translation_step(self, session_id: str) -> float:
        return self._policy_values(self._mode(session_id))['default_step']

    def assert_task_allowed(self, mode: RuntimeMode) -> None:
        # Called inside SessionStore.mutate's RLock, also held during acquisition.
        if self.lease is not None:
            label = "手势" if self.lease.owner == "gesture" else "手动"
            raise SessionConflict(f"机械臂正在由{label}面板控制，请先退出该控制模式")

    def _mode(self, session_id: str) -> RuntimeMode:
        return self.runtime._session_mode(session_id)

    def _owned(self, session_id: str, token: str) -> Lease:
        lease = self.lease
        if (lease is None or lease.session_id != session_id
                or not secrets.compare_digest(lease.token, token)):
            raise SessionConflict("手动控制权已失效，请重新接管")
        return lease

    def _busy(self, mode: RuntimeMode) -> bool:
        return any(r.robot_mode == mode and
                   (r.status.value in BUSY or r.pending_command is not None)
                   for r in self.runtime.store._records.values())

    def status(self, session_id: str) -> dict:
        mode = self._mode(session_id)
        lease = self.lease
        limits = self._policy_values(mode)
        available = mode in self.runtime._robots
        return {
            "available": available,
            "mode": mode.value,
            "reason": "" if available else f"{mode.value} 运行时未启动",
            "occupied": lease is not None,
            "owned_by_session": lease is not None and lease.session_id == session_id,
            "owner": lease.owner if lease else None,
            "moving": bool(lease and lease.active),
            "stopping": bool(lease and lease.stopping),
            "fault": lease.fault if lease else None,
            "limits": {
                "translation_step": limits['translation_step'],
                "rotation_step": limits['rotation_step'],
                "translation_speed": limits['translation_speed'],
                "angular_speed": limits['angular_speed'],
            },
        }

    async def acquire(
        self,
        session_id: str,
        *,
        owner: Literal["manual", "gesture"] = "manual",
    ) -> dict:
        mode = self._mode(session_id)
        if mode not in self.runtime._robots:
            raise SessionConflict(self.status(session_id)["reason"])
        with self.runtime.store._lock:
            if self.lease is not None:
                raise SessionConflict("机械臂已有手动控制者，请等待其释放")
            if self._busy(mode):
                raise SessionConflict("已有文本或手势任务待确认/执行，不能接管手动控制")
            lease = Lease(
                session_id,
                secrets.token_urlsafe(32),
                self.clock()+LEASE_SECONDS,
                mode=mode,
                owner=owner,
            )
            self.lease = lease
        try:
            view = await asyncio.to_thread(self.runtime.get_robot_telemetry, session_id)
            if not view.connected or view.estop or view.motion_state in {"moving", "estop"}:
                raise SessionConflict("机械臂未连接、尚未静止或处于急停状态，不能接管")
            if mode == RuntimeMode.REAL and view.enabled is not True:
                raise SessionConflict("真实机械臂尚未使能，不能接管直接控制")
            if self._mode(session_id) != mode:
                raise SessionConflict("接管期间运行模式已改变")
            lease.transport = self._transport(mode)
        except Exception:
            self.lease = None
            raise
        if self.watchdog is None or self.watchdog.done():
            self.watchdog = asyncio.create_task(self._watch())
        return {**self.status(session_id), "token": lease.token}

    async def heartbeat(self, session_id: str, token: str) -> dict:
        lease = self._owned(session_id, token)
        if self.clock() > lease.expires:
            await self.release(session_id, token)
            raise SessionConflict("控制心跳超时，请重新接管")
        lease.expires = self.clock()+LEASE_SECONDS
        return self.status(session_id)

    async def input(self, session_id: str, command: ManualInput) -> dict:
        lease = self._owned(session_id, command.token)
        if self.clock() > lease.expires:
            await self.release(session_id, command.token)
            raise SessionConflict("控制心跳超时")
        if command.sequence <= lease.sequence:
            raise SessionConflict("过期或重复的手柄输入已拒绝")
        lease.sequence = command.sequence
        if command.kind is None:
            await self._stop(lease)
            return self.status(session_id)
        if lease.external_stopped:
            raise SessionConflict("直接控制已被停止/急停，请退出面板后重新接管")
        if lease.fault and not lease.stopping:
            await self._recover_motion_fault_if_stationary(lease)
        if lease.fault or lease.stopping:
            detail = lease.fault or "停止操作仍在进行"
            raise SessionConflict(f"上次动作尚未安全恢复：{detail}")
        if self._mode(session_id) != lease.mode:
            await self._stop(lease)
            raise SessionConflict("模式已变化，手动输入已停止")
        if command.kind != "joint" and command.axis > 2:
            raise HTTPException(422, "XYZ/姿态轴只能为 0、1、2")
        limits = self._policy_values(lease.mode)
        maximum = (limits['translation_step']
                   if command.kind == "translation" else limits['rotation_step'])
        if command.amount > maximum:
            raise HTTPException(422, "点动步长超出当前配置限制")
        if lease.desired is not None and lease.active:
            old = lease.desired
            if (old.kind, old.axis, old.direction) != (command.kind, command.axis, command.direction):
                await self._stop(lease)
                raise SessionConflict("改变运动方向前请先松开控制")
        lease.desired = command
        lease.hold_until = self.clock()+(
            GESTURE_HOLD_SECONDS if lease.owner == "gesture" else HOLD_SECONDS
        )
        if lease.task is None or lease.task.done():
            lease.task = asyncio.create_task(self._run(lease))
        return self.status(session_id)

    async def _recover_motion_fault_if_stationary(self, lease: Lease) -> bool:
        """Clear a per-step failure only after fresh telemetry proves safety.

        Direct gesture/manual motion may reach a kinematic boundary and have
        one WayPoint rejected.  That individual step must not permanently
        poison the control lease.  A genuinely unconfirmed stop remains
        latched and can only be released through the confirmed stop path.
        """

        if (
            not lease.fault
            or lease.fault.startswith("停止未确认")
            or lease.active
            or lease.stopping
        ):
            return False
        try:
            view = await asyncio.to_thread(
                self.runtime.get_robot_telemetry,
                lease.session_id,
            )
        except Exception:
            return False
        stationary = bool(
            self._mode(lease.session_id) == lease.mode
            and view.connected
            and not view.estop
            and getattr(view, "freshness", None) == "fresh"
            and getattr(view, "moving", None) is False
            and getattr(view, "in_position", None) is True
            and view.motion_state not in {"moving", "paused", "estop"}
            and getattr(view, "vendor_fault", None) is None
            and getattr(view, "emergency_stop_circuit_fault", False) is not True
            and getattr(view, "safeguard_active", False) is not True
            and getattr(view, "safeguard_circuit_fault", False) is not True
            and (lease.mode != RuntimeMode.REAL or view.enabled is True)
        )
        if stationary:
            lease.fault = None
            return True
        return False

    def _request(
        self,
        command: ManualInput,
        mode: RuntimeMode = RuntimeMode.SIMULATION,
        *,
        translation_amounts: tuple[float, ...] | None = None,
    ) -> MoveSequenceRequest:
        amount = command.amount
        limits = self._policy_values(mode)
        speed = limits['translation_speed'] * command.speed_scale
        angular = limits['angular_speed'] * command.speed_scale
        # Honor the chosen finite increment (up to the manual/policy limit).
        # Only one segment is in flight; release/watchdog interrupts it through
        # the same acknowledged stop path rather than shrinking every segment.
        value = command.direction * amount
        if command.kind == "translation":
            steps = []
            for segment_amount in translation_amounts or (amount,):
                xyz = [0.0, 0.0, 0.0]
                xyz[command.axis] = command.direction * segment_amount
                steps.append(MotionSequenceStep(
                    kind=MotionStepKind.CARTESIAN_RELATIVE,
                    translation_mm=tuple(xyz),
                ))
        elif command.kind == "rotation":
            steps = [MotionSequenceStep(
                kind=MotionStepKind.TCP_ROTATION_RELATIVE,
                rotation_axis=("x", "y", "z")[command.axis],
                rotation_deg=value,
            )]
        else:
            steps = [MotionSequenceStep(
                kind=MotionStepKind.JOINT_RELATIVE,
                joint_index=command.axis+1,
                rotation_deg=value,
            )]
        return MoveSequenceRequest(command_id=f"manual-{uuid4().hex}", steps=tuple(steps),
                                   translation_speed_mm_s=speed, joint_speed_deg_s=angular,
                                   joint_acceleration_deg_s2=limits['angular_acceleration'])

    async def _continuous_translation_amounts(
        self,
        lease: Lease,
        command: ManualInput,
    ) -> tuple[float, ...] | None:
        """Build one blended real-robot hold without enlarging its first jog.

        A real MoveSequence proposal has a non-trivial confirmation/completion
        round trip. Repeating one short proposal therefore makes a held key or
        gesture stop at every increment. Queue collinear increments in one
        controller sequence instead: the existing gateway gives intermediate
        points a bounded blend radius, while key-up/gesture-loss still cancels
        the active sequence through the confirmed stop path.

        The first segment remains exactly the operator-selected increment, and
        pointer/key release still enters the existing acknowledged stop path.
        The complete batch is clipped to the configured direct-control
        look-ahead, max_step_mm, and the Base-axis workspace boundary.
        """

        if (
            lease.mode != RuntimeMode.REAL
            or not command.continuous
            or command.kind != "translation"
        ):
            return None
        try:
            view = await asyncio.to_thread(
                self.runtime.get_robot_telemetry,
                lease.session_id,
            )
            actual = getattr(view, "actual_tcp_robot_base", None)
            point = actual.get("translation_mm") if isinstance(actual, dict) else None
            if point is None:
                tcp = getattr(view, "current_tcp", None)
                if tcp is not None:
                    point = (tcp.x, tcp.y, tcp.z)
            if point is None or len(point) != 3:
                return None

            real = getattr(self.runtime, "_real_config", None)
            if real is not None:
                low = tuple(float(value) for value in real.limits.workspace_low_mm)
                high = tuple(float(value) for value in real.limits.workspace_high_mm)
                margin = float(real.arrival.position_tolerance_mm)
            else:
                low = self.policy.workspace_low_mm
                high = self.policy.workspace_high_mm
                margin = float(self.policy.entry_tolerance_mm)
            coordinate = float(point[command.axis])
            available = (
                high[command.axis] - margin - coordinate
                if command.direction > 0
                else coordinate - (low[command.axis] + margin)
            )
            maximum = self._policy_values(lease.mode)["translation_step"]
            lookahead = self._policy_values(lease.mode)["continuous_lookahead"]
            travel = min(float(maximum), float(lookahead), available)
            if not math.isfinite(travel) or travel <= margin:
                return ()

            first = min(float(command.amount), travel)
            amounts = [first]
            remaining = travel - first
            cruise = max(
                float(command.amount),
                float(self._policy_values(lease.mode)["default_step"]),
            )
            while remaining > margin and len(amounts) < MAX_CONTINUOUS_WAYPOINTS:
                segment = min(cruise, remaining)
                amounts.append(segment)
                remaining -= segment
            return tuple(amounts)
        except (AttributeError, KeyError, TypeError, ValueError):
            # Missing telemetry must not expand a point jog. Falling back to
            # one finite increment preserves the previous fail-closed behavior.
            return None

    async def _run(self, lease: Lease) -> None:
        try:
            while self.lease is lease and lease.desired is not None and not lease.stopping:
                command = lease.desired
                if self.clock() >= min(lease.expires, lease.hold_until):
                    lease.desired = None; break
                lease.active = True
                lease.submitted.clear()
                translation_amounts = await self._continuous_translation_amounts(
                    lease, command,
                )
                if translation_amounts == ():
                    lease.desired = None
                    break
                request = self._request(
                    command,
                    lease.mode,
                    translation_amounts=translation_amounts,
                )
                try:
                    record = await lease.transport.submit(request)
                finally:
                    lease.submitted.set()
                if lease.stopping or lease.desired is None:
                    break
                deadline = self.clock()+10
                while record['status'] in {'queued','running'} and not lease.stopping:
                    if self.clock()>deadline: raise TimeoutError('点动命令完成超时')
                    await asyncio.sleep(.03)
                    record = await lease.transport.record(request.command_id)
                if lease.stopping: break
                if record['status'] != 'succeeded':
                    lease.fault = str((record.get('error') or {}).get('message','点动未完成'))
                    lease.desired = None; break
                if not command.continuous:
                    lease.desired = None; break
                await asyncio.sleep(0.02)
        except Exception as error:
            if not lease.stopping:
                lease.fault = str(error)[:240]
                try:
                    await lease.transport.stop()
                except Exception as stop_error:
                    lease.fault = '停止未确认：'+str(stop_error)[:160]
            lease.desired = None
        finally:
            lease.active = False

    async def _stop(self, lease: Lease) -> None:
        lease.desired = None; lease.hold_until = 0
        if lease.stopping:
            await lease.stop_done.wait()
            if (lease.fault or '').startswith('停止未确认'):
                raise SessionConflict(lease.fault)
            return
        if not lease.active and not (lease.fault or '').startswith('停止未确认'):
            if lease.task and not lease.task.done(): await asyncio.shield(lease.task)
            return
        lease.stopping = True
        lease.stop_done.clear()
        try:
            if lease.active: await asyncio.wait_for(lease.submitted.wait(), timeout=3)
            await lease.transport.stop()
            if lease.task: await asyncio.wait_for(asyncio.shield(lease.task), timeout=5)
            if (lease.fault or '').startswith('停止未确认'): lease.fault = None
        except Exception as error:
            lease.fault = "停止未确认："+str(error)[:160]
            raise SessionConflict(lease.fault) from error
        finally:
            lease.stopping = False
            lease.stop_done.set()

    async def release(self, session_id: str, token: str) -> dict:
        lease = self._owned(session_id, token)
        await self._stop(lease)
        if lease.fault and lease.fault.startswith("停止未确认"):
            raise SessionConflict(lease.fault)
        with self.runtime.store._lock:
            if self.lease is lease: self.lease = None
        await lease.transport.close()
        return self.status(session_id)

    async def stop_external(self, mode: RuntimeMode) -> None:
        if self.lease is not None and self.lease.mode == mode:
            await self._stop(self.lease)
            self.lease.external_stopped = True

    async def _watch(self) -> None:
        while self.lease is not None:
            await asyncio.sleep(0.05)
            lease = self.lease
            if lease is None: break
            try:
                if self.clock() >= lease.expires:
                    await self.release(lease.session_id, lease.token)
                elif lease.active and self.clock() >= lease.hold_until:
                    await self._stop(lease)
            except Exception:
                # Retain ownership on an unconfirmed stop, preventing a new task.
                await asyncio.sleep(0.2)

    async def shutdown(self) -> None:
        if self.lease is not None:
            await self.release(self.lease.session_id, self.lease.token)
        if self.watchdog is not None:
            self.watchdog.cancel()


router = APIRouter()


def controller(request: Request) -> ManualController:
    return request.app.state.runtime.manual


@router.get("/api/sessions/{session_id}/manual")
def manual_status(session_id: str, request: Request):
    return controller(request).status(session_id)


@router.get("/api/sessions/{session_id}/manual/joint-labels")
async def manual_joint_labels(session_id: str, request: Request):
    selected = controller(request)
    if selected._mode(session_id) != RuntimeMode.SIMULATION:
        return {"labels": [], "available": False}
    base = getattr(selected.runtime._robots[RuntimeMode.SIMULATION], 'base_url', None)
    if not base:
        return {"labels": [], "available": False}
    try:
        async with httpx.AsyncClient(base_url=base,timeout=1,trust_env=False) as client:
            response = await client.get('/v1/visualization/joint-labels')
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError):
        return {"labels": [], "available": False}


@router.post("/api/sessions/{session_id}/manual/acquire")
async def acquire(session_id: str, request: Request):
    return await controller(request).acquire(session_id)


@router.post("/api/sessions/{session_id}/manual/heartbeat")
async def heartbeat(session_id: str, body: LeaseRequest, request: Request):
    return await controller(request).heartbeat(session_id, body.token)


@router.post("/api/sessions/{session_id}/manual/input")
async def manual_input(session_id: str, body: ManualInput, request: Request):
    return await controller(request).input(session_id, body)


@router.post("/api/sessions/{session_id}/manual/release")
async def release(session_id: str, body: LeaseRequest, request: Request):
    return await controller(request).release(session_id, body.token)
