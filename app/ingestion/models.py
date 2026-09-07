from __future__ import annotations

from pydantic import BaseModel

from app.retrieval.chunk import ChunkRecord


class ParsedPage(BaseModel):
    page_number: int
    text: str


class ChunkDraft(BaseModel):
    text: str
    page: int
    section: str
    chunk_index: int
