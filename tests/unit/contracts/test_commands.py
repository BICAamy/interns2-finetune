from __future__ import annotations

import unittest

from pydantic import ValidationError

from surgical_contracts import (
    Axis,
    CommandIntent,
    CoordinateFrame,
    Direction,
    ParsedCommand,
    Point3D,
    RelativeMotion,
)


def point(x: float, y: float, z: float) -> Point3D:
    return Point3D(x=x, y=y, z=z)


class ParsedCommandTests(unittest.TestCase):
    def test_puncture_requires_both_distinct_points(self):
        command = ParsedCommand(
            command_id="cmd-puncture",
            intent=CommandIntent.PUNCTURE,
            entry_point=point(1, 2, 3),
            target_point=point(4, 5, 6),
        )

        self.assertEqual(command.intent, CommandIntent.PUNCTURE)

        with self.assertRaisesRegex(ValidationError, "requires target_point"):
            ParsedCommand(
                command_id="cmd-missing-target",
                intent=CommandIntent.PUNCTURE,
                entry_point=point(1, 2, 3),
            )
        with self.assertRaisesRegex(ValidationError, "must be different"):
            ParsedCommand(
                command_id="cmd-same-points",
                intent=CommandIntent.PUNCTURE,
                entry_point=point(1, 2, 3),
                target_point=point(1, 2, 3),
            )

    def test_move_to_entry_rejects_target_point(self):
        with self.assertRaisesRegex(ValidationError, "only accepts entry_point"):
            ParsedCommand(
                command_id="cmd-entry",
                intent=CommandIntent.MOVE_TO_ENTRY,
                entry_point=point(1, 2, 3),
                target_point=point(4, 5, 6),
            )

    def test_relative_motion_requires_only_relative_payload(self):
        relative = RelativeMotion(
            axis=Axis.Z,
            direction=Direction.POSITIVE,
            distance_mm=5,
        )
        command = ParsedCommand(
            command_id="cmd-relative",
            intent=CommandIntent.MOVE_RELATIVE,
            relative_motion=relative,
        )

        self.assertEqual(command.relative_motion.translation_mm(), (0.0, 0.0, 5.0))
        with self.assertRaisesRegex(ValidationError, "cannot contain entry"):
            ParsedCommand(
                command_id="cmd-bad-relative",
                intent=CommandIntent.MOVE_RELATIVE,
                entry_point=point(1, 2, 3),
                relative_motion=relative,
            )

    def test_clarify_can_retain_partial_non_executable_coordinates(self):
        command = ParsedCommand(
            command_id="cmd-clarify",
            intent=CommandIntent.CLARIFY,
            entry_point=point(1, 2, 3),
            missing_fields=["target_point"],
            needs_confirmation=True,
            summary="Please provide the target point",
        )

        self.assertEqual(command.entry_point, point(1, 2, 3))

    def test_clarify_requires_a_question_and_missing_fields(self):
        with self.assertRaisesRegex(ValidationError, "requires at least one"):
            ParsedCommand(
                command_id="cmd-empty-clarify",
                intent=CommandIntent.CLARIFY,
                needs_confirmation=True,
                summary="What is missing?",
            )
        with self.assertRaisesRegex(ValidationError, "needs_confirmation=true"):
            ParsedCommand(
                command_id="cmd-unconfirmed-clarify",
                intent=CommandIntent.CLARIFY,
                missing_fields=["target_point"],
                summary="Please provide the target point",
            )

    def test_executable_command_cannot_claim_missing_fields(self):
        with self.assertRaisesRegex(ValidationError, "cannot contain missing_fields"):
            ParsedCommand(
                command_id="cmd-invalid-missing",
                intent=CommandIntent.MOVE_TO_ENTRY,
                entry_point=point(1, 2, 3),
                missing_fields=["target_point"],
            )

    def test_models_reject_unknown_fields_and_non_finite_coordinates(self):
        with self.assertRaises(ValidationError):
            Point3D(x=1, y=2, z=3, unexpected=True)
        with self.assertRaises(ValidationError):
            Point3D(x=float("nan"), y=2, z=3)
        with self.assertRaises(ValidationError):
            Point3D(x=1, y=2, z=float("inf"))

    def test_points_in_different_frames_cannot_form_a_puncture(self):
        with self.assertRaisesRegex(ValidationError, "same frame"):
            ParsedCommand(
                command_id="cmd-frame",
                intent=CommandIntent.PUNCTURE,
                entry_point=point(1, 2, 3),
                target_point=Point3D(
                    x=4,
                    y=5,
                    z=6,
                    frame=CoordinateFrame.SIMULATION_WORLD,
                ),
            )


if __name__ == "__main__":
    unittest.main()
