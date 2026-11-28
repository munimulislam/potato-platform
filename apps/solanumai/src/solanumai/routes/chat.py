import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from potato_data_agent import AgentResult, DatabaseUnavailable, LLMUnavailable
from solanumai.agent_runner import AgentRunner, get_agent_runner
from solanumai.auth import require_login
from solanumai.contracts import (
    ChatMessageOut,
    ChatRequest,
    ChatResponse,
    ConversationDetail,
    ConversationOut,
)
from solanumai.store import ChatStore, get_chat_store

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])

MAX_HISTORY_MESSAGES = 40
TRACE_RESULT_CHARS = 500


def _to_out(row: dict) -> ChatMessageOut:
    payload = row.get("payload") or {}
    return ChatMessageOut(
        id=row["id"],
        role=row["role"],
        content=row["content"],
        displays=payload.get("displays") or [],
        table=payload.get("table"),
        trace=payload.get("trace") or [],
        created_at=row["created_at"],
    )


def _trace(result: AgentResult) -> list[dict]:
    return [
        {
            "tool": c.name,
            "arguments": c.arguments,
            "seconds": c.seconds,
            "result": c.result[:TRACE_RESULT_CHARS],
        }
        for c in result.tool_calls
    ] + [{"rounds": result.rounds, "stopped": result.stopped_reason}]


def _title(message: str) -> str:
    first_line = message.strip().splitlines()[0]
    return first_line[:80] + ("…" if len(first_line) > 80 else "")


@router.post("", response_model=ChatResponse)
def chat(
    req: ChatRequest,
    user: dict = Depends(require_login),
    chats: ChatStore = Depends(get_chat_store),
    agent: AgentRunner = Depends(get_agent_runner),
):
    if req.conversation_id is None:
        conversation_id = chats.create_conversation(
            user["id"], user.get("name"), _title(req.message)
        )
        history: list[dict] = []
    else:
        if chats.get_conversation(req.conversation_id, user["id"]) is None:
            raise HTTPException(404, "Conversation not found")
        conversation_id = req.conversation_id
        history = [
            {"role": m["role"], "content": m["content"]}
            for m in chats.get_messages(conversation_id)
        ]
        history = history[-MAX_HISTORY_MESSAGES:]

    chats.add_message(conversation_id, "user", req.message)

    payload: dict = {"displays": [], "trace": []}

    try:
        result = agent.ask(history, req.message)
        answer_text = result.answer
        payload = {"displays": result.displays, "trace": _trace(result)}
    except (LLMUnavailable, DatabaseUnavailable) as e:
        log.warning("Agent unavailable (conversation %s): %s", conversation_id, e)
        answer_text = (
            f"Sorry, I can't answer right now: {e} Please try again in a moment."
        )
    except Exception:
        # The question is saved; the user gets an honest message instead of an error page.
        log.exception("Agent failed (conversation %s)", conversation_id)
        answer_text = (
            "Sorry, I couldn't answer that. Please try again, or rephrase the question."
        )

    saved = chats.add_message(
        conversation_id, "assistant", answer_text, payload=payload
    )

    return ChatResponse(conversation_id=conversation_id, message=_to_out(saved))


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(
    user: dict = Depends(require_login), chats: ChatStore = Depends(get_chat_store)
):
    return [ConversationOut(**row) for row in chats.list_conversations(user["id"])]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: UUID,
    user: dict = Depends(require_login),
    chats: ChatStore = Depends(get_chat_store),
):
    conversation = chats.get_conversation(conversation_id, user["id"])

    if conversation is None:
        raise HTTPException(404, "Conversation not found")

    messages = [_to_out(m) for m in chats.get_messages(conversation_id)]

    return ConversationDetail(**conversation, messages=messages)


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: UUID,
    user: dict = Depends(require_login),
    chats: ChatStore = Depends(get_chat_store),
):
    if not chats.delete_conversation(conversation_id, user["id"]):
        raise HTTPException(404, "Conversation not found")
    return Response(status_code=204)
