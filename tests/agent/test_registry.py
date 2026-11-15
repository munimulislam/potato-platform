"""
Tests for registry.py: whatever happens inside a tool, the LLM must get readable JSON back,
and real bugs must not be hidden as tool errors.
"""

import json

import pytest
from pydantic import BaseModel, ConfigDict

from potato_trial_pipeline.agent.common import ToolError
from potato_trial_pipeline.agent.tools.registry import (
    TOOLS,
    Tool,
    run_tool,
    tool_specs,
)

MODULE = "potato_trial_pipeline.agent.tools.registry"


def strict_json(text: str):
    def reject(token):
        raise ValueError(f"invalid JSON constant: {token}")

    return json.loads(text, parse_constant=reject)


# ---------------------------------------------------------------------------------------
# A fake tool, so these tests need no database and no R
# ---------------------------------------------------------------------------------------
class EchoQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    word: str


class EchoResult(BaseModel):
    echoed: str


def echo(query: EchoQuery) -> EchoResult:
    if query.word == "fail":
        raise ToolError("the tool refused this")
    if query.word == "bug":
        raise RuntimeError("a real bug")
    return EchoResult(echoed=query.word)


@pytest.fixture
def fake_tools(monkeypatch):
    tools = [
        Tool(
            name="echo",
            description="Echo a word.",
            input_model=EchoQuery,
            function=echo,
        )
    ]
    monkeypatch.setattr(f"{MODULE}.TOOLS", tools)
    return tools


# ---------------------------------------------------------------------------------------
# Tool specs (what the LLM sees)
# ---------------------------------------------------------------------------------------
def test_tool_names_are_unique_and_match_specs():
    names = [tool.name for tool in TOOLS]
    assert len(names) == len(set(names))
    assert [spec["name"] for spec in tool_specs()] == names


def test_every_schema_is_a_json_object_without_refs():
    for spec in tool_specs():
        schema = spec["input_schema"]
        assert schema["type"] == "object"
        text = json.dumps(schema)
        assert "$ref" not in text and "$defs" not in text, spec["name"]


def test_env_type_enum_is_inlined_for_the_llm():
    spec = next(s for s in tool_specs() if s["name"] == "rank_varieties")
    env_type = json.dumps(spec["input_schema"]["properties"]["env_type"])
    assert '"ne"' in env_type and '"med"' in env_type


# ---------------------------------------------------------------------------------------
# run_tool: every outcome is JSON the LLM can read
# ---------------------------------------------------------------------------------------
def test_unknown_tool_lists_valid_tools(fake_tools):
    out = strict_json(run_tool("rank_potatoes", {}))
    assert "unknown tool" in out["error"]
    assert out["valid_tools"] == ["echo"]


def test_wrong_type_is_invalid_arguments(fake_tools):
    out = strict_json(run_tool("echo", {"word": 5}))
    assert out["error"] == "invalid arguments"
    assert out["details"][0]["loc"] == ["word"]


def test_unknown_argument_is_invalid_arguments(fake_tools):
    # extra="forbid" must reach the LLM, so a misspelt argument is never silently ignored
    out = strict_json(run_tool("echo", {"word": "hi", "wrd": "hi"}))
    assert out["error"] == "invalid arguments"
    assert any(d["loc"] == ["wrd"] for d in out["details"])


def test_tool_error_becomes_error_json(fake_tools):
    out = strict_json(run_tool("echo", {"word": "fail"}))
    assert out == {"error": "the tool refused this"}


def test_success_returns_the_result_model(fake_tools):
    out = run_tool("echo", {"word": "hi"})
    assert EchoResult.model_validate_json(out).echoed == "hi"


def test_real_bugs_are_not_hidden(fake_tools):
    with pytest.raises(RuntimeError, match="a real bug"):
        run_tool("echo", {"word": "bug"})


def test_real_tool_bad_arguments_are_reported():
    # The real rank_varieties model: top_n=0 is out of range, no database is touched.
    out = strict_json(run_tool("rank_varieties", {"trait": "o_a_score", "top_n": 0}))
    assert out["error"] == "invalid arguments"
    assert out["details"][0]["loc"] == ["top_n"]


def test_invalid_arguments_tell_the_llm_what_is_allowed():
    out = strict_json(run_tool("rank_varieties", {"trait": "x", "year_from": 2015}))
    assert "year_min" in out["allowed_arguments"]


def test_floats_are_rounded_and_json_is_compact(monkeypatch):
    class Numbers(BaseModel):
        value: float
        values: list[float]
        count: int

    tools = [
        Tool(
            name="numbers",
            description="Numbers.",
            input_model=EchoQuery,
            function=lambda query: Numbers(
                value=7.27626906117655, values=[0.0889351495177164], count=42
            ),
        )
    ]
    monkeypatch.setattr(f"{MODULE}.TOOLS", tools)
    out = run_tool("numbers", {"word": "x"})
    assert out == '{"value":7.276,"values":[0.089],"count":42}'
