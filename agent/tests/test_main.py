from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
import unittest
from unittest.mock import patch

from agent.config import AgentSettings
from agent.main import main
from agent.runtime import ParsedCommandResponse
from surgical_contracts import CommandIntent, ParsedCommand, Point3D


def settings() -> AgentSettings:
    return AgentSettings(
        base_url="http://127.0.0.1:23333/v1",
        api_key="EMPTY",
        model="interns2-test",
        timeout=30,
        max_retries=0,
        max_tokens=512,
        temperature=0,
        top_p=0.95,
        max_tool_rounds=3,
    )


def parsed_response() -> ParsedCommandResponse:
    return ParsedCommandResponse(
        model="interns2-test",
        command=ParsedCommand(
            command_id="cmd-cli",
            intent=CommandIntent.PUNCTURE,
            entry_point=Point3D(x=20, y=35, z=80),
            target_point=Point3D(x=24, y=38, z=120),
            needs_confirmation=True,
        ),
    )


class AgentMainTests(unittest.TestCase):
    @patch("agent.main.InternS2Agent")
    @patch("agent.main.AgentSettings.from_env")
    def test_mock_execute_returns_plan_ready_without_puncture(
        self,
        from_env,
        agent_class,
    ):
        from_env.return_value = settings()
        agent_class.return_value.parse_command.return_value = parsed_response()
        output = StringIO()

        with redirect_stdout(output):
            exit_code = main(["--prompt", "test", "--mock-execute", "--json"])

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["orchestration"]["final_state"], "plan_ready")
        self.assertIn("未执行穿刺", payload["orchestration"]["message"])
        self.assertFalse(payload["orchestration"]["planner_result"]["executable"])

    @patch("agent.main.InternS2Agent")
    @patch("agent.main.AgentSettings.from_env")
    def test_parse_only_does_not_add_orchestration(self, from_env, agent_class):
        from_env.return_value = settings()
        agent_class.return_value.parse_command.return_value = parsed_response()
        output = StringIO()

        with redirect_stdout(output):
            exit_code = main(["--prompt", "test", "--parse-only", "--json"])

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertNotIn("orchestration", payload)


if __name__ == "__main__":
    unittest.main()
