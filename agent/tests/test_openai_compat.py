from __future__ import annotations

import json
import unittest

import httpx
try:
    from openai import OpenAI
except ImportError:  # Standalone agent-web intentionally uses its HTTP facade.
    OpenAI = None

from agent.config import AgentSettings
from agent.runtime import InternS2Agent
from surgical_contracts import CommandIntent


class OpenAICompatibilityTests(unittest.TestCase):
    @unittest.skipIf(OpenAI is None, "official OpenAI SDK is not installed")
    def test_real_sdk_serializes_tool_and_decodes_lmdeploy_shape(self):
        requests: list[dict] = []
        arguments = {
            "intent": "move_relative",
            # LMDeploy 0.14's XML parser can stringify each non-string
            # parameter even though the top-level arguments are valid JSON.
            "entry_point": "null",
            "target_point": "null",
            "relative_motion": json.dumps(
                {"axis": "z", "direction": "positive"}
            ),
            "missing_fields": "[]",
            "needs_confirmation": "false",
            "confidence": "0.99",
            "summary": "机械臂往上抬一点",
        }

        def handle(request: httpx.Request) -> httpx.Response:
            requests.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "id": "chatcmpl-step7",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "interns2-test",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "tool_calls",
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call-step7",
                                        "type": "function",
                                        "function": {
                                            "name": "submit_surgical_task",
                                            "arguments": json.dumps(
                                                arguments,
                                                ensure_ascii=False,
                                            ),
                                        },
                                    }
                                ],
                            },
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    },
                },
            )

        http_client = httpx.Client(transport=httpx.MockTransport(handle))
        client = OpenAI(
            api_key="EMPTY",
            base_url="http://lmdeploy.test/v1",
            http_client=http_client,
        )
        settings = AgentSettings(
            base_url="http://lmdeploy.test/v1",
            api_key="EMPTY",
            model="interns2-test",
            timeout=30,
            max_retries=0,
            max_tokens=512,
            temperature=0,
            top_p=0.95,
            max_tool_rounds=3,
        )
        try:
            result = InternS2Agent(
                settings,
                client=client,
                command_id_factory=lambda: "cmd-openai-sdk",
            ).parse_command("机械臂往上抬一点")
        finally:
            http_client.close()

        self.assertEqual(result.command.intent, CommandIntent.MOVE_RELATIVE)
        self.assertEqual(result.command.command_id, "cmd-openai-sdk")
        self.assertEqual(result.command.relative_motion.distance_mm, 5.0)
        self.assertFalse(result.command.needs_confirmation)
        self.assertEqual(
            requests[0]["tools"][0]["function"]["name"],
            "submit_surgical_task",
        )
        self.assertNotIn("tool_choice", requests[0])


if __name__ == "__main__":
    unittest.main()
