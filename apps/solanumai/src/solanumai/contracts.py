"""
Request and response models of the JSON API.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class TableInfo(BaseModel):
    schema_name: str
    table_name: str
    approx_rows: int


class TablePage(BaseModel):
    schema_name: str
    table_name: str
    columns: list[str]
    rows: list[list[Any]]
    page: int
    page_size: int
    has_next: bool


class ChatRequest(BaseModel):
    conversation_id: UUID | None = None
    message: str = Field(min_length=1, max_length=4000)


class ChatMessageOut(BaseModel):
    id: UUID
    role: Literal["user", "assistant"]
    content: str
    displays: list[str] = []
    table: list[dict[str, Any]] | None = None
    trace: list[dict[str, Any]] = []
    created_at: datetime


class ChatResponse(BaseModel):
    conversation_id: UUID
    message: ChatMessageOut


class ConversationOut(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[ChatMessageOut]


class ModelStatus(BaseModel):
    key: str
    loaded: bool
    version: str | None = None
    error: str | None = None
