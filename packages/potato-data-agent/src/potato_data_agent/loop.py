"""
@File        - loop.py
@Description - The agent loop: question -> LLM -> tool calls -> LLM -> ... -> answer.
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from potato_data_agent.context import ToolContext
from potato_data_agent.llm import LLM
from potato_data_agent.schema_card import schema_card
from potato_data_agent.tools.registry import ToolOutput, call_tool, tool_specs

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
SYSTEM_PROMPT_PATH = PROMPTS_DIR / "system.md"
SQL_EXAMPLES_PATH = PROMPTS_DIR / "sql_examples.md"
REPEAT_NOTE = (
    "You already called this tool with these arguments for this question; the result is "
    "above. Do not call it again. Answer the user now from that result."
)
GAVE_UP_MESSAGE = (
    "I could not complete this within the allowed number of steps. "
    "Please ask a narrower question (one trait, one region or a year range)."
)
WARM_UP_QUESTION = "Reply with OK."


class ToolCallRecord(BaseModel):
    name: str
    arguments: str
    result: str
    seconds: float
    display: str | None = None


class AgentResult(BaseModel):
    answer: str
    tool_calls: list[ToolCallRecord]
    displays: list[str] = []
    rounds: int
    stopped_reason: Literal["final_answer", "max_rounds"]
    messages: list[dict]


def load_system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def load_sql_examples() -> str:
    return SQL_EXAMPLES_PATH.read_text(encoding="utf-8")


def build_system_prompt(ctx: ToolContext) -> str:
    return "\n\n".join([load_system_prompt(), schema_card(ctx), load_sql_examples()])


def _run_call(name: str, arguments: str, ctx: ToolContext) -> ToolOutput:
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError:
        return ToolOutput(
            for_llm=json.dumps(
                {"error": "arguments are not valid JSON", "received": arguments}
            )
        )
    if not isinstance(parsed, dict):
        return ToolOutput(
            for_llm=json.dumps(
                {"error": "arguments must be a JSON object", "received": arguments}
            )
        )
    return call_tool(name, parsed, ctx)


def _call_key(name: str, arguments: str) -> str:
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError:
        return f"{name}:{arguments}"
    if isinstance(parsed, dict):
        parsed = {k: v for k, v in parsed.items() if v is not None}
    return f"{name}:{json.dumps(parsed, sort_keys=True)}"


def _log(
    path: Path | None, question: str, model_name: str, result: AgentResult
) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": model_name,
        "question": question,
        "answer": result.answer,
        "rounds": result.rounds,
        "stopped_reason": result.stopped_reason,
        "tool_calls": [call.model_dump() for call in result.tool_calls],
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def answer(
    question: str, llm: LLM, ctx: ToolContext, history: list[dict] | None = None
) -> AgentResult:
    config = ctx.config
    content = question + (" /no_think" if config.no_think else "")
    conversation = list(history or []) + [{"role": "user", "content": content}]
    system = {"role": "system", "content": build_system_prompt(ctx)}
    specs = tool_specs()
    records: list[ToolCallRecord] = []
    done: set[str] = set()
    offer_tools = True

    for round_number in range(1, config.max_rounds + 1):
        turn = llm.chat([system] + conversation, specs if offer_tools else [])

        if not turn.tool_calls or not offer_tools:
            text = turn.text or (GAVE_UP_MESSAGE if turn.tool_calls else "")
            conversation.append({"role": "assistant", "content": text})
            result = AgentResult(
                answer=text,
                tool_calls=records,
                displays=[r.display for r in records if r.display],
                rounds=round_number,
                stopped_reason="final_answer",
                messages=conversation,
            )
            _log(config.run_log_path, question, llm.model_name, result)
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
                # break from repeated tool call
                output = ToolOutput(for_llm=json.dumps({"note": REPEAT_NOTE}))
                offer_tools = False
            else:
                output = _run_call(call.name, call.arguments, ctx)
                done.add(key)

            records.append(
                ToolCallRecord(
                    name=call.name,
                    arguments=call.arguments,
                    result=output.for_llm,
                    seconds=round(time.perf_counter() - started, 2),
                    display=output.display,
                )
            )

            conversation.append(
                {"role": "tool", "tool_call_id": call.id, "content": output.for_llm}
            )

    conversation.append({"role": "assistant", "content": GAVE_UP_MESSAGE})
    result = AgentResult(
        answer=GAVE_UP_MESSAGE,
        tool_calls=records,
        displays=[r.display for r in records if r.display],
        rounds=config.max_rounds,
        stopped_reason="max_rounds",
        messages=conversation,
    )
    _log(config.run_log_path, question, llm.model_name, result)
    return result


def warm_up(llm: LLM, ctx: ToolContext) -> float:
    """
    Send the real system prompt and tool list once, so the LLM server caches them.

    Aafter this call the server skips re-reading those system prompts and only processes the
    new question. It must build the messages the same way answer() does, or the cache
    won't match.

    Return: the seconds it took to answer the warm up question
    """
    content = WARM_UP_QUESTION + (" /no_think" if ctx.config.no_think else "")
    started = time.perf_counter()
    llm.chat(
        [
            {"role": "system", "content": build_system_prompt(ctx)},
            {"role": "user", "content": content},
        ],
        tool_specs(),
    )
    return round(time.perf_counter() - started, 1)
