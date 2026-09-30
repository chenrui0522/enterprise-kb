"""Leave-ledger API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class LeaveLedgerSourceOut(BaseModel):
    id: str
    role: str
    filename: str
    parse_preview: dict[str, Any] | None = None

    model_config = {"from_attributes": True}


class LeaveLedgerJobOut(BaseModel):
    id: str
    tenant_id: str
    status: str
    warnings: list[dict[str, Any]] | None = None
    compute_result: dict[str, Any] | None = None
    resolved_warnings: dict[str, Any] | None = None
    confirmed_at: datetime | None = None
    created_at: datetime | None = None
    sources: list[LeaveLedgerSourceOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class LeaveLedgerReviewIn(BaseModel):
    resolutions: dict[str, Any] | None = None


class LeaveLedgerVoidIn(BaseModel):
    reason: str | None = None


class LeaveLedgerMergeIn(BaseModel):
    prior_job_id: str = Field(min_length=1, max_length=32)


class LeaveLedgerJobSummaryOut(BaseModel):
    id: str
    status: str
    confirmed_at: datetime | None = None
    created_at: datetime | None = None
    person_count: int = 0

    model_config = {"from_attributes": True}
