from __future__ import annotations

import httpx

from agent.config import AgentSettings
from agent.openai_compat_http import OpenAICompatibleHTTPClient


def settings() -> AgentSettings:
    return AgentSettings(
        base_url="http://interns2.test/v1",
        api_key="test-key",
        model="test-model",
        timeout=5.0,
        max_retries=0,
        max_tokens=256,
        temperature=0.0,
        top_p=0.95,
        max_tool_rounds=1,
    )


def test_minimal_http_client_matches_agent_sdk_surface():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "test-model"}]})
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "function": {
                                        "name": "submit_surgical_task",
                                        "arguments": "{}",
                                    },
                                }
                            ]
                        }
                    }
                ]
            },
        )

    http = httpx.Client(
        base_url="http://interns2.test/v1",
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer test-key"},
    )
    client = OpenAICompatibleHTTPClient(settings(), client=http)

    assert client.models.list().data[0].id == "test-model"
    completion = client.chat.completions.create(
        model="test-model",
        messages=[{"role": "user", "content": "test"}],
        extra_body={"spaces_between_special_tokens": False},
    )
    assert completion.choices[0].message.tool_calls[0].id == "call-1"
    assert requests[1].headers["authorization"] == "Bearer test-key"
    assert b'"spaces_between_special_tokens":false' in requests[1].content

    client.close()
    assert not http.is_closed
    http.close()
