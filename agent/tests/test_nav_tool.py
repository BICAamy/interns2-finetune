from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from agent.config import AgentSettings
from agent.runtime import InternS2NavigationAgent
from agent.tools.NavGPT.nav_src.nav_tool import NavGPTTool


class FakeNavChatClient:
    model = "fake-deepseek"

    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def chat(self, messages, *, json_mode=False, stop=None):
        self.calls.append({"messages": messages, "json_mode": json_mode})
        return next(self.responses)


class NavGPTToolTests(unittest.TestCase):
    def test_selects_exact_candidate(self):
        response = json.dumps(
            {
                "status": "move",
                "next_viewpoint_id": "door-a",
                "direction": "front-left",
                "action": "Move toward door A.",
                "reason": "It matches the requested exit.",
                "action_plan": ["Approach door A", "Re-observe after crossing"],
            }
        )
        client = FakeNavChatClient([response])
        result = NavGPTTool(client).navigate(
            instruction="Go to the exit",
            observation="An open exit is visible at the front-left.",
            navigable_viewpoints=[{"id": "door-a", "direction": "front-left"}],
        )
        self.assertEqual(result["decision"]["next_viewpoint_id"], "door-a")
        self.assertEqual(result["candidate_ids"], ["door-a"])

    def test_retries_an_invented_candidate_id(self):
        invalid = json.dumps(
            {
                "status": "move",
                "next_viewpoint_id": "invented",
                "direction": "left",
                "action": "Move left.",
                "reason": "Possible route.",
                "action_plan": ["Move"],
            }
        )
        valid = json.dumps(
            {
                "status": "move",
                "next_viewpoint_id": "real-id",
                "direction": "left",
                "action": "Move to real-id.",
                "reason": "It is the supplied left candidate.",
                "action_plan": ["Move"],
            }
        )
        client = FakeNavChatClient([invalid, valid])
        result = NavGPTTool(client).navigate(
            instruction="Turn left",
            observation="A corridor continues left.",
            navigable_viewpoints=[{"id": "real-id"}],
        )
        self.assertEqual(result["decision"]["next_viewpoint_id"], "real-id")
        self.assertEqual(len(client.calls), 2)


class FakeCompletions:
    def __init__(self):
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if len(self.requests) == 1:
            tool_call = SimpleNamespace(
                id="call-1",
                function=SimpleNamespace(
                    name="navgpt_navigation",
                    arguments=json.dumps(
                        {
                            "instruction": "Find the door",
                            "observation": "A door is visible ahead.",
                            "navigable_viewpoints": [],
                        }
                    ),
                ),
            )
            message = SimpleNamespace(content="", tool_calls=[tool_call], reasoning_content=None)
        else:
            message = SimpleNamespace(
                content="The doorway ahead is the best grounded next direction.",
                tool_calls=[],
                reasoning_content=None,
            )
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeInternS2Client:
    def __init__(self):
        self.chat = SimpleNamespace(completions=FakeCompletions())


class FakeNavTool:
    def navigate(self, **kwargs):
        return {
            "decision": {
                "status": "move",
                "next_viewpoint_id": None,
                "direction": "forward",
                "action": "Approach the doorway cautiously.",
                "reason": "The door is visible ahead.",
                "action_plan": ["Move forward"],
            }
        }


class AgentLoopTests(unittest.TestCase):
    def test_image_tool_loop_returns_final_answer(self):
        settings = AgentSettings(
            base_url="http://localhost:23333/v1",
            api_key="EMPTY",
            model="interns2-test",
            timeout=30,
            max_retries=0,
            max_tokens=128,
            temperature=0.0,
            top_p=0.95,
            max_tool_rounds=2,
        )
        client = FakeInternS2Client()
        agent = InternS2NavigationAgent(settings, navgpt_tool=FakeNavTool(), client=client)
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "scene.jpg"
            image.write_bytes(b"test-image-bytes")
            result = agent.run(image, "Where should I go?")

        self.assertIn("doorway", result.answer)
        self.assertEqual(len(result.tool_events), 1)
        second_messages = client.chat.completions.requests[1]["messages"]
        self.assertEqual(second_messages[-1]["role"], "tool")


if __name__ == "__main__":
    unittest.main()
