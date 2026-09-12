from __future__ import annotations

from pydantic import BaseModel, Field


class ChunkRecord(BaseModel):
    """One indexed chunk. `vector` is optional on read path (not returned by Milvus)."""

    id: str
    text: str = Field(min_length=1, max_length=4096)
    title: str = ""
    doc_id: str
    version_id: str
    chunk_index: int
    page: int
    section: str = ""
    tenant_id: str
    vector: list[float] = Field(default_factory=list)
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
    parent_id: str = ""
    chunker_version: str = ""


class SearchHit(BaseModel):
    chunk_id: str
    doc_id: str
    version_id: str
    title: str
    page: int
    section: str
    text: str
    score: float
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