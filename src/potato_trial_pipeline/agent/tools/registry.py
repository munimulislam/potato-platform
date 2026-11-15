"""
@File        - registry.py
@Description - The only place that knows which tools exist. The agent loop talks to the
               registry, never to the tools directly.

call_tool() returns a ToolOutput: the JSON string the LLM reads (always), and optionally a
text to show the user exactly as computed (e.g. a ranking table). The JSON is:
  - unknown tool name       -> {"error": "unknown tool ...", "valid_tools": [...]}
  - arguments fail Pydantic -> {"error": "invalid arguments", "details": [...]}
  - the tool raises ToolError -> {"error": "<message>"}
  - success                 -> the tool's result model as JSON
Any other exception is a bug and is NOT caught, so it is loud.
"""

import json
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from potato_trial_pipeline.agent.common import ToolError
from potato_trial_pipeline.agent.tools.rank_varieties import (
    RankVarietiesQuery,
    for_llm,
    rank_varieties,
    render_table,
)
from potato_trial_pipeline.agent.tools.run_sql import RunSqlQuery, run_sql

FLOAT_DECIMALS = 3  # 7.27626906117655 -> 7.276


class Tool(BaseModel):
    name: str
    description: str
    input_model: type[BaseModel]
    function: Callable[[BaseModel], BaseModel]

    # Optional: turns the full result into the short version the LLM reads
    to_llm: Callable[[BaseModel], Any] | None = None

    # Optional: text shown to the user as-is, next to the LLM's answer
    to_display: Callable[[BaseModel], str] | None = None


class ToolOutput(BaseModel):
    for_llm: str  # JSON the LLM reads
    display: str | None = None  # shown to the user exactly as computed


TOOLS: list[Tool] = [
    Tool(
        name="run_sql",
        description=(
            "Runs ONE read-only DuckDB SELECT query on the trial database and returns the rows "
            "(at most 50). The tables and columns are described in the system prompt. Use it "
            "for counts, lists, coverage, years, locations and raw values. Never use it to "
            "decide which variety is best or to compare varieties: use rank_varieties for that."
        ),
        input_model=RunSqlQuery,
        function=run_sql,
    ),
    Tool(
        name="rank_varieties",
        description=(
            "Ranks varieties for ONE trait with a REML/BLUP mixed model that corrects for how "
            "easy each trial was and is cautious about varieties with few trials. Optional "
            "filters: region (env_type), locations, year range, min_trials, top_n. Returns the "
            "top varieties with: value (the model's predicted value), se (its standard error), "
            "trials, years, and level_with_top (true = statistically level with rank 1); plus "
            "warnings. It does not combine traits, does not model site-specific "
            "performance and cannot rank text traits. Use trait and location names exactly as "
            "they appear in the database."
        ),
        input_model=RankVarietiesQuery,
        function=rank_varieties,
        to_llm=for_llm,
        to_display=render_table,
    ),
]


def _inline_refs(schema: dict) -> dict:
    """Replace {"$ref": "#/$defs/X"} with the definition itself and drop $defs.
    Pydantic puts enums (e.g. EnvType) under $defs; some LLM providers do not accept $ref.
    """
    defs = schema.get("$defs", {})

    def resolve(node):
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].split("/")[-1]
                return resolve(defs[name])
            return {k: resolve(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


def tool_specs() -> list[dict]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": _inline_refs(tool.input_model.model_json_schema()),
        }
        for tool in TOOLS
    ]


def _round_floats(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, FLOAT_DECIMALS)
    if isinstance(value, dict):
        return {k: _round_floats(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_round_floats(v) for v in value]
    return value


def call_tool(name: str, arguments: dict) -> ToolOutput:
    tools = {tool.name: tool for tool in TOOLS}

    if name not in tools:
        return ToolOutput(
            for_llm=json.dumps(
                {"error": f"unknown tool '{name}'", "valid_tools": sorted(tools)}
            )
        )

    tool = tools[name]

    try:
        query = tool.input_model.model_validate(arguments)
    except ValidationError as e:
        details = e.errors(include_url=False, include_context=False)
        return ToolOutput(
            for_llm=json.dumps(
                {
                    "error": "invalid arguments",
                    "details": details,
                    "allowed_arguments": list(tool.input_model.model_fields),
                }
            )
        )

    try:
        result = tool.function(query)
    except ToolError as e:
        return ToolOutput(for_llm=json.dumps({"error": str(e)}))

    data = tool.to_llm(result) if tool.to_llm else json.loads(result.model_dump_json())
    compact = _round_floats(data)
    return ToolOutput(
        for_llm=json.dumps(compact, separators=(",", ":")),
        display=tool.to_display(result) if tool.to_display else None,
    )


def run_tool(name: str, arguments: dict) -> str:
    """Only the JSON the LLM reads."""
    return call_tool(name, arguments).for_llm
