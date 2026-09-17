from __future__ import annotations

import unittest

from pydantic import ValidationError

from surgical_contracts import (
    CommandIntent,
    CoordinateFrame,
    DistanceUnit,
    ErrorCode,
    GatewayCommandKind,
    GatewayHandshake,
    MotionSafetyLimits,
    MotionStopConfirmation,
    MoveRelativeRequest,
    MoveToEntryRequest,
    ParsedCommand,
    Point3D,
    Pose6D,
    RobotCommandAcknowledgement,
    RobotCommandEnvelope,
    RobotCommandResult,
    SoftwareStopRequest,
    SoftwareStopResult,
    StopDelivery,
    ToolName,
    ToolStatus,
)


def pose() -> Pose6D:
    return Pose6D(
        translation_mm=(500, 0, 500),
        rotation_rpy_deg=(0, 90, 0),
        quaternion_xyzw=(0, 0.7071068, 0, 0.7071068),
        frame=CoordinateFrame.ROBOT_BASE,
        unit=DistanceUnit.MILLIMETER,
    )


def movement(**changes: object) -> RobotCommandEnvelope:
    values = {
        "gateway_session_id": "session-1",
        "command_id": "cmd-1",
        "command_kind": GatewayCommandKind.MOVE_RELATIVE,
        "created_at_ms": 1000,
        "expires_at_ms": 2000,
        "based_on_robot_state_sequence": 7,
        "expected_start_pose_robot_base": pose(),
        "expected_tcp_name": "needle_tip",
        "expected_ucs_name": "Base",
        "payload": MoveRelativeRequest(
            command_id="cmd-1",
            translation_mm=(0, 0, 5),
            frame=CoordinateFrame.ROBOT_BASE,
            speed_mm_s=5,
        ),
        "safety_limits": MotionSafetyLimits(max_speed_mm_s=5, max_step_mm=10),
        "operator_confirmation_id": "confirm-1",
    }
    values.update(changes)
    return RobotCommandEnvelope.model_validate(values)


class GatewayContractTests(unittest.TestCase):
    def test_handshake_defaults_to_observe_only_and_hash_is_strict(self) -> None:
        handshake = GatewayHandshake(
            gateway_session_id="session-1",
            device_sn="robot-1",
            robot_model="E05-Pro",
            package_version="6.5",
            safety_config_sha256="a" * 64,
        )
        self.assertEqual(handshake.control_mode.value, "observe-only")
        with self.assertRaises(ValidationError):
            GatewayHandshake.model_validate(
                {**handshake.model_dump(), "safety_config_sha256": "bad"}
            )
        with self.assertRaises(ValidationError):
            GatewayHandshake.model_validate(
                {**handshake.model_dump(), "schema_version": "2.0"}
            )

    def test_motion_envelope_requires_typed_payload_and_preflight(self) -> None:
        valid = movement()
        self.assertEqual(valid.payload.command_id, valid.command_id)
        restored = RobotCommandEnvelope.model_validate_json(valid.model_dump_json())
        self.assertEqual(restored, valid)
        for change in (
            {"expires_at_ms": 1000},
            {
                "payload": MoveRelativeRequest(
                    command_id="other",
                    translation_mm=(0, 0, 5),
                    frame=CoordinateFrame.ROBOT_BASE,
                )
            },
            {"expected_start_pose_robot_base": None},
            {"expected_tcp_name": None},
            {"safety_limits": None},
            {"operator_confirmation_id": None},
            {"payload": SoftwareStopRequest(command_id="cmd-1")},
            {
                "payload": MoveRelativeRequest(
                    command_id="cmd-1",
                    translation_mm=(0, 0, 11),
                    frame=CoordinateFrame.ROBOT_BASE,
                )
            },
            {
                "payload": MoveRelativeRequest(
                    command_id="cmd-1",
                    translation_mm=(0, 0, 5),
                    frame=CoordinateFrame.ROBOT_BASE,
                    speed_mm_s=6,
                )
            },
            {"payload": MoveRelativeRequest(command_id="cmd-1", translation_mm=(0, 0, 5))},
            {
                "payload": MoveRelativeRequest(
                    command_id="cmd-1",
                    translation_mm=(0, 0, 5),
                    frame=CoordinateFrame.SIMULATION_WORLD,
                )
            },
        ):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                movement(**change)
        with self.assertRaises(ValidationError):
            movement(safety_limits=MotionSafetyLimits(max_speed_mm_s=float("inf"), max_step_mm=10))

    def test_entry_motion_requires_explicit_base_point_and_matching_tcp(self) -> None:
        def entry_point(*, frame: CoordinateFrame | None = None, unit: bool = True) -> Point3D:
            values: dict[str, object] = {"x": 500, "y": 0, "z": 505}
            if frame is not None:
                values["frame"] = frame
            if unit:
                values["unit"] = DistanceUnit.MILLIMETER
            return Point3D.model_validate(values)

        def request(point: Point3D, *, tcp: str = "needle_tip") -> MoveToEntryRequest:
            return MoveToEntryRequest(command_id="cmd-1", entry_point=point, tcp=tcp)

        valid = movement(
            command_kind=GatewayCommandKind.MOVE_TO_ENTRY,
            payload=request(entry_point(frame=CoordinateFrame.ROBOT_BASE)),
        )
        self.assertEqual(valid.payload.entry_point.frame, CoordinateFrame.ROBOT_BASE)
        for payload in (
            request(entry_point()),
            request(entry_point(frame=CoordinateFrame.ROBOT_BASE, unit=False)),
            request(entry_point(frame=CoordinateFrame.SIMULATION_WORLD)),
            request(entry_point(frame=CoordinateFrame.ROBOT_BASE), tcp="other_tcp"),
        ):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                movement(command_kind=GatewayCommandKind.MOVE_TO_ENTRY, payload=payload)

    def test_software_stop_is_separate_from_estop_and_motion(self) -> None:
        stop = RobotCommandEnvelope(
            gateway_session_id="session-1",
            command_id="stop-1",
            command_kind=GatewayCommandKind.SOFTWARE_STOP_REQUEST,
            created_at_ms=1000,
            expires_at_ms=2000,
            based_on_robot_state_sequence=7,
            payload=SoftwareStopRequest(command_id="stop-1"),
        )
        self.assertIsNone(stop.safety_limits)
        self.assertIsNone(stop.operator_confirmation_id)
        with self.assertRaises(ValidationError):
            RobotCommandEnvelope.model_validate(
                {**stop.model_dump(), "expected_tcp_name": "needle_tip"}
            )
        intent = ParsedCommand(
            command_id="stop-1", intent=CommandIntent.SOFTWARE_STOP_REQUEST
        )
        self.assertEqual(intent.intent.value, "software_stop_request")
        self.assertEqual(ToolName.ROBOT_SOFTWARE_STOP_REQUEST.value, "robot.software_stop_request")
        with self.assertRaises(ValidationError):
            ParsedCommand(
                command_id="stop-2",
                intent=CommandIntent.SOFTWARE_STOP_REQUEST,
                entry_point={"x": 1, "y": 2, "z": 3},
            )

    def test_stop_result_does_not_claim_physical_estop_or_confirmed_stop(self) -> None:
        stop = SoftwareStopResult(
            delivery=StopDelivery.UNKNOWN,
            motion_stop=MotionStopConfirmation.UNCONFIRMED,
        )
        self.assertNotIn("physical_estop_active", SoftwareStopResult.model_fields)
        with self.assertRaises(ValidationError):
            SoftwareStopResult.model_validate(
                {**stop.model_dump(), "physical_estop_active": True}
            )
        result = RobotCommandResult(
            gateway_session_id="session-1",
            command_id="stop-1",
            command_kind=GatewayCommandKind.SOFTWARE_STOP_REQUEST,
            status=ToolStatus.FAILED,
            error_code=ErrorCode.ROBOT_TIMEOUT,
            software_stop=stop,
        )
        self.assertEqual(result.software_stop.motion_stop.value, "unconfirmed")
        with self.assertRaises(ValidationError):
            RobotCommandResult(
                gateway_session_id="session-1",
                command_id="stop-1",
                command_kind=GatewayCommandKind.SOFTWARE_STOP_REQUEST,
                status=ToolStatus.SUCCESS,
                error_code=ErrorCode.ROBOT_TIMEOUT,
            )
        with self.assertRaisesRegex(ValidationError, "sent and confirmed"):
            RobotCommandResult(
                gateway_session_id="session-1",
                command_id="stop-1",
                command_kind=GatewayCommandKind.SOFTWARE_STOP_REQUEST,
                status=ToolStatus.SUCCESS,
                software_stop=stop,
            )
        with self.assertRaisesRegex(ValidationError, "requires delivery"):
            RobotCommandResult(
                gateway_session_id="session-1",
                command_id="stop-1",
                command_kind=GatewayCommandKind.SOFTWARE_STOP_REQUEST,
                status=ToolStatus.FAILED,
                error_code=ErrorCode.ROBOT_TIMEOUT,
            )
        with self.assertRaises(ValidationError):
            RobotCommandAcknowledgement(
                gateway_session_id="session-1",
                command_id="cmd-1",
                status="rejected",
            )


if __name__ == "__main__":
    unittest.main()
