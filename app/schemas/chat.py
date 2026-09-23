from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=500)


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=500)


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    title: str
    title_source: str = "default"
    created_at: datetime
    updated_at: datetime


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str = Field(min_length=1, max_length=4000)
    active_tool: str | None = Field(default=None, max_length=64)
    attachment_id: str | None = Field(default=None, max_length=32)


class ChatToolOut(BaseModel):
    id: str
    label: str


class ChatAttachmentOut(BaseModel):
    id: str
    filename: str
    storage_key: str


class ToolActionIn(BaseModel):
    conversation_id: str
    action: str = Field(min_length=1, max_length=64)
    payload: dict | None = None


class ToolActionOut(BaseModel):
    content: str
    card: dict | None = None
    conversation_id: str


class CitationImageOut(BaseModel):
    image_id: str
    url: str
    caption: str = ""
    page: int = 0


class CitationOut(BaseModel):
    chunk_id: str
    doc_id: str
    document_title: str
    page: int
    section: str | None = None
    images: list[CitationImageOut] = []


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: str
    content: str
    rewritten_query: str | None = None
    compressed: bool = False
    meta: dict | None = None
    citations: list[CitationOut] = Field(default_factory=list)
    created_at: datetime


class ConversationMemoryOut(BaseModel):
    conversation_id: str
    content: str
    version: int
    token_count: int
    covered_from_message_id: str | None = None
    covered_to_message_id: str | None = None
    updated_at: datetime


class FeedbackIn(BaseModel):
    message_id: str
    rating: str = Field(pattern="^(up|down)$")
    comment: str | None = Field(default=None, max_length=2000)
