"""
Tests for cli.py: an LLM that does not answer must not crash the chat or lose the conversation.
"""

from openai import APITimeoutError

from potato_data_agent import cli
from potato_data_agent.llm import AssistantTurn, FakeLLM

MODULE = "potato_data_agent.cli"


class TimesOutOnceLLM(FakeLLM):
    """First call times out, later calls follow the script."""

    def __init__(self, script):
        super().__init__(script)
        self.timed_out = False

    def chat(self, messages, tools):
        if not self.timed_out:
            self.timed_out = True
            raise APITimeoutError(request=None)
        return super().chat(messages, tools)


def test_timeout_is_reported_and_the_chat_continues(monkeypatch, capsys, tmp_path):
    llm = TimesOutOnceLLM([AssistantTurn(text="second try worked")])
    inputs = iter(["first question", "first question", "/exit"])
    monkeypatch.setattr(f"{MODULE}.OpenAILLM", lambda: llm)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    monkeypatch.setattr(
        "potato_data_agent.loop.AGENT_LOG", tmp_path / "agent_runs.jsonl"
    )
    monkeypatch.setattr("potato_data_agent.loop.tool_specs", lambda: [])
    monkeypatch.setattr("potato_data_agent.loop.schema_card", lambda: "")

    cli.main()

    out = capsys.readouterr().out
    assert "did not respond: APITimeoutError" in out
    assert "Agent: second try worked" in out
