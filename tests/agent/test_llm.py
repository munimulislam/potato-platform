"""
Tests for OpenAILLM against a local fake server that speaks the OpenAI chat API.
This uses the real openai client, so it checks what is actually sent and parsed,
without an API key or internet.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from potato_trial_pipeline.agent.llm import OpenAILLM
from potato_trial_pipeline.agent.tools.registry import tool_specs

MODULE = "potato_trial_pipeline.agent.llm"


def completion(message: dict, finish_reason: str) -> dict:
    return {
        "id": "test",
        "object": "chat.completion",
        "created": 0,
        "model": "test-model",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
    }


@pytest.fixture
def server(monkeypatch):
    """Answers each request with the next queued response and keeps the request bodies."""
    state = {"requests": [], "responses": []}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            state["requests"].append(json.loads(body))
            reply = json.dumps(state["responses"].pop(0)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    monkeypatch.setattr(f"{MODULE}.settings.llm_model", lambda: "test-model")
    monkeypatch.setattr(f"{MODULE}.settings.llm_api_key", lambda: "test-key")
    monkeypatch.setattr(f"{MODULE}.settings.llm_temperature", lambda: 0.0)
    monkeypatch.setattr(
        f"{MODULE}.settings.llm_base_url",
        lambda: f"http://127.0.0.1:{httpd.server_port}/v1",
    )
    yield state
    httpd.shutdown()


def test_request_contains_model_messages_tools_and_temperature(server):
    server["responses"].append(
        completion({"role": "assistant", "content": "hi"}, "stop")
    )
    messages = [{"role": "user", "content": "hello"}]

    turn = OpenAILLM().chat(messages, tool_specs())

    sent = server["requests"][0]
    assert sent["model"] == "test-model"
    assert sent["messages"] == messages
    assert sent["temperature"] == 0
    names = [t["function"]["name"] for t in sent["tools"]]
    assert names == ["run_sql", "rank_varieties"]
    assert all(t["type"] == "function" for t in sent["tools"])
    assert turn.text == "hi" and turn.tool_calls == []


def test_tool_calls_are_parsed(server):
    server["responses"].append(
        completion(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "rank_varieties",
                            "arguments": '{"trait": "o_a_score"}',
                        },
                    }
                ],
            },
            "tool_calls",
        )
    )

    turn = OpenAILLM().chat([{"role": "user", "content": "rank"}], tool_specs())

    assert turn.text is None
    assert [(c.id, c.name, c.arguments) for c in turn.tool_calls] == [
        ("call_1", "rank_varieties", '{"trait": "o_a_score"}')
    ]


def test_temperature_is_not_sent_when_disabled(server, monkeypatch):
    # Some reasoning models reject the temperature parameter entirely.
    monkeypatch.setattr(f"{MODULE}.settings.llm_temperature", lambda: None)
    server["responses"].append(
        completion({"role": "assistant", "content": "ok"}, "stop")
    )
    OpenAILLM().chat([{"role": "user", "content": "hi"}], tool_specs())
    assert "temperature" not in server["requests"][0]


def test_no_tools_are_sent_when_the_loop_wants_an_answer(server):
    server["responses"].append(
        completion({"role": "assistant", "content": "ok"}, "stop")
    )
    OpenAILLM().chat([{"role": "user", "content": "hi"}], [])
    assert "tools" not in server["requests"][0]
