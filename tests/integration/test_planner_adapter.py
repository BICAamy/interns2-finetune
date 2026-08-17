from __future__ import annotations

from dataclasses import replace
import unittest

from fastapi.testclient import TestClient

from planner_adapter.config import (
    MockPlannerOutcome,
    PlannerAdapterSettings,
    PlannerProviderKind,
)
from planner_adapter.main import create_app
from planner_adapter.providers import MockPuncturePlannerProvider


def settings(
    *,
    outcome: MockPlannerOutcome = MockPlannerOutcome.SUCCESS,
    provider: PlannerProviderKind = PlannerProviderKind.MOCK,
) -> PlannerAdapterSettings:
    return PlannerAdapterSettings(provider=provider, mock_outcome=outcome)


def point(x: float, y: float, z: float, *, frame: str = "robot_base") -> dict:
    return {
        "x": x,
        "y": y,
        "z": z,
        "unit": "mm",
        "frame": frame,
        "source": "structured_data",
    }


def request_payload() -> dict:
    return {
        "schema_version": "1.0",
        "request_id": "plan-api-001",
        "command_id": "cmd-api-001",
        "entry_point": point(20.0, 35.0, 80.0),
        "target_point": point(24.0, 38.0, 120.0),
    }


class PlannerAdapterApiTests(unittest.TestCase):
    def test_health_exposes_selected_provider_and_safety_boundary(self):
        with TestClient(create_app(settings())) as client:
            response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "healthy")
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["provider"], "mock")
        self.assertEqual(payload["planner_version"], "mock-v1")
        self.assertEqual(payload["output_schema_version"], "preview-v1")
        self.assertFalse(payload["executable"])

    def test_success_returns_endpoint_preview_that_is_never_executable(self):
        provider = MockPuncturePlannerProvider()
        app = create_app(settings(), provider)
        with TestClient(app) as client:
            response = client.post("/v1/plan", json=request_payload())

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["planner_name"], "mock")
        self.assertEqual(payload["planner_version"], "mock-v1")
        self.assertEqual(payload["output_schema_version"], "preview-v1")
        self.assertEqual(payload["control_mode"], "mock_preview")
        self.assertEqual(
            payload["control_payload"]["preview_points_mm"],
            [[20.0, 35.0, 80.0], [24.0, 38.0, 120.0]],
        )
        self.assertEqual(payload["control_payload"]["frame"], "robot_base")
        self.assertFalse(payload["executable"])
        self.assertEqual(provider.call_count, 1)

    def test_fault_modes_return_valid_non_executable_envelopes(self):
        cases = {
            MockPlannerOutcome.FAILURE: ("failed", "INVALID_PLANNER_OUTPUT"),
            MockPlannerOutcome.TIMEOUT: ("timed_out", "PLANNER_TIMEOUT"),
            MockPlannerOutcome.INVALID_SCHEMA: (
                "failed",
                "INVALID_PLANNER_OUTPUT",
            ),
            MockPlannerOutcome.VERSION_MISMATCH: (
                "failed",
                "INVALID_PLANNER_OUTPUT",
            ),
        }
        for outcome, expected in cases.items():
            with self.subTest(outcome=outcome.value):
                with TestClient(create_app(settings(outcome=outcome))) as client:
                    response = client.post("/v1/plan", json=request_payload())
                payload = response.json()
                self.assertEqual(response.status_code, 200)
                self.assertEqual(payload["status"], expected[0])
                self.assertEqual(payload["error_code"], expected[1])
                self.assertFalse(payload["executable"])
                self.assertEqual(payload["control_payload"], {})

    def test_version_mismatch_is_not_leaked_as_a_success(self):
        configured = replace(
            settings(outcome=MockPlannerOutcome.VERSION_MISMATCH),
            expected_output_schema_version="preview-v1",
        )
        with TestClient(create_app(configured)) as client:
            payload = client.post("/v1/plan", json=request_payload()).json()

        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["output_schema_version"], "preview-v1")
        self.assertIn("version mismatch", payload["message"].lower())

    def test_invalid_request_uses_stable_error_response(self):
        provider = MockPuncturePlannerProvider()
        invalid_requests = (
            {**request_payload(), "unknown": "not allowed"},
            {**request_payload(), "schema_version": "2.0"},
            {
                **request_payload(),
                "target_point": point(24.0, 38.0, 120.0, frame="simulation_world"),
            },
            {
                **request_payload(),
                "target_point": point(20.0, 35.0, 80.0),
            },
        )
        with TestClient(create_app(settings(), provider)) as client:
            for payload in invalid_requests:
                with self.subTest(payload=payload):
                    response = client.post("/v1/plan", json=payload)
                    self.assertEqual(response.status_code, 422)
                    self.assertEqual(
                        response.json()["code"],
                        "INVALID_COMMAND_SCHEMA",
                    )
        self.assertEqual(provider.call_count, 0)

    def test_external_placeholder_makes_no_transport_assumptions(self):
        configured = settings(provider=PlannerProviderKind.EXTERNAL)
        with TestClient(create_app(configured)) as client:
            health = client.get("/health")
            response = client.post("/v1/plan", json=request_payload())

        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "unhealthy")
        self.assertFalse(health.json()["ready"])
        self.assertEqual(health.json()["provider"], "external")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "unavailable")
        self.assertEqual(response.json()["error_code"], "PLANNER_UNAVAILABLE")
        self.assertFalse(response.json()["executable"])

    def test_settings_reject_invalid_runtime_values(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 65535"):
            replace(settings(), port=70000).validate()
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            replace(settings(), request_timeout_s=0).validate()


if __name__ == "__main__":
    unittest.main()
