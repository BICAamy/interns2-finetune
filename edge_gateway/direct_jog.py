"""Mac-local owner for one LongJogL/LongJogJ direct-control hold."""

from __future__ import annotations

import threading
import time
from typing import Callable

from surgical_contracts import (
    DirectJogRequest,
    ErrorCode,
    GatewayCommandKind,
    MotionStopConfirmation,
    RobotCommandEnvelope,
    RobotCommandResult,
    RobotTelemetry,
    SoftwareStopResult,
    StopDelivery,
    ToolStatus,
    command_fingerprint,
)

from .huayan.real_motion_client import LocalRealMotionClient


class DirectJogExecutor:
    """Keep one vendor long jog alive until the browser releases control."""

    def __init__(
        self,
        *,
        client: LocalRealMotionClient,
        snapshot: Callable[[], RobotTelemetry],
        cloud_connected: Callable[[], bool],
        keepalive_interval_s: float = 0.2,
        motion_timeout_s: float = 120.0,
        stop_confirmation_s: float = 3.0,
    ) -> None:
        self._client = client
        self._snapshot = snapshot
        self._cloud_connected = cloud_connected
        self._keepalive_interval_s = keepalive_interval_s
        self._motion_timeout_s = motion_timeout_s
        self._stop_confirmation_s = stop_confirmation_s
        self._stop_requested = threading.Event()
        self._done = threading.Event()
        self._lock = threading.Lock()
        self._stop_result = SoftwareStopResult(
            delivery=StopDelivery.NOT_SENT,
            motion_stop=MotionStopConfirmation.UNCONFIRMED,
        )

    def execute(
        self, envelope: RobotCommandEnvelope, fingerprint: str,
    ) -> RobotCommandResult:
        started = False
        close_attempted = False
        failure: tuple[ErrorCode, str] | None = None
        payload = envelope.payload
        try:
            if (
                envelope.command_kind != GatewayCommandKind.DIRECT_JOG
                or not isinstance(payload, DirectJogRequest)
                or command_fingerprint(envelope) != fingerprint
            ):
                raise ValueError("direct-jog envelope or fingerprint is invalid")

            if not self._stop_requested.is_set():
                if not self._client.start_long_jog(
                    kind=payload.kind,
                    axis=payload.axis,
                    direction=payload.direction,
                ):
                    failure = (
                        ErrorCode.ROBOT_COMMAND_REJECTED,
                        "controller rejected LongJog start",
                    )
                else:
                    started = True

            started_at = time.monotonic()
            next_keepalive = started_at + self._keepalive_interval_s
            while started and failure is None and not self._stop_requested.is_set():
                now = time.monotonic()
                if not self._cloud_connected():
                    self._stop_requested.set()
                    break
                if now - started_at >= self._motion_timeout_s:
                    failure = (
                        ErrorCode.ROBOT_TIMEOUT,
                        "direct jog exceeded the configured local motion deadline",
                    )
                    break
                if now >= next_keepalive:
                    if not self._client.keep_long_jog_alive():
                        failure = (
                            ErrorCode.ROBOT_COMMAND_REJECTED,
                            "controller rejected LongMoveEvent",
                        )
                        break
                    next_keepalive = now + self._keepalive_interval_s
                self._stop_requested.wait(0.01)

            if started:
                close_attempted = True
                delivered = self._client.stop_long_jog()
                with self._lock:
                    self._stop_result = SoftwareStopResult(
                        delivery=(StopDelivery.SENT if delivered else StopDelivery.NOT_SENT),
                        motion_stop=MotionStopConfirmation.UNCONFIRMED,
                    )
                if not delivered and failure is None:
                    failure = (
                        ErrorCode.ROBOT_COMMAND_REJECTED,
                        "controller rejected LongJog close",
                    )

            final = self._wait_stationary()
            if final is not None:
                with self._lock:
                    self._stop_result = SoftwareStopResult(
                        delivery=(
                            StopDelivery.SENT if started else StopDelivery.NOT_SENT
                        ),
                        motion_stop=MotionStopConfirmation.CONFIRMED,
                    )
            elif failure is None:
                failure = (
                    ErrorCode.ROBOT_TIMEOUT,
                    "LongJog close was not confirmed by fresh stationary feedback",
                )

            if failure is not None:
                return self._failed(envelope, *failure)
            assert final is not None
            return RobotCommandResult(
                gateway_session_id=envelope.gateway_session_id,
                command_id=envelope.command_id,
                command_kind=envelope.command_kind,
                status=ToolStatus.SUCCESS,
                final_pose_robot_base=final.actual_pose_robot_base,
                final_joint_positions_deg=final.joint_positions_deg,
            )
        except Exception as exc:
            if started and not close_attempted:
                try:
                    delivered = self._client.stop_long_jog()
                    with self._lock:
                        self._stop_result = SoftwareStopResult(
                            delivery=(
                                StopDelivery.SENT
                                if delivered
                                else StopDelivery.NOT_SENT
                            ),
                            motion_stop=MotionStopConfirmation.UNCONFIRMED,
                        )
                except Exception:
                    pass
            return self._failed(
                envelope,
                ErrorCode.ROBOT_TIMEOUT if isinstance(exc, TimeoutError)
                else ErrorCode.INTERNAL_ERROR,
                f"{type(exc).__name__}: {exc}",
            )
        finally:
            self._done.set()

    def _wait_stationary(self) -> RobotTelemetry | None:
        deadline = time.monotonic() + self._stop_confirmation_s
        while time.monotonic() < deadline:
            try:
                state = self._snapshot()
            except Exception:
                time.sleep(0.02)
                continue
            if (
                state.moving is False
                and state.potentially_moving is False
                and state.in_position is True
            ):
                return state
            time.sleep(0.02)
        return None

    def request_authenticated_stop(
        self, _command_id: str, *, timeout_s: float,
    ) -> SoftwareStopResult:
        self._stop_requested.set()
        self._done.wait(timeout_s)
        with self._lock:
            return self._stop_result.model_copy(deep=True)

    def request_authenticated_pause(
        self, _command_id: str, *, target_command_id: str, timeout_s: float,
    ) -> bool:
        del target_command_id, timeout_s
        return False

    def request_authenticated_resume(
        self, _command_id: str, *, target_command_id: str, timeout_s: float,
    ) -> bool:
        del target_command_id, timeout_s
        return False

    @staticmethod
    def _failed(
        envelope: RobotCommandEnvelope, code: ErrorCode, message: str,
    ) -> RobotCommandResult:
        return RobotCommandResult(
            gateway_session_id=envelope.gateway_session_id,
            command_id=envelope.command_id,
            command_kind=envelope.command_kind,
            status=ToolStatus.FAILED,
            error_code=code,
            error_message=message[:512],
        )
