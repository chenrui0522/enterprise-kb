"""Staffing daily-import API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db_session
from app.core.errors import AppError
from app.core.logging import get_logger
from app.identity.constants import PERM_STAFFING_READ, PERM_STAFFING_WRITE
from app.identity.deps import require_permission, tenant_from_principal
from app.identity.principal import Principal
from app.ingestion.storage import FileDocumentStorage
from app.models.identity import Project
from app.models.entity import new_id
from app.schemas.staffing import (
    FactOut,
    ProjectSummaryOut,
    ReviewIn,
    StaffingBatchOut,
    VoidIn,
    VoidOut,
)
from app.staffing import service as staffing_service
from sqlalchemy import select

logger = get_logger("api.staffing")
router = APIRouter(tags=["staffing"])

MAX_UPLOAD_BYTES = 40 * 1024 * 1024


@router.get("/staffing/my-projects", response_model=list[dict])
async def my_staffing_projects(
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permission(PERM_STAFFING_READ)),
) -> list[dict]:
    """Projects the current user may import staffing into."""
    if not principal.project_ids and "projects:manage" not in principal.permissions:
        return []
    stmt = select(Project).where(Project.tenant_id == principal.tenant_id)
    if "projects:manage" not in principal.permissions:
        stmt = stmt.where(Project.id.in_(list(principal.project_ids)))
    rows = (await session.execute(stmt.order_by(Project.code))).scalars().all()
    return [{"id": r.id, "code": r.code, "name": r.name, "status": r.status} for r in rows]


@router.post("/staffing/imports", response_model=StaffingBatchOut, status_code=201)
async def upload_staffing_import(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permission(PERM_STAFFING_WRITE)),
    tenant_id: str = Depends(tenant_from_principal),
) -> StaffingBatchOut:
    _ = tenant_id
    filename = file.filename or "daily.xlsx"
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise AppError("文件过大", status_code=413)
    batch_id = new_id()
    storage = FileDocumentStorage(get_settings().document_storage_dir)
    storage_key = storage.store_staffing(batch_id, filename, data)
    batch = await staffing_service.create_import_batch(
        session,
        principal=principal,
        filename=filename,
        data=data,
        storage_key=storage_key,
        batch_id=batch_id,
    )
    return StaffingBatchOut.model_validate(batch)


@router.get("/staffing/imports/{batch_id}", response_model=StaffingBatchOut)
async def get_staffing_import(
    batch_id: str,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permission(PERM_STAFFING_READ)),
    tenant_id: str = Depends(tenant_from_principal),
) -> StaffingBatchOut:
    batch = await staffing_service.get_batch(session, tenant_id, batch_id)
    if batch.project_id:
        await staffing_service.ensure_project_access(principal, batch.project_id)
    return StaffingBatchOut.model_validate(batch)


@router.post("/staffing/imports/{batch_id}/review", response_model=StaffingBatchOut)
async def review_staffing_import(
    batch_id: str,
    body: ReviewIn,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permission(PERM_STAFFING_WRITE)),
) -> StaffingBatchOut:
    batch = await staffing_service.review_batch(
        session,
        principal=principal,
        batch_id=batch_id,
        project_id=body.project_id,
        resolutions=body.resolutions,
        person_renames=body.person_renames,
    )
    return StaffingBatchOut.model_validate(batch)


@router.post("/staffing/imports/{batch_id}/confirm", response_model=StaffingBatchOut)
async def confirm_staffing_import(
    batch_id: str,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permission(PERM_STAFFING_WRITE)),
) -> StaffingBatchOut:
    batch = await staffing_service.confirm_batch(
        session, principal=principal, batch_id=batch_id
    )
    return StaffingBatchOut.model_validate(batch)


@router.get(
    "/staffing/projects/{project_id}/summary", response_model=ProjectSummaryOut
)
async def staffing_summary(
    project_id: str,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permission(PERM_STAFFING_READ)),
) -> ProjectSummaryOut:
    data = await staffing_service.project_summary(
        session, principal=principal, project_id=project_id
    )
    return ProjectSummaryOut.model_validate(data)


@router.get("/staffing/projects/{project_id}/export.xlsx")
async def staffing_export_xlsx(
    project_id: str,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permission(PERM_STAFFING_READ)),
) -> Response:
    data = await staffing_service.export_project_xlsx(
        session, principal=principal, project_id=project_id
    )
    filename = f"staffing-{project_id}.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/staffing/projects/{project_id}/facts", response_model=list[FactOut])
async def staffing_facts(
    project_id: str,
    include_voided: bool = Query(False),
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permission(PERM_STAFFING_READ)),
) -> list[FactOut]:
    facts = await staffing_service.list_facts(
        session,
        principal=principal,
        project_id=project_id,
        include_voided=include_voided,
    )
    return [FactOut.model_validate(f) for f in facts]


@router.post("/staffing/projects/{project_id}/void", response_model=VoidOut)
async def staffing_void(
    project_id: str,
    body: VoidIn,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permission(PERM_STAFFING_WRITE)),
) -> VoidOut:
    count = await staffing_service.void_facts(
        session,
        principal=principal,
        project_id=project_id,
        scope=body.scope,
        dates=body.dates,
        person_names=body.person_names,
        batch_id=body.batch_id,
    )
    return VoidOut(voided_count=count)
