from __future__ import annotations

import unittest

from pydantic import ValidationError

from surgical_contracts import (
    ErrorCode,
    MoveToEntryResult,
    PlanPunctureResult,
    PlannerStatus,
    Point3D,
    ToolStatus,
)


class ResultContractTests(unittest.TestCase):
    def test_successful_move_result_must_reach_entry(self):
        with self.assertRaisesRegex(ValidationError, "reached=true"):
            MoveToEntryResult(
                command_id="cmd-1",
                status=ToolStatus.SUCCESS,
                reached=False,
                final_tcp_position=Point3D(x=0, y=0, z=0),
                position_error_mm=5,
                message="invalid success",
            )

    def test_failed_move_result_requires_error_code(self):
        with self.assertRaisesRegex(ValidationError, "requires error_code"):
            MoveToEntryResult(
                command_id="cmd-1",
                status=ToolStatus.FAILED,
                reached=False,
                final_tcp_position=Point3D(x=0, y=0, z=0),
                message="failed",
            )

    def test_v1_planner_result_cannot_be_executable(self):
        with self.assertRaises(ValidationError):
            PlanPunctureResult(
                request_id="plan-1",
                status=PlannerStatus.SUCCESS,
                planner_name="fake",
                planner_version="fake-v1",
                output_schema_version="preview-v1",
                executable=True,
                message="unsafe",
            )

    def test_failed_planner_result_requires_error_code(self):
        result = PlanPunctureResult(
            request_id="plan-1",
            status=PlannerStatus.TIMED_OUT,
            planner_name="fake",
            planner_version="fake-v1",
            output_schema_version="preview-v1",
            message="timeout",
            error_code=ErrorCode.PLANNER_TIMEOUT,
        )

        self.assertFalse(result.executable)


if __name__ == "__main__":
    unittest.main()
