"""
Tests for loop.py with a scripted FakeLLM: no real LLM, no database, no R.
The tools are replaced by a fake registry, so only the loop's own logic is tested.
"""

import json

import pytest

from potato_trial_pipeline.agent.llm import AssistantTurn, FakeLLM, ToolCall
from potato_trial_pipeline.agent.loop import GAVE_UP_MESSAGE, answer, load_system_prompt

MODULE = "potato_trial_pipeline.agent.loop"


@pytest.fixture
def tools(monkeypatch, tmp_path):
    """A fake registry that records calls, and a log file in tmp_path."""
    calls = []

    def fake_run_tool(name, arguments):
        calls.append((name, arguments))
        if arguments.get("trait") == "bad":
            return json.dumps({"error": "Unknown or non-rankable trait 'bad'."})
        return json.dumps({"tool": name, "ok": True})

    monkeypatch.setattr(f"{MODULE}.run_tool", fake_run_tool)
    monkeypatch.setattr(f"{MODULE}.tool_specs", lambda: [{"name": "rank_varieties"}])
    monkeypatch.setattr(f"{MODULE}.AGENT_LOG", tmp_path / "logs" / "agent_runs.jsonl")
    monkeypatch.setattr(f"{MODULE}.schema_card", lambda: "# Database (test)")
    return calls


def call(id, name="rank_varieties", **arguments):
    return ToolCall(id=id, name=name, arguments=json.dumps(arguments))


def tool_messages(request):
    return [m for m in request if m["role"] == "tool"]


# ---------------------------------------------------------------------------------------
# The basic flows
# ---------------------------------------------------------------------------------------
def test_direct_answer_needs_one_round(tools):
    llm = FakeLLM([AssistantTurn(text="Hello")])
    result = answer("hi", llm)
    assert result.answer == "Hello"
    assert (result.rounds, result.stopped_reason) == (1, "final_answer")
    assert tools == []
    assert llm.requests[0][0]["role"] == "system"  # the system prompt is always first


def test_tool_call_then_answer(tools):
    llm = FakeLLM(
        [
            AssistantTurn(tool_calls=[call("c1", trait="o_a_score", top_n=5)]),
            AssistantTurn(text="Cristina is top."),
        ]
    )
    result = answer("best appearance?", llm)

    # the tool got exactly the arguments the LLM sent
    assert tools == [("rank_varieties", {"trait": "o_a_score", "top_n": 5})]
    # the assistant turn is kept, and the tool result carries the same id
    second_request = llm.requests[1]
    assert second_request[-2]["tool_calls"][0]["id"] == "c1"
    assert tool_messages(second_request)[0]["tool_call_id"] == "c1"
    assert result.rounds == 2 and result.answer == "Cristina is top."
    assert result.tool_calls[0].name == "rank_varieties"


def test_two_tool_calls_in_one_turn_both_run_in_order(tools):
    llm = FakeLLM(
        [
            AssistantTurn(
                tool_calls=[call("a", trait="o_a_score"), call("b", trait="ffdefects")]
            ),
            AssistantTurn(text="done"),
        ]
    )
    answer("two traits", llm)
    assert [args["trait"] for _, args in tools] == ["o_a_score", "ffdefects"]
    assert [m["tool_call_id"] for m in tool_messages(llm.requests[1])] == ["a", "b"]


# ---------------------------------------------------------------------------------------
# Errors go back to the LLM so it can correct itself
# ---------------------------------------------------------------------------------------
def test_tool_error_is_sent_back_and_the_retry_runs(tools):
    llm = FakeLLM(
        [
            AssistantTurn(tool_calls=[call("c1", trait="bad")]),
            AssistantTurn(tool_calls=[call("c2", trait="o_a_score")]),
            AssistantTurn(text="fixed"),
        ]
    )
    result = answer("q", llm)
    assert "non-rankable" in tool_messages(llm.requests[1])[0]["content"]
    assert [args["trait"] for _, args in tools] == ["bad", "o_a_score"]
    assert result.answer == "fixed" and result.rounds == 3


@pytest.mark.parametrize("raw", ["{not json", "[1, 2]"])
def test_broken_arguments_are_reported_not_run(tools, raw):
    llm = FakeLLM(
        [
            AssistantTurn(
                tool_calls=[ToolCall(id="c1", name="rank_varieties", arguments=raw)]
            ),
            AssistantTurn(text="sorry"),
        ]
    )
    answer("q", llm)
    assert tools == []  # the tool never ran
    content = json.loads(tool_messages(llm.requests[1])[0]["content"])
    assert "arguments" in content["error"]


# ---------------------------------------------------------------------------------------
# Limits, history and the audit log
# ---------------------------------------------------------------------------------------
def test_endless_tool_calls_stop_at_max_rounds(tools, monkeypatch):
    monkeypatch.setattr(f"{MODULE}.MAX_ROUNDS", 3)
    llm = FakeLLM(
        # different arguments every round, so these are not repeats
        [AssistantTurn(tool_calls=[call(f"c{i}", trait=f"x{i}")]) for i in range(3)]
    )
    result = answer("q", llm)
    assert result.stopped_reason == "max_rounds" and result.rounds == 3
    assert result.answer == GAVE_UP_MESSAGE
    assert len(llm.requests) == 3  # never more LLM calls than the limit


def test_follow_up_question_sees_the_previous_exchange(tools):
    llm = FakeLLM(
        [AssistantTurn(text="first answer"), AssistantTurn(text="second answer")]
    )
    first = answer("first question", llm)
    answer("and in Spain?", llm, first.messages)

    contents = [m["content"] for m in llm.requests[1]]
    assert contents[1:] == ["first question", "first answer", "and in Spain?"]


def test_every_question_is_logged_once_as_valid_json(tools, tmp_path):
    llm = FakeLLM(
        [
            AssistantTurn(tool_calls=[call("c1", trait="o_a_score")]),
            AssistantTurn(text="answer one"),
            AssistantTurn(text="answer two"),
        ]
    )
    answer("q1", llm)
    answer("q2", llm)

    lines = (tmp_path / "logs" / "agent_runs.jsonl").read_text().splitlines()
    entries = [json.loads(line) for line in lines]
    assert [e["question"] for e in entries] == ["q1", "q2"]
    assert entries[0]["tool_calls"][0]["arguments"] == '{"trait": "o_a_score"}'
    assert entries[0]["model"] == "fake"


def test_system_prompt_names_the_real_tools():
    prompt = load_system_prompt()
    for name in ("run_sql", "rank_varieties", "distinguishable_from_top"):
        assert name in prompt


# ---------------------------------------------------------------------------------------
# Repeated calls: seen in a real run (rank_varieties called 6 times with the same arguments)
# ---------------------------------------------------------------------------------------
class RecordingFakeLLM(FakeLLM):
    """Also records which tools were offered on each round."""

    def __init__(self, script):
        super().__init__(script)
        self.tools_offered = []

    def chat(self, messages, tools):
        self.tools_offered.append(tools)
        return super().chat(messages, tools)


def test_repeated_call_is_not_run_again_and_the_model_must_answer(tools):
    same = {"trait": "yield"}
    same_with_nulls = {"trait": "yield", "env_type": None, "locations": None}
    llm = RecordingFakeLLM(
        [
            AssistantTurn(tool_calls=[call("c1", **same)]),
            AssistantTurn(tool_calls=[call("c2", **same_with_nulls)]),
            AssistantTurn(text="t18293/22 is top."),
        ]
    )
    result = answer("best yield?", llm)

    assert tools == [("rank_varieties", same)]  # the tool ran only once
    assert "Do not call it again" in tool_messages(llm.requests[2])[-1]["content"]
    assert llm.tools_offered[2] == []  # no tools offered: the model has to answer
    assert result.answer == "t18293/22 is top." and result.rounds == 3


def test_same_tool_with_different_arguments_still_runs(tools):
    llm = FakeLLM(
        [
            AssistantTurn(tool_calls=[call("c1", trait="yield")]),
            AssistantTurn(tool_calls=[call("c2", trait="yield", env_type="med")]),
            AssistantTurn(text="done"),
        ]
    )
    answer("yield overall and in med", llm)
    assert len(tools) == 2


def test_tool_calls_when_no_tools_were_offered_are_ignored(tools):
    llm = FakeLLM(
        [
            AssistantTurn(tool_calls=[call("c1", trait="yield")]),
            AssistantTurn(tool_calls=[call("c2", trait="yield")]),
            AssistantTurn(tool_calls=[call("c3", trait="yield")]),  # ignores the note
        ]
    )
    result = answer("q", llm)
    assert len(tools) == 1
    assert result.answer == GAVE_UP_MESSAGE and result.stopped_reason == "final_answer"


# ---------------------------------------------------------------------------------------
# End to end with the real registry and the real run_sql (no LLM, no R)
# ---------------------------------------------------------------------------------------
def test_end_to_end_with_real_run_sql(make_db, monkeypatch, tmp_path):
    path = make_db(
        [("o_a_score", "float", "High", True)],
        [("cara", "oak park 2015", "o_a_score", 2015, "ne", "oak park", 7.0)],
    )
    monkeypatch.setattr(
        "potato_trial_pipeline.agent.tools.run_sql.settings.duckdb_path", lambda: path
    )
    monkeypatch.setattr(f"{MODULE}.AGENT_LOG", tmp_path / "agent_runs.jsonl")
    query = "SELECT COUNT(DISTINCT experiment_name) AS n FROM main.int_trait_experiment_level"
    llm = FakeLLM(
        [
            AssistantTurn(tool_calls=[call("c1", name="run_sql", sql=query)]),
            AssistantTurn(text="There is one trial."),
        ]
    )

    result = answer("how many trials?", llm)

    assert json.loads(result.tool_calls[0].result)["rows"] == [[1]]
    system_prompt = llm.requests[0][0]["content"]
    assert "Locations: oak park" in system_prompt  # the schema card reached the LLM
    assert result.answer == "There is one trial."
