"""
Usage:
  DB_HOST=localhost DB_PORT=5433 DB_NAME=potato_dev \
  AGENT_USER=agent_ro AGENT_PASSWORD_FILE=secrets/dev/agent-password \
  LLM_MODEL=qwen3:4b LLM_BASE_URL=http://localhost:11434/v1 LLM_API_KEY=ollama \
  uv run --package potato-data-agent potato-data-agent

Commands:
  /trace   show the tool calls of the last answer
  /reset   forget the conversation
  /exit    quit
"""

import os
from pathlib import Path

from psycopg.conninfo import make_conninfo
from psycopg_pool import ConnectionPool

from potato_data_agent.config import AgentConfig
from potato_data_agent.context import ToolContext
from potato_data_agent.errors import AgentError
from potato_data_agent.llm import OpenAILLM
from potato_data_agent.loop import AgentResult, answer


def _password() -> str:
    if os.environ.get("AGENT_PASSWORD"):
        return os.environ["AGENT_PASSWORD"]
    return Path(os.environ["AGENT_PASSWORD_FILE"]).read_text(encoding="utf-8").strip()


def _config_from_env() -> AgentConfig:
    temperature = os.getenv("LLM_TEMPERATURE", "0")
    return AgentConfig(
        model=os.environ["LLM_MODEL"],
        api_key=os.environ["LLM_API_KEY"],
        base_url=os.getenv("LLM_BASE_URL") or None,
        temperature=float(temperature) if temperature else None,
        timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "600")),
        max_retries=int(os.getenv("LLM_MAX_RETRIES", "0")),
        no_think=os.getenv("LLM_NO_THINK", "false").lower() == "true",
        run_log_path=Path(os.getenv("AGENT_RUN_LOG", "logs/agent_runs.jsonl")),
        rscript_path=Path(os.getenv("RSCRIPT_PATH", "Rscript")),
    )


def _pool() -> ConnectionPool:
    conninfo = make_conninfo(
        host=os.environ["DB_HOST"],
        port=os.environ["DB_PORT"],
        dbname=os.environ["DB_NAME"],
        user=os.environ["AGENT_USER"],
        password=_password(),
        application_name="potato-agent-cli",
        options="-c default_transaction_read_only=on -c statement_timeout=30000",
    )
    return ConnectionPool(conninfo, min_size=1, max_size=2)


def _print_trace(result: AgentResult | None) -> None:
    if result is None or not result.tool_calls:
        print("(no tool calls)")
        return
    for i, call in enumerate(result.tool_calls, start=1):
        print(f"[{i}] {call.name}({call.arguments})  {call.seconds} s")
        print(f"    -> {call.result[:300]}{'...' if len(call.result) > 300 else ''}")
    print(f"rounds: {result.rounds}, stopped: {result.stopped_reason}")


def main() -> None:
    config = _config_from_env()
    llm = OpenAILLM(config)
    history: list[dict] = []
    last: AgentResult | None = None

    with _pool() as pool:
        ctx = ToolContext.create(pool, config)
        print(f"Potato trials agent ({llm.model_name}). Type /exit to quit.")

        while True:
            try:
                question = input("\nYou: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not question:
                continue
            if question == "/exit":
                break
            if question == "/trace":
                _print_trace(last)
                continue
            if question == "/reset":
                history, last = [], None
                print("(conversation cleared)")
                continue

            try:
                last = answer(question, llm, ctx, history)
            except AgentError as e:
                # The LLM or the database did not answer. Keep the conversation so far,
                # so the user can simply ask again.
                print(f"\n({e} Try again.)")
                continue

            history = last.messages
            for table in last.displays:
                print(f"\n{table}")
            print(f"\nAgent: {last.answer}")


if __name__ == "__main__":
    main()
