"""Chat composer attachment persistence helpers."""

from __future__ import annotations

import json
from pathlib import Path

from app.core.config import get_settings
from app.core.errors import AppError
from app.ingestion.storage import FileDocumentStorage
from app.models.entity import new_id

MAX_CHAT_ATTACHMENT_BYTES = 40 * 1024 * 1024


def save_chat_xlsx(*, user_id: str, filename: str, data: bytes) -> dict:
    if not filename.lower().endswith((".xlsx", ".xls")):
        raise AppError("仅支持 Excel（.xlsx）附件", status_code=400)
    if len(data) > MAX_CHAT_ATTACHMENT_BYTES:
        raise AppError("附件过大", status_code=400)
    if len(data) == 0:
        raise AppError("空附件", status_code=400)
    attachment_id = new_id()
    storage = FileDocumentStorage(get_settings().document_storage_dir)
    storage_key = storage.store_chat_attachment(attachment_id, filename, data)
    meta = {
        "id": attachment_id,
        "filename": filename,
        "storage_key": storage_key,
        "user_id": user_id,
    }
    meta_path = Path(get_settings().document_storage_dir) / "chat_attachments" / attachment_id / "meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return meta


def load_attachment(attachment_id: str, *, user_id: str) -> dict:
    meta_path = Path(get_settings().document_storage_dir) / "chat_attachments" / attachment_id / "meta.json"
    if not meta_path.exists():
        raise AppError("附件不存在或已过期", status_code=404)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("user_id") != user_id:
        raise AppError("无权使用该附件", status_code=403)
    storage = FileDocumentStorage(get_settings().document_storage_dir)
    data = storage.read_bytes(meta["storage_key"])
    return {
        "id": meta["id"],
        "filename": meta["filename"],
        "storage_key": meta["storage_key"],
        "data": data,
    }
