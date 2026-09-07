from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=500)


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str = Field(min_length=1, max_length=4000)


class CitationOut(BaseModel):
    chunk_id: str
    doc_id: str
    document_title: str
    page: int
    section: str | None = None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: str
    content: str
    rewritten_query: str | None = None
    citations: list[CitationOut] = Field(default_factory=list)
    created_at: datetime


class FeedbackIn(BaseModel):
    message_id: str
    rating: str = Field(pattern="^(up|down)$")
    comment: str | None = Field(default=None, max_length=2000)
