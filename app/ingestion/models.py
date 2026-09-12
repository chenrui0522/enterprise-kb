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
    chunk_type: str = "text"
    heading_path: str = ""
    clause_no: str = ""
    step_no: str = ""
    faq_id: str = ""
    table_id: str = ""
    row_start: int = 0
    row_end: int = 0
    parent_id: str = ""
    chunker_version: str = ""
