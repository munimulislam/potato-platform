"""
Request and response models of the JSON API.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ExplorerQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    env_type: str | None = Field(None, max_length=20)
    year_from: int | None = Field(None, ge=1900, le=2100)
    year_to: int | None = Field(None, ge=1900, le=2100)
    location: str | None = Field(None, max_length=100)
    variety: str | None = Field(None, max_length=100)
    experiment: str | None = Field(None, max_length=100)
    trait: str | None = Field(
        None, max_length=64
    )  # one trait column, rows with a value only
    page: int = Field(1, ge=1)
    format: Literal["json", "csv"] = "json"

    @field_validator(
        "env_type",
        "year_from",
        "year_to",
        "location",
        "variety",
        "experiment",
        "trait",
        mode="before",
    )
    @classmethod
    def _blank_is_none(cls, v: Any) -> Any:
        # An empty form field arrives as "": treat it as no filter, not as a value
        if isinstance(v, str):
            return v.strip() or None
        return v

    @model_validator(mode="after")
    def _years_in_order(self) -> "ExplorerQuery":
        if (
            self.year_from is not None
            and self.year_to is not None
            and self.year_from > self.year_to
        ):
            raise ValueError("'Year from' must not be after 'Year to'")
        return self


class ExplorerOptions(BaseModel):
    """Values for the filter dropdowns, taken from the data itself."""

    env_types: list[str]
    locations: list[str]
    year_min: int | None
    year_max: int | None
    traits: list[str]


class ExplorerPage(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    page: int
    page_size: int
    has_next: bool
    options: ExplorerOptions


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
