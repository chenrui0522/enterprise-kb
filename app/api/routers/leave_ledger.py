"""Leave-ledger API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db_session
from app.core.errors import AppError
from app.core.logging import get_logger
from app.identity.deps import require_leave_ledger, tenant_from_principal
from app.identity.principal import Principal
from app.ingestion.storage import FileDocumentStorage
from app.leave_ledger import service as leave_service
from app.schemas.leave_ledger import (
    LeaveLedgerJobOut,
    LeaveLedgerJobSummaryOut,
    LeaveLedgerMergeIn,
    LeaveLedgerReviewIn,
    LeaveLedgerVoidIn,
)

logger = get_logger("api.leave_ledger")
router = APIRouter(tags=["leave-ledger"])

MAX_UPLOAD_BYTES = 40 * 1024 * 1024


def _storage() -> FileDocumentStorage:
    return FileDocumentStorage(get_settings().document_storage_dir)


async def _job_out(session: AsyncSession, job) -> LeaveLedgerJobOut:
    sources = await leave_service.list_sources(session, job.id)
    return LeaveLedgerJobOut.model_validate(leave_service.job_to_out_dict(job, sources))


@router.get("/leave-ledger/jobs", response_model=list[LeaveLedgerJobSummaryOut])
async def list_leave_ledger_jobs(
    status: str = Query(default="confirmed"),
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_leave_ledger(write=False)),
    tenant_id: str = Depends(tenant_from_principal),
) -> list[LeaveLedgerJobSummaryOut]:
    _ = principal
    if status != "confirmed":
        raise AppError("目前仅支持 status=confirmed", status_code=400)
    jobs = await leave_service.list_confirmed_jobs(session, tenant_id=tenant_id)
    out: list[LeaveLedgerJobSummaryOut] = []
    for job in jobs:
        rows = (job.compute_result or {}).get("rows") or []
        out.append(
            LeaveLedgerJobSummaryOut(
                id=job.id,
                status=job.status,
                confirmed_at=job.confirmed_at,
                created_at=job.created_at,
                person_count=len(rows),
            )
        )
    return out


@router.post("/leave-ledger/jobs", response_model=LeaveLedgerJobOut, status_code=201)
async def create_leave_ledger_job(
    files: list[UploadFile] = File(...),
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_leave_ledger(write=True)),
) -> LeaveLedgerJobOut:
    payloads: list[tuple[str, bytes]] = []
    for f in files:
        data = await f.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise AppError(f"文件过大：{f.filename}", status_code=413)
        payloads.append((f.filename or "source.xlsx", data))
    job = await leave_service.create_job_with_files(
        session,
        principal=principal,
        files=payloads,
        storage=_storage(),
    )
    return await _job_out(session, job)


@router.get("/leave-ledger/jobs/{job_id}", response_model=LeaveLedgerJobOut)
async def get_leave_ledger_job(
    job_id: str,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_leave_ledger(write=False)),
    tenant_id: str = Depends(tenant_from_principal),
) -> LeaveLedgerJobOut:
    _ = principal
    job = await leave_service.get_job(session, tenant_id, job_id)
    return await _job_out(session, job)


@router.post("/leave-ledger/jobs/{job_id}/sources", response_model=LeaveLedgerJobOut)
async def upload_leave_ledger_source(
    job_id: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_leave_ledger(write=True)),
) -> LeaveLedgerJobOut:
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise AppError("文件过大", status_code=413)
    job = await leave_service.add_source_file(
        session,
        principal=principal,
        job_id=job_id,
        filename=file.filename or "source.xlsx",
        data=data,
        storage=_storage(),
    )
    return await _job_out(session, job)


@router.post("/leave-ledger/jobs/{job_id}/review", response_model=LeaveLedgerJobOut)
async def review_leave_ledger_job(
    job_id: str,
    body: LeaveLedgerReviewIn,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_leave_ledger(write=True)),
) -> LeaveLedgerJobOut:
    job = await leave_service.review_job(
        session,
        principal=principal,
        job_id=job_id,
        resolutions=body.resolutions,
        storage=_storage(),
    )
    return await _job_out(session, job)


@router.post("/leave-ledger/jobs/{job_id}/confirm", response_model=LeaveLedgerJobOut)
async def confirm_leave_ledger_job(
    job_id: str,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_leave_ledger(write=True)),
) -> LeaveLedgerJobOut:
    job = await leave_service.confirm_job(session, principal=principal, job_id=job_id)
    return await _job_out(session, job)


@router.post("/leave-ledger/jobs/{job_id}/merge", response_model=LeaveLedgerJobOut)
async def merge_leave_ledger_job(
    job_id: str,
    body: LeaveLedgerMergeIn,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_leave_ledger(write=True)),
) -> LeaveLedgerJobOut:
    job = await leave_service.merge_job(
        session,
        principal=principal,
        job_id=job_id,
        prior_job_id=body.prior_job_id,
    )
    return await _job_out(session, job)


@router.post("/leave-ledger/jobs/{job_id}/void", response_model=LeaveLedgerJobOut)
async def void_leave_ledger_job(
    job_id: str,
    body: LeaveLedgerVoidIn | None = None,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_leave_ledger(write=True)),
) -> LeaveLedgerJobOut:
    job = await leave_service.void_job(
        session,
        principal=principal,
        job_id=job_id,
        reason=(body.reason if body else None),
    )
    return await _job_out(session, job)


@router.get("/leave-ledger/jobs/{job_id}/export.xlsx")
async def export_leave_ledger_job(
    job_id: str,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_leave_ledger(write=False)),
    tenant_id: str = Depends(tenant_from_principal),
) -> Response:
    _ = principal
    data = await leave_service.export_job_xlsx(session, tenant_id=tenant_id, job_id=job_id)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="leave-ledger-{job_id}.xlsx"'
        },
    )
