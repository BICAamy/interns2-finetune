"""Single-owner, latest-wins SOFA mirror for authenticated real feedback."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from threading import Condition, Event, Lock, Thread
import time
from typing import Any, Protocol

from surgical_contracts import (
    RobotTelemetry,
    SimulationCameraControlRequest,
    SimulationCameraState,
    SourceFreshness,
)


def _default_camera_state() -> SimulationCameraState:
    # 定义一个默认 SOFA 相机位置。
    return SimulationCameraState(
        preset="front",
        yaw_deg=0.0, # 相机相对于底座坐标系的yaw角偏移值
        pitch_deg=0.0, # 相机相对于底座坐标系的pitch角偏移值
        distance_m=1.65, 
        target_m=(0.35, 0.0, 0.42), # 相机看这里
        position_m=(0.35, -1.65, 0.42), # 相机初始位置
        updated_at_ms=time.time_ns() // 1_000_000, # 摄像机状态最后一次被修改时的 Unix 时间戳，ms
    )

# 这里用了Protocol结构化继承
# 而 类PassiveRealMirrorEnv 长得像 MirrorEnvironment，所以我们认为 类PassiveRealMirrorEnv 继承了 MirrorEnvironment
class MirrorEnvironment(Protocol):
    controller: Any

    def reset(self) -> None: ...
    def apply_external_joint_state(self, telemetry: RobotTelemetry) -> Any | None: ...
    def refresh_frozen_frame(self) -> Any | None: ...
    def clear_trajectory(self) -> Any | None: ...
    def get_camera_state(self) -> SimulationCameraState: ...
    def control_camera(self, request: SimulationCameraControlRequest) -> SimulationCameraState: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class MirrorStatus:
    enabled: bool # mirror 功能是否启用
    worker_alive: bool # 后台仿真线程还活着吗
    source_sequence: int | None # 当前 SOFA frame 对应的是哪一帧真实 RobotTelemetry
    gateway_session_id: str | None # 当前这个真实状态属于哪个 Mac gateway session，每一次mac连接服务器都会产生新的会话id，直到断开连接
    frame_sequence: int # RealMirrorWorker 自己生成了第几张画面。
    freshness: SourceFreshness # 当前真机状态：
    calibrated: bool # 标定参数是否已提供
    warning: str # 这只是提示语句：这个 SOFA mirror 只是显示，不允许拿这个仿真画面反过来控制机器人
    reason: str # 
    error: str | None # RealMirrorWorker 自己有没有发生异常


def create_sofa_mirror_environment(
    *,
    stale_ms: int,
    sign: tuple[int, ...] | None,
    zero_offset_deg: tuple[float, ...] | None,
    base_to_sofa_translation_mm: tuple[float, ...] | None,
    base_to_sofa_quaternion_xyzw: tuple[float, ...] | None,
) -> MirrorEnvironment:
    """SOFA 场景和 OpenGL 是由专门的 mirror thread 创建和操作"""
    from simulation.entry_point_env.passive_mirror_env import PassiveRealMirrorEnv

    return PassiveRealMirrorEnv(
        stale_ms=stale_ms,
        sign=sign,
        zero_offset_deg=zero_offset_deg,
        base_to_sofa_translation_mm=base_to_sofa_translation_mm,
        base_to_sofa_quaternion_xyzw=base_to_sofa_quaternion_xyzw,
    )


class RealMirrorWorker:
    def __init__(
        self,
        telemetry_source: Callable[[], RobotTelemetry],
        *,
        stale_ms: int, # 用于判断当前真实状态（这里定义的那个freshness）是不是已经 stale。
        sign: tuple[int, ...] | None = None, # 标定参数
        zero_offset_deg: tuple[float, ...] | None = None, # 标定参数
        base_to_sofa_translation_mm: tuple[float, ...] | None = None, # 标定参数
        base_to_sofa_quaternion_xyzw: tuple[float, ...] | None = None, # 标定参数
        environment_factory: Callable[[], MirrorEnvironment] | None = None, # 环境对象
        tick_interval_s: float = 0.05, # mirror 自己多久循环一次，这里硬编码为0.05s -> 20Hz
    ) -> None:
        if tick_interval_s <= 0 or stale_ms <= 0:
            raise ValueError("mirror tick and stale deadline must be positive")
        self._telemetry_source = telemetry_source
        if (sign is None) != (zero_offset_deg is None):
            raise ValueError("joint sign and zero offset must be set together")
        if (base_to_sofa_translation_mm is None) != (
            base_to_sofa_quaternion_xyzw is None
        ):
            raise ValueError("Base-to-SOFA translation and quaternion must be set together")
        self._calibrated = sign is not None and base_to_sofa_translation_mm is not None
        self._environment_factory = environment_factory or (
            lambda: create_sofa_mirror_environment(
                stale_ms=stale_ms,
                sign=sign,
                zero_offset_deg=zero_offset_deg,
                base_to_sofa_translation_mm=base_to_sofa_translation_mm,
                base_to_sofa_quaternion_xyzw=base_to_sofa_quaternion_xyzw,
            )
        )
        self._tick_interval_s = tick_interval_s
        self._lock = Lock()
        self._condition = Condition(self._lock)
        self._stop = Event()
        self._ready = Event()
        self._thread: Thread | None = None
        self._error: str | None = None
        self._frame: Any | None = None
        self._frame_sequence = 0
        self._source_sequence: int | None = None
        self._session_id: str | None = None
        self._freshness = SourceFreshness.DISCONNECTED
        self._reason = "no_actual_joint_sample"
        self._camera_state: SimulationCameraState | None = _default_camera_state()
        self._camera_requests: deque[
            tuple[SimulationCameraControlRequest, Event, dict[str, Any]]
        ] = deque()
        self._trajectory_clear_requests: deque[
            tuple[Event, dict[str, Any]]
        ] = deque()

    def start(self, *, timeout_s: float = 60.0) -> None:
        with self._lock: # 线程锁：保护共享变量
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear() # 停止线程
            self._ready.clear() # 告诉线程 SOFA 初始化完毕了
            self._error = None
            self._frame = None # 当前最新渲染出的图像
            self._frame_sequence = 0 # RealMirrorWorker 自己生成了第几张画面。
            self._source_sequence = None # 当前 SOFA frame 对应的是哪一帧真实 RobotTelemetry
            self._session_id = None # 这张 SOFA 画面对应哪个 gateway session
            self._freshness = SourceFreshness.DISCONNECTED
            self._reason = "no_actual_joint_sample" # 信息：为什么现在不能正常更新。
            self._camera_state = _default_camera_state()
            self._camera_requests.clear()
            self._trajectory_clear_requests.clear()
            self._thread = Thread(target=self._run, name="real-sofa-mirror", daemon=True) # 创建运行 SOFA 的后台线程
            self._thread.start() # 启动线程
        if not self._ready.wait(timeout_s): # 主线程进行等待
            raise RuntimeError("real SOFA mirror did not initialize")
        if self._error is not None:
            raise RuntimeError(self._error)

    def shutdown(self, *, timeout_s: float = 10.0) -> None:
        self._stop.set()
        with self._lock:
            self._condition.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join(timeout_s)

    def _publish(self, frame: Any, *, source_sequence: int | None, session_id: str | None) -> None:
        with self._lock:
            self._frame = frame.copy()
            self._frame_sequence += 1
            self._source_sequence = source_sequence
            self._session_id = session_id
            self._condition.notify_all()

    def _run(self) -> None:
        environment: MirrorEnvironment | None = None
        try:
            environment = self._environment_factory()
            environment.reset()
            camera_getter = getattr(environment, "get_camera_state", None)
            if camera_getter is not None:
                with self._lock:
                    self._camera_state = camera_getter()
            self._ready.set()
            while not self._stop.is_set():
                while True:
                    with self._lock:
                        pending = self._camera_requests.popleft() if self._camera_requests else None
                    if pending is None:
                        break
                    request, completed, holder = pending
                    try:
                        camera_control = getattr(environment, "control_camera", None)
                        if camera_control is None:
                            raise RuntimeError("mirror environment has no camera control")
                        state = camera_control(request)
                        with self._lock:
                            self._camera_state = state
                        holder["state"] = state
                    except Exception as error:
                        holder["error"] = error
                    finally:
                        completed.set()
                while True:
                    with self._lock:
                        pending_clear = (
                            self._trajectory_clear_requests.popleft()
                            if self._trajectory_clear_requests
                            else None
                        )
                    if pending_clear is None:
                        break
                    completed, holder = pending_clear
                    try:
                        frame = environment.clear_trajectory()
                        holder["trajectory_points"] = len(
                            environment.controller.trajectory_mm
                        )
                        if frame is not None:
                            snapshot = environment.controller.snapshot
                            self._publish(
                                frame,
                                source_sequence=(
                                    snapshot.source_sequence
                                    if snapshot is not None
                                    else None
                                ),
                                session_id=(
                                    snapshot.gateway_session_id
                                    if snapshot is not None
                                    else None
                                ),
                            )
                    except Exception as error:
                        holder["error"] = error
                    finally:
                        completed.set()
                telemetry = self._telemetry_source()
                old_freshness = environment.controller.freshness
                frame = environment.apply_external_joint_state(telemetry)
                with self._lock:
                    self._freshness = environment.controller.freshness
                    self._reason = environment.controller.reason
                if frame is not None:
                    snapshot = environment.controller.snapshot
                    assert snapshot is not None
                    self._publish(
                        frame,
                        source_sequence=snapshot.source_sequence,
                        session_id=snapshot.gateway_session_id,
                    )
                elif old_freshness != environment.controller.freshness:
                    frozen = environment.refresh_frozen_frame()
                    if frozen is not None:
                        snapshot = environment.controller.snapshot
                        assert snapshot is not None
                        self._publish(
                            frozen,
                            source_sequence=snapshot.source_sequence,
                            session_id=snapshot.gateway_session_id,
                        )
                self._stop.wait(self._tick_interval_s)
        except Exception as error:
            with self._lock:
                self._error = f"{type(error).__name__}: {error}"
                self._freshness = SourceFreshness.DISCONNECTED
                self._condition.notify_all()
            self._ready.set()
        finally:
            if environment is not None:
                try:
                    environment.close()
                except Exception:
                    pass
            with self._lock:
                self._condition.notify_all()

    def status(self) -> MirrorStatus:
        with self._lock:
            return MirrorStatus(
                enabled=True,
                worker_alive=self._thread is not None and self._thread.is_alive(),
                source_sequence=self._source_sequence,
                gateway_session_id=self._session_id,
                frame_sequence=self._frame_sequence,
                freshness=self._freshness,
                calibrated=self._calibrated,
                warning=(
                    "COORDINATE CALIBRATED / TOOL TCP UNAVAILABLE / NOT FOR CONTROL"
                    if self._calibrated
                    else "UNCALIBRATED / NOT FOR CONTROL"
                ),
                reason=self._reason,
                error=self._error,
            )

    def wait_for_frame(self, after_sequence: int, *, timeout_s: float = 2.0) -> tuple[int, Any | None]:
        deadline = time.monotonic() + timeout_s
        with self._lock:
            while self._frame_sequence <= after_sequence and not self._stop.is_set() and self._error is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return self._frame_sequence, None
                self._condition.wait(remaining)
            return self._frame_sequence, self._frame.copy() if self._frame is not None else None

    def get_camera_state(self) -> SimulationCameraState:
        with self._lock:
            if self._camera_state is None:
                raise RuntimeError("real SOFA mirror camera is not ready")
            return self._camera_state.model_copy(deep=True)

    def control_camera(
        self,
        request: SimulationCameraControlRequest,
        *,
        timeout_s: float = 2.0,
    ) -> SimulationCameraState:
        if self._thread is None or not self._thread.is_alive():
            raise RuntimeError("real SOFA mirror is not running")
        completed = Event()
        holder: dict[str, Any] = {}
        with self._lock:
            self._camera_requests.append((request, completed, holder))
        if not completed.wait(timeout_s):
            raise RuntimeError("real SOFA mirror camera update timed out")
        if "error" in holder:
            raise RuntimeError("real SOFA mirror camera update failed") from holder["error"]
        state = holder.get("state")
        if not isinstance(state, SimulationCameraState):
            raise RuntimeError("real SOFA mirror returned no camera state")
        return state.model_copy(deep=True)

    def clear_trajectory(self, *, timeout_s: float = 2.0) -> int:
        """Clear only mirror history on the SOFA owner thread."""

        if self._thread is None or not self._thread.is_alive():
            raise RuntimeError("real SOFA mirror is not running")
        completed = Event()
        holder: dict[str, Any] = {}
        with self._lock:
            self._trajectory_clear_requests.append((completed, holder))
        if not completed.wait(timeout_s):
            raise RuntimeError("real SOFA mirror trajectory clear timed out")
        if "error" in holder:
            raise RuntimeError("real SOFA mirror trajectory clear failed") from holder[
                "error"
            ]
        points = holder.get("trajectory_points")
        if not isinstance(points, int):
            raise RuntimeError("real SOFA mirror returned no trajectory result")
        return points
