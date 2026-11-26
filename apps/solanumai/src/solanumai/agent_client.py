"""
The seam between the web app and the agent. Thursday: replace the body of ask_agent with the
real agent call. Nothing else in the app changes.

Contract: `table` and `trace` must contain plain JSON types (str, int, float, bool, None, list, dict)
because they're stored in Postgres (jsonb) and sent to the browser.
"""

from dataclasses import dataclass, field


@dataclass
class AgentResult:
    answer: str
    table: list[dict] | None = None
    trace: list[dict] = field(default_factory=list)


def ask_agent(history: list[dict], message: str) -> AgentResult:
    """history: earlier messages of this conversation, oldest first: [{"role": ..., "content": ...}]"""
    return AgentResult(answer=f"(agent not connected yet) You asked: {message}")
