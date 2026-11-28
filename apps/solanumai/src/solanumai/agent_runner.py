import logging
import threading

from fastapi import Request
from potato_data_agent import LLM, AgentResult, ToolContext, answer, warm_up

log = logging.getLogger(__name__)


class AgentRunner:
    def __init__(
        self,
        llm: LLM,
        ctx: ToolContext,
        max_concurrent: int,
        warm_up_retry_seconds: int,
    ):
        self._llm = llm
        self._ctx = ctx
        self._slots = threading.BoundedSemaphore(max_concurrent)
        self._retry_seconds = warm_up_retry_seconds
        self._stop = threading.Event()

    def ask(self, history: list[dict], message: str) -> AgentResult:
        with self._slots:
            return answer(message, self._llm, self._ctx, history)

    def start(self) -> None:
        threading.Thread(target=self._run, name="agent-warm-up", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        # Loads the system prompt into the LLM's cache
        while not self._stop.is_set():
            if self._warm_up():
                return
            self._stop.wait(self._retry_seconds)

    def _warm_up(self) -> bool:
        try:
            # Takes a slot like a real question: the LLM server handles one request at a time.
            with self._slots:
                seconds = warm_up(self._llm, self._ctx)
        except Exception as e:
            log.warning(
                "Agent warm-up failed, retrying in %ss: %s", self._retry_seconds, e
            )
            return False

        log.info("Agent warm-up done in %.1f s", seconds)
        return True


def get_agent_runner(request: Request) -> AgentRunner:
    return request.app.state.agent_runner
