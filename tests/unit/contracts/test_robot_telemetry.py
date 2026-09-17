from __future__ import annotations

import unittest

from pydantic import ValidationError

from surgical_contracts import (
    CoordinateFrame,
    DistanceUnit,
    LinkState,
    Pose6D,
    RobotConnectionState,
    RobotHealth,
    RobotProvider,
    RobotTelemetry,
    RuntimeMode,
    SourceFreshness,
    VendorFault,
)


def base_pose() -> Pose6D:
    return Pose6D(
        translation_mm=(500.0, 0.0, 500.0),
        rotation_rpy_deg=(0.0, 90.0, 0.0),
        quaternion_xyzw=(0.0, 0.7071068, 0.0, 0.7071068),
        frame=CoordinateFrame.ROBOT_BASE,
        unit=DistanceUnit.MILLIMETER,
    )


class RobotTelemetryTests(unittest.TestCase):
    def test_missing_safety_and_connection_fields_remain_unknown(self) -> None:
        state = RobotTelemetry(
            runtime_mode=RuntimeMode.REAL,
            provider=RobotProvider.HUAYAN_EDGE_GATEWAY,
            sequence=0,
        )
        self.assertEqual(state.freshness, SourceFreshness.UNKNOWN)
        self.assertEqual(state.connections.gateway, LinkState.UNKNOWN)
        self.assertEqual(state.connections.datasheet, LinkState.UNKNOWN)
        self.assertIsNone(state.physical_estop_active)
        self.assertIsNone(state.safeguard_circuit_fault)
        self.assertIsNone(state.enabled)
        self.assertIsNone(state.potentially_moving)

    def test_fresh_real_state_requires_actual_pose_joints_and_age(self) -> None:
        payload = {
            "runtime_mode": "real",
            "provider": "huayan_edge_gateway",
            "sequence": 1,
            "freshness": "fresh",
        }
        with self.assertRaises(ValidationError):
            RobotTelemetry.model_validate(payload)
        payload.update(
            joint_positions_deg=(0, 0, 60, 0, 90, 0),
            actual_pose_robot_base=base_pose(),
        )
        with self.assertRaisesRegex(ValidationError, "state_age_ms"):
            RobotTelemetry.model_validate(payload)
        state = RobotTelemetry.model_validate({**payload, "state_age_ms": 25})
        self.assertEqual(len(state.joint_positions_deg or ()), 6)

    def test_real_state_cannot_claim_controller_simulation(self) -> None:
        with self.assertRaisesRegex(ValidationError, "controller simulation"):
            RobotTelemetry(
                runtime_mode=RuntimeMode.REAL,
                provider=RobotProvider.HUAYAN_EDGE_GATEWAY,
                sequence=1,
                freshness=SourceFreshness.FRESH,
                joint_positions_deg=(0, 0, 60, 0, 90, 0),
                actual_pose_robot_base=base_pose(),
                state_age_ms=10,
                controller_is_simulation=True,
            )

    def test_nonfinite_wrong_dimensions_and_unknown_frame_fail(self) -> None:
        pose = base_pose().model_dump()
        for change in (
            {"translation_mm": (0, float("nan"), 0)},
            {"rotation_rpy_deg": (0, 0)},
            {"quaternion_xyzw": (0, 0, 0, 0)},
            {"quaternion_xyzw": (0, 0, 0, 2)},
            {"frame": "unknown_frame"},
        ):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                Pose6D.model_validate({**pose, **change})
        with self.assertRaises(ValidationError):
            RobotTelemetry(
                runtime_mode=RuntimeMode.REAL,
                provider=RobotProvider.HUAYAN_EDGE_GATEWAY,
                sequence=0,
                joint_positions_deg=(0, 0, 0),
            )

    def test_mode_provider_conflict_and_unknown_vendor_fault(self) -> None:
        with self.assertRaisesRegex(ValidationError, "disagree"):
            RobotTelemetry(
                runtime_mode=RuntimeMode.REAL,
                provider=RobotProvider.SIMULATION,
                sequence=0,
            )
        fault = VendorFault(vendor_error_code=49621, vendor_error_axis=3)
        self.assertEqual(fault.recoverability.value, "unknown")
        self.assertEqual(fault.execution_certainty.value, "unknown")
        with self.assertRaises(ValidationError):
            VendorFault(vendor_error_code=49621, vendor_error_axis=7)

    def test_real_motion_readiness_cannot_be_claimed_in_step_one(self) -> None:
        health = RobotHealth(
            runtime_mode=RuntimeMode.REAL,
            provider=RobotProvider.HUAYAN_EDGE_GATEWAY,
            status="healthy",
        )
        self.assertFalse(health.ready_for_motion)
        with self.assertRaisesRegex(ValidationError, "preflight"):
            RobotHealth(
                runtime_mode=RuntimeMode.REAL,
                provider=RobotProvider.HUAYAN_EDGE_GATEWAY,
                status="healthy",
                ready_for_motion=True,
            )
        connected = RobotConnectionState(
            gateway=LinkState.CONNECTED,
            datasheet=LinkState.CONNECTED,
            command_socket=LinkState.CONNECTED,
            controller_box=LinkState.CONNECTED,
        )
        with self.assertRaisesRegex(ValidationError, "preflight"):
            RobotHealth(
                runtime_mode=RuntimeMode.REAL,
                provider=RobotProvider.HUAYAN_EDGE_GATEWAY,
                status="healthy",
                freshness=SourceFreshness.FRESH,
                connections=connected,
                ready_for_motion=True,
            )


if __name__ == "__main__":
    unittest.main()
