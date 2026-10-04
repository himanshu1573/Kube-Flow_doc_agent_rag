import asyncio
import importlib.util
import json
import unittest
from pathlib import Path
from unittest import mock

import httpx

APP_PATH = Path(__file__).resolve().parents[1] / "server-https" / "app.py"


def load_app_module():
    spec = importlib.util.spec_from_file_location("server_https_app", APP_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sse(*events):
    lines = [f"data: {json.dumps(event)}" for event in events]
    lines.append("data: [DONE]")
    return "\n\n".join(lines) + "\n\n"


def tool_call_delta(index, call_id, name, query):
    return {
        "choices": [
            {
                "index": 0,
                "delta": {
                    "tool_calls": [
                        {
                            "index": index,
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": json.dumps({"query": query})},
                        }
                    ]
                },
                "finish_reason": None,
            }
        ]
    }


def finish(reason):
    return {"choices": [{"index": 0, "delta": {}, "finish_reason": reason}]}


def content(text):
    return {"choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]}


class FakeLLM:
    """Scripted OpenAI-compatible streaming endpoint."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.headers = []

    def handler(self, request):
        self.requests.append(json.loads(request.content))
        self.headers.append(dict(request.headers))
        status, body, headers = self.responses.pop(0)
        return httpx.Response(status, text=body, headers=headers)

    def client_factory(self, real_client):
        transport = httpx.MockTransport(self.handler)

        def factory(*args, **kwargs):
            kwargs["transport"] = transport
            return real_client(*args, **kwargs)

        return factory


def fake_tool(tool_call):
    name = tool_call["function"]["name"]
    return f"results for {name}", [f"https://example.com/{name}"]


class ServerToolCallTests(unittest.TestCase):
    def setUp(self):
        self.app = load_app_module()
        self.payload = {
            "model": "test-model",
            "messages": [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "How do pipelines and manifests relate?"},
            ],
            "tools": [],
            "stream": True,
        }

    def run_chat(self, llm):
        real_client = httpx.AsyncClient
        with mock.patch.object(self.app.httpx, "AsyncClient", llm.client_factory(real_client)), \
                mock.patch.object(self.app, "execute_tool_call", side_effect=fake_tool):
            return asyncio.run(self.app.get_non_streaming_response(self.payload))

    def test_multiple_tool_calls_use_single_follow_up(self):
        llm = FakeLLM(
            [
                (200, sse(
                    tool_call_delta(0, "call_docs", "search_kubeflow_docs", "pipelines"),
                    tool_call_delta(1, "call_code", "search_kubeflow_code", "manifests"),
                    finish("tool_calls"),
                ), {}),
                (200, sse(content("Final answer."), finish("stop")), {}),
            ]
        )

        answer, citations = self.run_chat(llm)

        self.assertEqual(len(llm.requests), 2, "expected one tool round-trip, not one per tool")
        self.assertEqual(answer, "Final answer.")
        self.assertEqual(
            citations,
            ["https://example.com/search_kubeflow_docs", "https://example.com/search_kubeflow_code"],
        )

        follow_up = llm.requests[1]["messages"]
        assistant_turn = follow_up[-3]
        self.assertEqual(assistant_turn["role"], "assistant")
        self.assertEqual(
            [call["id"] for call in assistant_turn["tool_calls"]], ["call_docs", "call_code"]
        )
        tool_turns = follow_up[-2:]
        self.assertEqual([turn["role"] for turn in tool_turns], ["tool", "tool"])
        self.assertEqual(
            [turn["tool_call_id"] for turn in tool_turns], ["call_docs", "call_code"]
        )

    def test_follow_up_forbids_tools_and_never_loops_on_tool_use_failed(self):
        tool_use_failed = {"error": {"code": "tool_use_failed", "message": "model tried to call a tool"}}
        llm = FakeLLM(
            [
                (200, sse(
                    tool_call_delta(0, "call_docs", "search_kubeflow_docs", "kserve"),
                    finish("tool_calls"),
                ), {}),
                # The answer step misbehaves; it must not trigger another retrieval round.
                (200, sse(tool_use_failed), {}),
                (200, sse(tool_use_failed), {}),
                (200, sse(tool_use_failed), {}),
            ]
        )
        self.payload["tools"] = [{"type": "function", "function": {"name": "search_kubeflow_docs"}}]

        with self.assertRaises(Exception):
            self.run_chat(llm)

        self.assertEqual(len(llm.requests), 2, "tool_use_failed in the answer step must not loop")
        follow_up = llm.requests[1]
        self.assertEqual(follow_up["tool_choice"], "none")
        self.assertEqual(follow_up["tools"], self.payload["tools"])

    def test_rate_limit_is_retried_after_retry_after(self):
        rate_limited = json.dumps({"error": {"code": "rate_limit_exceeded"}})
        llm = FakeLLM(
            [
                (429, rate_limited, {"retry-after": "0"}),
                (200, sse(content("Recovered."), finish("stop")), {}),
            ]
        )

        answer, _ = self.run_chat(llm)

        self.assertEqual(answer, "Recovered.")
        self.assertEqual(len(llm.requests), 2)

    def test_rate_limit_is_retried_up_to_configured_attempts(self):
        rate_limited = json.dumps({"error": {"code": "rate_limit_exceeded"}})
        llm = FakeLLM(
            [
                (429, rate_limited, {"retry-after": "0"}),
                (429, rate_limited, {"retry-after": "0"}),
                (200, sse(content("Third time lucky."), finish("stop")), {}),
            ]
        )

        with mock.patch.object(self.app, "LLM_RATE_LIMIT_RETRIES", 2):
            answer, _ = self.run_chat(llm)

        self.assertEqual(answer, "Third time lucky.")
        self.assertEqual(len(llm.requests), 3)

    def test_chat_endpoint_returns_429_when_llm_stays_rate_limited(self):
        from fastapi.testclient import TestClient

        rate_limited = json.dumps({"error": {"code": "rate_limit_exceeded"}})
        llm = FakeLLM([(429, rate_limited, {"retry-after": "0"})] * (self.app.LLM_RATE_LIMIT_RETRIES + 1))
        real_client = httpx.AsyncClient
        with mock.patch.object(self.app.httpx, "AsyncClient", llm.client_factory(real_client)):
            response = TestClient(self.app.app).post(
                "/chat", json={"message": "What is Kubeflow?", "stream": False}
            )

        self.assertEqual(response.status_code, 429)
        self.assertIn("rate limit", response.json()["detail"])

    def test_retry_wait_is_bounded(self):
        self.assertEqual(self.app.retry_wait_seconds("3"), 3.0)
        self.assertEqual(self.app.retry_wait_seconds("120"), self.app.LLM_MAX_RETRY_WAIT)
        self.assertEqual(self.app.retry_wait_seconds("not-a-number"), 2.0)
        self.assertEqual(self.app.retry_wait_seconds(None), 2.0)


class ClientApiKeyTests(unittest.TestCase):
    """Bring-your-own LLM API key sent by the widget per request."""

    def setUp(self):
        self.app = load_app_module()
        self.llm = FakeLLM([(200, sse(content("Answer."), finish("stop")), {})])

    def post_chat(self, headers=None, **config):
        from fastapi.testclient import TestClient

        real_client = httpx.AsyncClient
        patches = [mock.patch.object(self.app, name, value) for name, value in config.items()]
        patches.append(mock.patch.object(self.app.httpx, "AsyncClient", self.llm.client_factory(real_client)))
        for patch in patches:
            patch.start()
        try:
            return TestClient(self.app.app).post(
                "/chat",
                json={"message": "What is Kubeflow?", "stream": False},
                headers=headers or {},
            )
        finally:
            for patch in reversed(patches):
                patch.stop()

    def test_client_key_overrides_server_key(self):
        response = self.post_chat({"X-LLM-API-Key": "user-key"}, LLM_API_KEY="server-key")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.llm.headers[0]["authorization"], "Bearer user-key")

    def test_server_key_used_when_client_sends_none(self):
        response = self.post_chat(LLM_API_KEY="server-key")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.llm.headers[0]["authorization"], "Bearer server-key")

    def test_client_model_override(self):
        response = self.post_chat(
            {"X-LLM-API-Key": "user-key", "X-LLM-Model": "openai/gpt-oss-120b"},
            MODEL="server-model",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.llm.requests[0]["model"], "openai/gpt-oss-120b")

    def test_required_client_key_rejects_requests_without_one(self):
        response = self.post_chat(LLM_API_KEY="server-key", REQUIRE_CLIENT_API_KEY=True)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.llm.requests, [], "the server key must not be used")

    def test_client_keys_ignored_when_disabled(self):
        response = self.post_chat(
            {"X-LLM-API-Key": "user-key"}, LLM_API_KEY="server-key", ALLOW_CLIENT_API_KEYS=False
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.llm.headers[0]["authorization"], "Bearer server-key")

    def test_malformed_client_key_is_rejected(self):
        response = self.post_chat({"X-LLM-API-Key": "two words"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.llm.requests, [])

    def test_provider_rejecting_the_key_returns_401(self):
        self.llm = FakeLLM([(401, json.dumps({"error": {"message": "Invalid API Key"}}), {})])

        response = self.post_chat({"X-LLM-API-Key": "user-key"})

        self.assertEqual(response.status_code, 401)
        self.assertIn("API key", response.json()["detail"])

    def test_config_reports_key_policy_without_leaking_the_key(self):
        from fastapi.testclient import TestClient

        with mock.patch.object(self.app, "LLM_API_KEY", "server-secret"), \
                mock.patch.object(self.app, "REQUIRE_CLIENT_API_KEY", True):
            body = TestClient(self.app.app).get("/config").json()

        self.assertTrue(body["require_client_api_key"])
        self.assertTrue(body["allow_client_api_keys"])
        self.assertTrue(body["server_api_key_configured"])
        self.assertNotIn("server-secret", json.dumps(body))


if __name__ == "__main__":
    unittest.main()
