"""Independent, leased manual motion. Never calls a parser or text orchestrator.

The current Mac gateway has no interruptible web-jog channel. Real mode is
explicitly unavailable here until that gateway is upgraded; no legacy command
or stop semantics are changed to pretend otherwise.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
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
    sequence: int = 0
    hold_until: float = 0
    desired: ManualInput | None = None
    task: asyncio.Task | None = None
    stopping: bool = False
    active: bool = False
    fault: str | None = None
    submitted: asyncio.Event = field(default_factory=asyncio.Event)
    transport: object | None = None


class ManualTransport:
    """Submit/ack and completion are separate, so stop cannot overtake submit."""
    def __init__(self, base_url: str):
        self.client = httpx.AsyncClient(base_url=base_url, timeout=2, trust_env=False)

    async def submit(self, command: MoveSequenceRequest) -> dict:
        response = await self.client.post('/v1/commands/move-sequence', json=command.model_dump(mode='json'))
        response.raise_for_status()
        return response.json()

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
                raise RuntimeError('停止请求未成功完成')
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
        self.transport_factory = transport_factory or (lambda: ManualTransport(
            self.runtime._robots[RuntimeMode.SIMULATION].base_url))

    def assert_task_allowed(self, mode: RuntimeMode) -> None:
        # Called inside SessionStore.mutate's RLock, also held during acquisition.
        if self.lease is not None and mode == RuntimeMode.SIMULATION:
            raise SessionConflict("仿真机械臂正在由手动面板控制，请先释放手动控制权")

    def _mode(self, session_id: str) -> RuntimeMode:
        return self.runtime._session_mode(session_id)

    def _owned(self, session_id: str, token: str) -> Lease:
        lease = self.lease
        if (lease is None or lease.session_id != session_id
                or not secrets.compare_digest(lease.token, token)):
            raise SessionConflict("手动控制权已失效，请重新接管")
        return lease

    def _busy(self) -> bool:
        return any(r.robot_mode == RuntimeMode.SIMULATION and
                   (r.status.value in BUSY or r.pending_command is not None)
                   for r in self.runtime.store._records.values())

    def status(self, session_id: str) -> dict:
        mode = self._mode(session_id)
        lease = self.lease
        return {
            "available": mode == RuntimeMode.SIMULATION,
            "mode": mode.value,
            "reason": ("" if mode == RuntimeMode.SIMULATION else
                       "Mac 网关尚未启用手动停止与超时停机，本轮未升级网关，真机手动控制未开放"),
            "occupied": lease is not None,
            "owned_by_session": lease is not None and lease.session_id == session_id,
            "moving": bool(lease and lease.active),
            "stopping": bool(lease and lease.stopping),
            "fault": lease.fault if lease else None,
            "limits": {
                "translation_step": min(20.0, self.policy.max_relative_translation_mm),
                "rotation_step": min(20.0, self.policy.max_rotation_deg),
                "translation_speed": self.policy.move_speed_mm_s,
                "angular_speed": self.policy.joint_speed_deg_s,
            },
        }

    async def acquire(self, session_id: str) -> dict:
        if self._mode(session_id) != RuntimeMode.SIMULATION:
            raise SessionConflict(self.status(session_id)["reason"])
        with self.runtime.store._lock:
            if self.lease is not None:
                raise SessionConflict("机械臂已有手动控制者，请等待其释放")
            if self._busy():
                raise SessionConflict("已有文本或手势任务待确认/执行，不能接管手动控制")
            lease = Lease(session_id, secrets.token_urlsafe(32), self.clock()+LEASE_SECONDS)
            self.lease = lease
        try:
            view = await asyncio.to_thread(self.runtime.get_robot_telemetry, session_id)
            if not view.connected or view.estop or view.motion_state in {"moving", "estop"}:
                raise SessionConflict("机械臂未连接、尚未静止或处于急停状态，不能接管")
            if self._mode(session_id) != RuntimeMode.SIMULATION:
                raise SessionConflict("接管期间运行模式已改变")
        except Exception:
            self.lease = None
            raise
        if self.watchdog is None or self.watchdog.done():
            self.watchdog = asyncio.create_task(self._watch())
        lease.transport = self.transport_factory()
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
        if lease.fault or lease.stopping:
            raise SessionConflict("上次停止尚未确认或动作失败，请先释放控制权")
        if self._mode(session_id) != RuntimeMode.SIMULATION:
            await self._stop(lease)
            raise SessionConflict("模式已变化，手动输入已停止")
        if command.kind != "joint" and command.axis > 2:
            raise HTTPException(422, "XYZ/姿态轴只能为 0、1、2")
        maximum = (min(20.0, self.policy.max_relative_translation_mm)
                   if command.kind == "translation" else min(20.0, self.policy.max_rotation_deg))
        if command.amount > maximum:
            raise HTTPException(422, "点动步长超出当前配置限制")
        if lease.desired is not None and lease.active:
            old = lease.desired
            if (old.kind, old.axis, old.direction) != (command.kind, command.axis, command.direction):
                await self._stop(lease)
                raise SessionConflict("改变运动方向前请先松开控制")
        lease.desired = command
        lease.hold_until = self.clock()+HOLD_SECONDS
        if lease.task is None or lease.task.done():
            lease.task = asyncio.create_task(self._run(lease))
        return self.status(session_id)

    def _request(self, command: ManualInput) -> MoveSequenceRequest:
        amount = command.amount
        speed = self.policy.move_speed_mm_s * command.speed_scale
        angular = self.policy.joint_speed_deg_s * command.speed_scale
        # Honor the chosen finite increment (up to the manual/policy limit).
        # Only one segment is in flight; release/watchdog interrupts it through
        # the same acknowledged stop path rather than shrinking every segment.
        value = command.direction * amount
        if command.kind == "translation":
            xyz = [0.0, 0.0, 0.0]; xyz[command.axis] = value
            step = MotionSequenceStep(kind=MotionStepKind.CARTESIAN_RELATIVE, translation_mm=tuple(xyz))
        elif command.kind == "rotation":
            step = MotionSequenceStep(kind=MotionStepKind.TCP_ROTATION_RELATIVE,
                                      rotation_axis=("x", "y", "z")[command.axis], rotation_deg=value)
        else:
            step = MotionSequenceStep(kind=MotionStepKind.JOINT_RELATIVE,
                                      joint_index=command.axis+1, rotation_deg=value)
        return MoveSequenceRequest(command_id=f"manual-{uuid4().hex}", steps=(step,),
                                   translation_speed_mm_s=speed, joint_speed_deg_s=angular,
                                   joint_acceleration_deg_s2=self.policy.joint_acceleration_deg_s2)

    async def _run(self, lease: Lease) -> None:
        try:
            while self.lease is lease and lease.desired is not None and not lease.stopping:
                command = lease.desired
                if self.clock() >= min(lease.expires, lease.hold_until):
                    lease.desired = None; break
                lease.active = True
                lease.submitted.clear()
                request = self._request(command)
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
            if lease.task: await asyncio.shield(lease.task)
            return
        if not lease.active and not (lease.fault or '').startswith('停止未确认'):
            if lease.task and not lease.task.done(): await asyncio.shield(lease.task)
            return
        lease.stopping = True
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
        if mode == RuntimeMode.SIMULATION and self.lease is not None:
            await self._stop(self.lease)

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
