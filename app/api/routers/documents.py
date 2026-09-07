from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db_session
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.core.tenant import tenant_dependency
from app.ingestion.queue import enqueue_job, make_job
from app.ingestion.storage import FileDocumentStorage
from app.ingestion.converters import IMAGE_EXTENSIONS
from app.models.entity import Document, DocumentVersion
from app.schemas.documents import DocumentOut, DocumentUploadOut
from app.chat.service import write_audit

logger = get_logger("api.documents")
router = APIRouter(tags=["documents"])

MAX_UPLOAD_BYTES = 200 * 1024 * 1024
ALLOWED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".md",
    ".markdown",
    ".txt",
    ".html",
    ".htm",
    ".csv",
    ".json",
    *IMAGE_EXTENSIONS,
}


@router.post("/documents", response_model=DocumentUploadOut, status_code=202)
async def upload_document(
    file: UploadFile = File(...),
    ocr: bool = Query(False, description="强制走 MinerU OCR 解析扫描件/复杂彩页手册"),
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(tenant_dependency),
) -> DocumentUploadOut:
    settings = get_settings()
    filename = file.filename or "unnamed.pdf"
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=(
                "暂不支持该格式；支持 PDF / Word(.docx) / PPT(.pptx) / Excel(.xlsx) / "
                "Markdown / TXT / HTML / CSV / JSON / 图片(PNG/JPG)"
            ),
        )
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件过大（上限 200MB）")
    if suffix == ".pdf" and not data.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="文件不是有效的 PDF（文件损坏或非 PDF）")
    if suffix in {".docx", ".pptx", ".xlsx"} and not data.startswith(b"PK\x03\x04"):
        raise HTTPException(status_code=400, detail="Office 文件已损坏或不是有效的压缩文档")
    if suffix == ".png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(status_code=400, detail="文件不是有效的 PNG 图片")
    if suffix in {".jpg", ".jpeg"} and not data.startswith(b"\xff\xd8\xff"):
        raise HTTPException(status_code=400, detail="文件不是有效的 JPG/JPEG 图片")

    needs_ocr = ocr or suffix in IMAGE_EXTENSIONS
    if needs_ocr and not settings.mineru_enabled:
        raise HTTPException(
            status_code=503,
            detail="扫描件/图片需要 MinerU OCR：请先在 .env 配置 KB_MINERU_URL 并启动 mineru-api 服务",
        )
    if ocr and suffix not in {".pdf", *IMAGE_EXTENSIONS}:
        raise HTTPException(
            status_code=422,
            detail="强制 OCR（ocr=true）仅对 PDF 与图片文件生效",
        )

    document = Document(
        tenant_id=tenant_id,
        title=filename.rsplit(".", 1)[0],
        filename=filename,
        status="pending",
        stage="queued",
    )
    session.add(document)
    await session.flush()
    version = DocumentVersion(
        tenant_id=tenant_id,
        doc_id=document.id,
        status="pending",
        stage="queued",
        storage_key="",
        parse_mode="ocr" if needs_ocr else "auto",
    )
    session.add(version)
    await session.flush()

    storage = FileDocumentStorage(settings.document_storage_dir)
    storage_key = storage.store(document.id, version.id, filename, data)
    version.storage_key = storage_key
    await session.commit()

    await enqueue_job(get_redis(), make_job(document.id, version.id, tenant_id, storage_key))
    await write_audit(
        session,
        tenant_id,
        action="document.upload",
        resource_type="document",
        resource_id=document.id,
        detail={"filename": filename},
    )
    return DocumentUploadOut(id=document.id, status=document.status, stage=document.stage)


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    status: str | None = None,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(tenant_dependency),
) -> list[DocumentOut]:
    query = select(Document).where(Document.tenant_id == tenant_id).order_by(Document.created_at.desc())
    if status:
        query = query.where(Document.status == status)
    result = await session.execute(query.limit(200))
    return [DocumentOut.model_validate(item) for item in result.scalars()]


@router.get("/documents/{document_id}", response_model=DocumentOut)
async def document_detail(
    document_id: str,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(tenant_dependency),
) -> DocumentOut:
    document = await session.get(Document, document_id)
    if document is None or document.tenant_id != tenant_id:
        raise NotFoundError("文档不存在")
    return DocumentOut.model_validate(document)


@router.post("/documents/{document_id}/retry", status_code=202)
async def retry_document(
    document_id: str,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(tenant_dependency),
) -> dict:
    document = await session.get(Document, document_id)
    if document is None or document.tenant_id != tenant_id:
        raise NotFoundError("文档不存在")
    if document.status != "failed":
        raise HTTPException(status_code=409, detail="只有失败状态的文档可以重试")
    result = await session.execute(
        select(DocumentVersion)
        .where(
            DocumentVersion.doc_id == document_id,
            DocumentVersion.tenant_id == tenant_id,
        )
        .order_by(DocumentVersion.created_at.desc())
        .limit(1)
    )
    version = result.scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=409, detail="没有可重试的处理版本")

    version.status = "pending"
    version.stage = "queued"
    version.error_message = None
    version.attempt += 1
    document.status = "pending"
    document.stage = "queued"
    document.error_message = None
    await session.commit()

    await enqueue_job(
        get_redis(),
        make_job(document.id, version.id, tenant_id, version.storage_key),
    )
    await write_audit(
        session,
        tenant_id,
        action="document.retry",
        resource_type="document",
        resource_id=document.id,
    )
    return {"id": document.id, "status": document.status, "stage": document.stage}
