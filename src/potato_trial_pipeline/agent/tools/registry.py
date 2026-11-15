"""
@File        - registry.py
@Description - The only place that knows which tools exist. The agent loop talks to the
               registry, never to the tools directly.

run_tool() always returns a JSON string the LLM can read:
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
from potato_trial_pipeline.agent.tools.describe_data import (
    DescribeDataQuery,
    describe_data,
)
from potato_trial_pipeline.agent.tools.rank_varieties import (
    RankVarietiesQuery,
    rank_varieties,
)
from potato_trial_pipeline.agent.tools.run_sql import RunSqlQuery, run_sql

FLOAT_DECIMALS = 3  # 7.27626906117655 -> 7.276


class Tool(BaseModel):
    name: str
    description: str
    input_model: type[BaseModel]
    function: Callable[[BaseModel], BaseModel]


TOOLS: list[Tool] = [
    # Tool(
    #     name="describe_data",
    #     description=(
    #         "Lists what data is available: the rankable traits (name, label, description, "
    #         "synonyms, scale, direction, and coverage: number of trials and varieties, years, "
    #         "regions), the trial locations with their region and years, the regions, and the "
    #         "overall year range. Call this first whenever you are unsure which trait, location, "
    #         "region or years the user means. Takes no arguments."
    #     ),
    #     input_model=DescribeDataQuery,
    #     function=describe_data,
    # ),
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
            "filters: region (env_type), locations, year range, min_trials, top_n. Returns per "
            "variety: predicted value, standard error, reliability, number of trials, first and "
            "last year, and whether it is clearly different from the top variety; plus model "
            "quality and warnings. It does not combine traits, does not model site-specific "
            "performance and cannot rank text traits. Use trait and location names exactly as "
            "they appear in the database."
        ),
        input_model=RankVarietiesQuery,
        function=rank_varieties,
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


def run_tool(name: str, arguments: dict) -> str:
    tools = {tool.name: tool for tool in TOOLS}

    if name not in tools:
        return json.dumps(
            {"error": f"unknown tool '{name}'", "valid_tools": sorted(tools)}
        )

    tool = tools[name]

    try:
        query = tool.input_model.model_validate(arguments)
    except ValidationError as e:
        details = e.errors(include_url=False, include_context=False)
        return json.dumps(
            {
                "error": "invalid arguments",
                "details": details,
                "allowed_arguments": list(tool.input_model.model_fields),
            }
        )

    try:
        result = tool.function(query)
    except ToolError as e:
        return json.dumps({"error": str(e)})

    compact = _round_floats(json.loads(result.model_dump_json()))
    return json.dumps(compact, separators=(",", ":"))
