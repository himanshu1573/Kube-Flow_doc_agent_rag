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

    def handler(self, request):
        self.requests.append(json.loads(request.content))
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


if __name__ == "__main__":
    unittest.main()
