from __future__ import annotations

import unittest

from pydantic import ValidationError

from surgical_contracts import (
    CommandIntent,
    RobotCommandKind,
    RobotState,
    SimulationHealth,
    SimulationTelemetry,
)


class SchemaCompatibilityTests(unittest.TestCase):
    def test_existing_simulation_state_json_stays_unchanged(self) -> None:
        baseline = {
            "schema_version": "1.0",
            "state": {
                "schema_version": "1.0",
                "mode": "simulation",
                "tcp": "needle_tip",
                "tcp_position": {
                    "x": 530.73,
                    "y": 0.0,
                    "z": 520.75,
                    "unit": "mm",
                    "frame": "robot_base",
                    "source": "simulation",
                },
                "orientation_xyzw": [0.0, 0.9659258, 0.0, 0.258819],
                "motion_state": "idle",
                "estop": False,
                "active_command_id": None,
            },
            "sequence": 0,
            "joint_positions_deg": [0, 0, 60, 0, 90, 0],
            "trajectory_mm": [[530.73, 0.0, 520.75]],
            "frame_sequence": 1,
            "updated_at_ms": 1789617557938,
        }
        telemetry = SimulationTelemetry.model_validate(baseline)
        self.assertEqual(set(telemetry.model_dump()), set(baseline))
        self.assertEqual(set(telemetry.state.model_dump()), set(baseline["state"]))
        self.assertEqual(telemetry.model_dump(mode="json")["state"]["mode"], "simulation")

    def test_simulation_health_and_estop_names_remain_valid(self) -> None:
        health = SimulationHealth(
            status="healthy",
            worker_alive=True,
            initialized=True,
            ready=True,
            queue_depth=0,
        )
        self.assertEqual(health.service, "robot-simulation")
        self.assertEqual(CommandIntent.EMERGENCY_STOP.value, "emergency_stop")
        self.assertEqual(RobotCommandKind.ESTOP.value, "estop")
        self.assertNotIn("physical_estop_active", RobotState.model_fields)

    def test_old_schema_rejects_new_version_and_unknown_fields(self) -> None:
        with self.assertRaises(ValidationError):
            RobotState.model_validate(
                {
                    "schema_version": "2.0",
                    "tcp_position": {"x": 0, "y": 0, "z": 0},
                }
            )
        with self.assertRaises(ValidationError):
            RobotState.model_validate(
                {
                    "tcp_position": {"x": 0, "y": 0, "z": 0},
                    "physical_estop_active": False,
                }
            )


if __name__ == "__main__":
    unittest.main()
