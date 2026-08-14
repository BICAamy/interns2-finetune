from __future__ import annotations

import unittest

import numpy as np
from scipy.spatial.transform import Rotation

from simulation.entry_point_env import (
    ContinuousTrajectoryController,
    E05ProKinematics,
    EntryPointEnvConfig,
)


CONFIG = EntryPointEnvConfig.from_yaml()


class E05ProConfigurationTests(unittest.TestCase):
    def test_force_variant_and_provisional_tcp_are_explicit(self):
        self.assertEqual(CONFIG.robot.model_name, "E05-Pro")
        self.assertTrue(CONFIG.robot.force_control_variant)
        self.assertEqual(CONFIG.robot.force_flange_offset_mm, 184.0)
        self.assertEqual(
            CONFIG.robot.tool_transform.translation_mm,
            (0.0, 0.0, 150.0),
        )
        self.assertTrue(CONFIG.robot.tool_transform.provisional)
        self.assertFalse(CONFIG.robot.tool_transform.real_robot_motion_allowed)
        self.assertFalse(CONFIG.real_robot_ready)

    def test_vendor_source_is_pinned(self):
        self.assertEqual(
            CONFIG.robot.source_repository,
            E05ProKinematics.SOURCE_REPOSITORY,
        )
        self.assertEqual(CONFIG.robot.source_commit, E05ProKinematics.SOURCE_COMMIT)
        self.assertEqual(CONFIG.robot.source_variant, E05ProKinematics.SOURCE_VARIANT)


class E05ProKinematicsTests(unittest.TestCase):
    def setUp(self):
        self.controller = ContinuousTrajectoryController(CONFIG)
        self.kinematics = self.controller.kinematics

    def test_zero_pose_matches_force_dimension_chain_and_tool_offset(self):
        snapshot = self.kinematics.forward(np.zeros(6))
        np.testing.assert_allclose(
            snapshot.flange_transform[:3, 3],
            (0.0, 0.0, 1204.0),
            atol=0.01,
        )
        np.testing.assert_allclose(
            snapshot.tcp_transform[:3, 3],
            (0.0, 0.0, 1354.0),
            atol=0.01,
        )

    def test_initial_pose_is_non_singular_and_inside_workspace(self):
        tcp_position = self.controller.get_state().tcp_position.as_tuple()
        np.testing.assert_allclose(
            tcp_position,
            (530.7307, 0.0, 520.7475),
            atol=0.01,
        )
        self.assertTrue(CONFIG.workspace.contains(tcp_position))

    def test_inverse_forward_round_trip_preserves_configured_orientation(self):
        initial = self.controller.kinematic_snapshot
        target_orientation = Rotation.from_matrix(initial.tcp_transform[:3, :3])
        target_position = np.asarray((450.0, 50.0, 450.0))

        solution = self.kinematics.inverse(
            target_position,
            target_orientation,
            np.deg2rad(CONFIG.robot.initial_joint_positions_deg),
        )
        solved = self.kinematics.forward(solution.joint_positions_rad)

        np.testing.assert_allclose(
            solved.tcp_transform[:3, 3],
            target_position,
            atol=CONFIG.ik_position_tolerance_mm,
        )
        self.assertLessEqual(
            solution.orientation_error_rad,
            np.deg2rad(CONFIG.ik_orientation_tolerance_deg),
        )

    def test_joint_limits_match_purchased_robot_datasheet(self):
        expected = np.asarray(
            [
                [-360.0, 360.0],
                [-135.0, 135.0],
                [-153.0, 153.0],
                [-360.0, 360.0],
                [-180.0, 180.0],
                [-360.0, 360.0],
            ]
        )
        np.testing.assert_allclose(CONFIG.robot.joint_limits_deg, expected)


if __name__ == "__main__":
    unittest.main()
