from __future__ import annotations

import os
import unittest
from math import dist

import numpy as np

from simulation.entry_point_env import (
    ContinuousTrajectoryController,
    EntryPointEnvConfig,
    InvalidMotionCommand,
    WorkspaceViolationError,
)
from surgical_contracts import MotionState
from surgical_contracts import Point3D


CONFIG = EntryPointEnvConfig.from_yaml()
RUN_SOFA_INTEGRATION = os.environ.get("ENTRY_POINT_SOFA_TESTS") == "1"


def run_until_settled(controller: ContinuousTrajectoryController, maximum_steps: int = 1000):
    for _ in range(maximum_steps):
        step = controller.step()
        if step.state.motion_state != MotionState.MOVING:
            return step
    raise AssertionError("controller did not settle within maximum_steps")


class RelativeMotionControllerTests(unittest.TestCase):
    def test_positive_z_motion_is_continuous_and_exact(self):
        controller = ContinuousTrajectoryController(CONFIG)
        initial = controller.get_state().tcp_position
        controller.move_relative((0.0, 0.0, 5.0))
        step = run_until_settled(controller)

        self.assertEqual(step.state.motion_state, MotionState.IDLE)
        np.testing.assert_allclose(
            step.state.tcp_position.as_tuple(),
            (initial.x, initial.y, float(initial.z) + 5.0),
            atol=CONFIG.ik_position_tolerance_mm,
        )
        maximum_step = CONFIG.default_speed_mm_s * CONFIG.time_step_s
        jumps = [
            dist(start, end)
            for start, end in zip(controller.trajectory_mm, controller.trajectory_mm[1:])
        ]
        self.assertLessEqual(max(jumps), maximum_step + 1e-9)

    def test_low_speed_eight_mm_motion_does_not_stop_at_entry_tolerance(self):
        controller = ContinuousTrajectoryController(CONFIG)
        controller.move_to_entry(
            Point3D(x=500.0, y=0.0, z=500.0),
            speed_mm_s=CONFIG.maximum_speed_mm_s,
        )
        run_until_settled(controller)
        initial = controller.get_state().tcp_position

        controller.move_relative((0.0, 0.0, 8.0), speed_mm_s=5.0)
        step = run_until_settled(controller)

        self.assertEqual(step.state.motion_state, MotionState.IDLE)
        self.assertLessEqual(
            step.position_error_mm,
            CONFIG.ik_position_tolerance_mm,
        )
        self.assertAlmostEqual(
            float(step.state.tcp_position.z) - float(initial.z),
            8.0,
            delta=CONFIG.ik_position_tolerance_mm,
        )

    def test_stop_freezes_position(self):
        controller = ContinuousTrajectoryController(CONFIG)
        controller.move_relative((-20.0, 0.0, 0.0))
        controller.step()
        stopped_position = controller.stop().tcp_position

        for _ in range(20):
            controller.step()

        state = controller.get_state()
        self.assertEqual(state.motion_state, MotionState.STOPPED)
        self.assertEqual(state.tcp_position, stopped_position)

    def test_invalid_and_out_of_workspace_relative_motion_is_rejected(self):
        controller = ContinuousTrajectoryController(CONFIG)
        with self.assertRaises(InvalidMotionCommand):
            controller.move_relative((0.0, 0.0, 0.0))
        with self.assertRaises(InvalidMotionCommand):
            controller.move_relative((0.0, 0.0, 51.0))

        controller.move_to_entry(Point3D(x=699.0, y=0.0, z=500.0))
        run_until_settled(controller)
        with self.assertRaises(WorkspaceViolationError):
            controller.move_relative((5.0, 0.0, 0.0))

    def test_active_motion_cannot_be_silently_replaced(self):
        controller = ContinuousTrajectoryController(CONFIG)
        controller.move_relative((-20.0, 0.0, 0.0))
        with self.assertRaisesRegex(InvalidMotionCommand, "while it is moving"):
            controller.move_relative((0.0, 5.0, 0.0))


@unittest.skipUnless(
    RUN_SOFA_INTEGRATION,
    "set ENTRY_POINT_SOFA_TESTS=1 inside the simulation image",
)
class RelativeMotionSofaIntegrationTests(unittest.TestCase):
    def test_sofa_tcp_moves_positive_z_five_mm(self):
        from sofa_env.base import RenderMode

        from simulation.entry_point_env.environment import EntryPointReachEnv

        env = EntryPointReachEnv(config=CONFIG, render_mode=RenderMode.NONE)
        try:
            env.reset(seed=11)
            initial = np.asarray(env.scene_tcp_position_mm())
            env.move_relative((0.0, 0.0, 5.0))
            for _ in range(20):
                step = env.step()
                if step.state.motion_state != MotionState.MOVING:
                    break
            else:
                self.fail("SOFA environment did not finish relative motion")

            expected = initial + np.asarray([0.0, 0.0, 5.0])
            np.testing.assert_allclose(
                env.scene_tcp_position_mm(),
                expected,
                atol=CONFIG.reach_tolerance_mm,
            )
        finally:
            env.close()


if __name__ == "__main__":
    unittest.main()
