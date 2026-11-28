import re
from typing import Protocol

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from pydantic import BaseModel

from potato_data_agent.config import AgentConfig
from potato_data_agent.errors import LLMUnavailable

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_thinking(text: str) -> str:
    return _THINK.sub("", text).strip()


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: str


class AssistantTurn(BaseModel):
    text: str | None = None
    tool_calls: list[ToolCall] = []


class LLM(Protocol):
    model_name: str

    def chat(self, messages: list[dict], tools: list[dict]) -> AssistantTurn: ...


class OpenAILLM:
    def __init__(self, config: AgentConfig) -> None:
        self.model_name = config.model
        self._temperature = config.temperature
        self.client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout_seconds,
            max_retries=config.max_retries,
        )

    def chat(self, messages: list[dict], tools: list[dict]) -> AssistantTurn:
        options = (
            {} if self._temperature is None else {"temperature": self._temperature}
        )
        if tools:
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

        try:
            response = self.client.chat.completions.create(
                model=self.model_name, messages=messages, **options
            )
        except (APIConnectionError, APITimeoutError) as e:
            raise LLMUnavailable(f"LLM is not reachable ({type(e).__name__}).") from e
        except APIStatusError as e:
            raise LLMUnavailable(f"LLM returned an error ({e.status_code}).") from e

        message = response.choices[0].message

        return AssistantTurn(
            text=strip_thinking(message.content) if message.content else None,
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
    def __init__(self, script: list[AssistantTurn]) -> None:
        self.model_name = "fake"
        self.script = list(script)
        self.requests: list[list[dict]] = []

    def chat(self, messages: list[dict], tools: list[dict]) -> AssistantTurn:
        self.requests.append([dict(m) for m in messages])
        if not self.script:
            raise AssertionError("FakeLLM was called more times than scripted")
        return self.script.pop(0)
