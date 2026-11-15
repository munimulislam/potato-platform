"""
@File        - cli.py
@Description - Chat with the agent in the terminal.

Usage:
  python -m potato_trial_pipeline.agent.cli

Commands:
  /trace   show the tool calls of the last answer
  /reset   forget the conversation
  /exit    quit
"""

from potato_trial_pipeline.agent.llm import OpenAILLM
from potato_trial_pipeline.agent.loop import AgentResult, answer
from openai import APIError


def _print_trace(result: AgentResult | None) -> None:
    if result is None or not result.tool_calls:
        print("(no tool calls)")
        return
    for i, call in enumerate(result.tool_calls, start=1):
        print(f"[{i}] {call.name}({call.arguments})  {call.seconds} s")
        print(f"    -> {call.result[:300]}{'...' if len(call.result) > 300 else ''}")
    print(f"rounds: {result.rounds}, stopped: {result.stopped_reason}")


def main() -> None:
    llm = OpenAILLM()
    history: list[dict] = []
    last: AgentResult | None = None
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
            last = answer(question, llm, history)
        except APIError as e:
            # The LLM did not answer (timeout, server down, rate limit). Keep the
            # conversation so far, so the user can simply ask again.
            print(
                f"\n(The language model did not respond: {type(e).__name__}. Try again.)"
            )
            continue
        history = last.messages
        print(f"\nAgent: {last.answer}")


if __name__ == "__main__":
    main()
