from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from agent.config import AgentSettings
from agent.runtime import InternS2Agent


def make_settings(model: str | None = "interns2-test") -> AgentSettings:
    return AgentSettings(
        base_url="http://localhost:23333/v1",
        api_key="EMPTY",
        model=model,
        timeout=30,
        max_retries=0,
        max_tokens=128,
        temperature=0.0,
        top_p=0.95,
        max_tool_rounds=3,
    )


class FakeCompletions:
    def __init__(self, content: str = "InternS2 is ready.") -> None:
        self.content = content
        self.requests: list[dict] = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        message = SimpleNamespace(content=self.content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeInternS2Client:
    def __init__(self, *, content: str = "InternS2 is ready.") -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions(content))
        self.models = SimpleNamespace(
            list=lambda: SimpleNamespace(
                data=[SimpleNamespace(id="discovered-interns2")]
            )
        )


class InternS2AgentTests(unittest.TestCase):
    def test_text_request_does_not_register_legacy_tools(self):
        client = FakeInternS2Client()
        agent = InternS2Agent(make_settings(), client=client)

        result = agent.run("Check the model.")

        self.assertEqual(result.answer, "InternS2 is ready.")
        request = client.chat.completions.requests[0]
        self.assertNotIn("tools", request)
        self.assertNotIn("tool_choice", request)
        self.assertEqual(request["messages"][1]["content"], "Check the model.")

    def test_optional_image_is_encoded_as_a_data_url(self):
        client = FakeInternS2Client(content="Image received.")
        agent = InternS2Agent(make_settings(), client=client)
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "scene.jpg"
            image.write_bytes(b"test-image-bytes")

            result = agent.run("Describe it.", image_path=image)

        self.assertEqual(result.answer, "Image received.")
        content = client.chat.completions.requests[0]["messages"][1]["content"]
        self.assertEqual(content[0]["type"], "image_url")
        self.assertTrue(content[0]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(content[1], {"type": "text", "text": "Describe it."})

    def test_model_is_discovered_when_not_configured(self):
        agent = InternS2Agent(make_settings(model=None), client=FakeInternS2Client())

        self.assertEqual(agent.model, "discovered-interns2")

    def test_empty_prompt_is_rejected_without_calling_model(self):
        client = FakeInternS2Client()
        agent = InternS2Agent(make_settings(), client=client)

        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            agent.run("   ")

        self.assertEqual(client.chat.completions.requests, [])


if __name__ == "__main__":
    unittest.main()
