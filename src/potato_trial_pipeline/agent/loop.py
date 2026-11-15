"""
@File        - loop.py
@Description - The agent loop: question -> LLM -> tool calls -> LLM -> ... -> answer.

Each round:
  1. Send the conversation and the tool specs to the LLM.
  2. No tool calls -> that text is the final answer.
  3. Otherwise run every tool call through the registry and send each result back
     with the same id, then go to 1.
Stops after MAX_ROUNDS. Every question is logged to logs/agent_runs.jsonl, so every
answer can be traced back to the exact tool output it came from.
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from potato_trial_pipeline.agent import settings
from potato_trial_pipeline.agent.llm import LLM
from potato_trial_pipeline.agent.tools.registry import run_tool, tool_specs
from potato_trial_pipeline.agent.tools.run_sql import schema_card

MAX_ROUNDS = 6
SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "system.md"
SQL_EXAMPLES_PATH = Path(__file__).resolve().parent / "prompts" / "sql_examples.md"
AGENT_LOG = settings.PROJECT_ROOT / "logs" / "agent_runs.jsonl"

REPEAT_NOTE = (
    "You already called this tool with these arguments for this question; the result is "
    "above. Do not call it again. Answer the user now from that result."
)
GAVE_UP_MESSAGE = (
    "I could not complete this within the allowed number of steps. "
    "Please ask a narrower question (one trait, one region or a year range)."
)


class ToolCallRecord(BaseModel):
    name: str
    arguments: str
    result: str
    seconds: float


class AgentResult(BaseModel):
    answer: str
    tool_calls: list[ToolCallRecord]
    rounds: int
    stopped_reason: Literal["final_answer", "max_rounds"]
    messages: list[dict]  # the conversation without the system prompt, for follow-ups


def load_system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def load_sql_examples() -> str:
    return SQL_EXAMPLES_PATH.read_text(encoding="utf-8")


def build_system_prompt() -> str:
    """The fixed rules, a description of the database (generated fresh each time) and
    verified example questions with their SQL."""
    return "\n\n".join([load_system_prompt(), schema_card(), load_sql_examples()])


def _run_call(name: str, arguments: str) -> str:
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError:
        return json.dumps(
            {"error": "arguments are not valid JSON", "received": arguments}
        )

    if not isinstance(parsed, dict):
        return json.dumps(
            {"error": "arguments must be a JSON object", "received": arguments}
        )

    return run_tool(name, parsed)


def _call_key(name: str, arguments: str) -> str:
    """Same tool + same arguments = same key. Arguments that are null count as not given,
    so {"trait": "yield"} and {"trait": "yield", "env_type": null} are the same call."""
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError:
        return f"{name}:{arguments}"

    if isinstance(parsed, dict):
        parsed = {k: v for k, v in parsed.items() if v is not None}

    return f"{name}:{json.dumps(parsed, sort_keys=True)}"


def _log(question: str, model_name: str, result: AgentResult) -> None:
    AGENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": model_name,
        "question": question,
        "answer": result.answer,
        "rounds": result.rounds,
        "stopped_reason": result.stopped_reason,
        "tool_calls": [call.model_dump() for call in result.tool_calls],
    }

    with AGENT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def answer(question: str, llm: LLM, history: list[dict] | None = None) -> AgentResult:
    conversation = list(history or []) + [{"role": "user", "content": question}]
    system = {"role": "system", "content": build_system_prompt()}
    specs = tool_specs()
    records: list[ToolCallRecord] = []
    done: set[str] = set()  # tool calls already run for this question
    # Switched off when the model repeats a call: then it must answer in text
    offer_tools = True

    for round_number in range(1, MAX_ROUNDS + 1):
        turn = llm.chat([system] + conversation, specs if offer_tools else [])

        if not turn.tool_calls or not offer_tools:
            text = turn.text or (GAVE_UP_MESSAGE if turn.tool_calls else "")
            conversation.append({"role": "assistant", "content": text})
            result = AgentResult(
                answer=text,
                tool_calls=records,
                rounds=round_number,
                stopped_reason="final_answer",
                messages=conversation,
            )
            _log(question, llm.model_name, result)
            return result

        conversation.append(
            {
                "role": "assistant",
                "content": turn.text,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": call.arguments},
                    }
                    for call in turn.tool_calls
                ],
            }
        )

        for call in turn.tool_calls:
            started = time.perf_counter()
            key = _call_key(call.name, call.arguments)

            if key in done:
                # Small models sometimes call the same tool again and again. Do not run it
                # again (a ranking takes many seconds); make the model answer instead.
                output = json.dumps({"note": REPEAT_NOTE})
                offer_tools = False
            else:
                output = _run_call(call.name, call.arguments)
                done.add(key)

            records.append(
                ToolCallRecord(
                    name=call.name,
                    arguments=call.arguments,
                    result=output,
                    seconds=round(time.perf_counter() - started, 2),
                )
            )

            conversation.append(
                {"role": "tool", "tool_call_id": call.id, "content": output}
            )

    conversation.append({"role": "assistant", "content": GAVE_UP_MESSAGE})
    result = AgentResult(
        answer=GAVE_UP_MESSAGE,
        tool_calls=records,
        rounds=MAX_ROUNDS,
        stopped_reason="max_rounds",
        messages=conversation,
    )
    _log(question, llm.model_name, result)
    return result
