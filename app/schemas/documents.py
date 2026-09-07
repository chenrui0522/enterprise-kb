from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentUploadOut(BaseModel):
    id: str
    status: str
    stage: str
    message: str = "受理成功，正在后台处理"


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    title: str
    filename: str
    status: str
    stage: str
    error_message: str | None = None
    current_version_id: str | None = None
    page_count: int | None = None
    created_at: datetime
    updated_at: datetime
