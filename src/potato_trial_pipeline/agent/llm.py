"""
@File        - llm.py
@Description - The only file that talks to an LLM provider.

Messages use the OpenAI chat format (role: system / user / assistant / tool).
OpenAILLM works with any OpenAI-compatible endpoint: OpenAI, Ollama (local),
Groq, vLLM, LM Studio, Gemini's OpenAI-compatible endpoint, ...
Configure in .env: LLM_MODEL, LLM_API_KEY, LLM_BASE_URL (empty for OpenAI itself),
LLM_TEMPERATURE (default 0; empty = not sent).

FakeLLM replays scripted turns, so the agent loop can be tested without any LLM.
"""

from typing import Protocol

from openai import OpenAI
from pydantic import BaseModel

from potato_trial_pipeline.agent import settings


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: str  # raw JSON text from the LLM; the loop parses and validates it


class AssistantTurn(BaseModel):
    text: str | None = None
    tool_calls: list[ToolCall] = []


class LLM(Protocol):
    model_name: str

    def chat(self, messages: list[dict], tools: list[dict]) -> AssistantTurn: ...


class OpenAILLM:
    def __init__(self) -> None:
        self.model_name = settings.llm_model()
        self.client = OpenAI(
            api_key=settings.llm_api_key(),
            base_url=settings.llm_base_url(),
            timeout=settings.llm_timeout_seconds(),
            max_retries=settings.llm_max_retries(),
        )

    def chat(self, messages: list[dict], tools: list[dict]) -> AssistantTurn:
        temperature = settings.llm_temperature()
        options = {} if temperature is None else {"temperature": temperature}
        if tools:
            # No tools at all (not an empty list) when the loop wants a final answer
            options["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["input_schema"],
                    },
                }
                for tool in tools
            ]
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            **options,
        )
        message = response.choices[0].message

        return AssistantTurn(
            text=message.content,
            tool_calls=[
                ToolCall(
                    id=call.id,
                    name=call.function.name,
                    arguments=call.function.arguments or "{}",
                )
                for call in (message.tool_calls or [])
            ],
        )


class FakeLLM:
    """Returns the scripted turns in order and records every request it received."""

    def __init__(self, script: list[AssistantTurn]) -> None:
        self.model_name = "fake"
        self.script = list(script)
        self.requests: list[list[dict]] = []

    def chat(self, messages: list[dict], tools: list[dict]) -> AssistantTurn:
        self.requests.append([dict(m) for m in messages])
        if not self.script:
            raise AssertionError("FakeLLM was called more times than scripted")
        return self.script.pop(0)
