from __future__ import annotations

import unittest

from pydantic import ValidationError

from surgical_contracts import (
    ErrorCode,
    MoveToEntryResult,
    PlanPunctureResult,
    PlannerHealth,
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

    def test_successful_planner_result_requires_nonempty_preview_metadata(self):
        with self.assertRaisesRegex(ValidationError, "requires control_mode"):
            PlanPunctureResult(
                request_id="plan-1",
                status=PlannerStatus.SUCCESS,
                planner_name="mock",
                planner_version="mock-v1",
                output_schema_version="preview-v1",
                message="incomplete",
            )

    def test_planner_health_can_never_advertise_executable_output(self):
        with self.assertRaises(ValidationError):
            PlannerHealth(
                status="healthy",
                ready=True,
                provider="mock",
                planner_version="mock-v1",
                output_schema_version="preview-v1",
                executable=True,
                message="unsafe",
            )

    def test_planner_health_status_must_match_readiness(self):
        with self.assertRaisesRegex(ValidationError, "must agree"):
            PlannerHealth(
                status="healthy",
                ready=False,
                provider="external",
                planner_version="unconfigured",
                output_schema_version="preview-v1",
                message="not ready",
            )


if __name__ == "__main__":
    unittest.main()
