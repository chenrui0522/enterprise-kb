"""Leave-ledger job lifecycle: upload, compute, review, confirm, export, void."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, NotFoundError
from app.core.logging import get_logger, log_event, preview_text, timed_event
from app.identity.principal import Principal
from app.ingestion.storage import FileDocumentStorage
from app.leave_ledger.classify import classify_source
from app.leave_ledger.config_data import hq_address_keywords, load_holidays
from app.leave_ledger.export import build_ledger_xlsx
from app.leave_ledger.merge import (
    filter_warnings_covered_by_prior,
    merge_ledger_rows,
    prior_ot_keys,
)
from app.leave_ledger.parse import (
    ParsedSources,
    parse_leave,
    parse_overtime,
    parse_punch,
    parse_travel,
    parsed_to_dict,
)
from app.leave_ledger.rules import compute_ledger, compute_result_to_dict
from app.models.entity import AuditEvent, new_id
from app.models.leave_ledger import LeaveLedgerJob, LeaveLedgerSnapshot, LeaveLedgerSource

logger = get_logger("leave_ledger")

ROLE_LABEL = {
    "travel": "出差申请",
    "overtime": "加班申请",
    "leave": "请假申请",
    "punch": "打卡日报",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _actor(principal: Principal) -> str:
    return principal.username or principal.user_id


async def _add_audit(
    session: AsyncSession,
    *,
    tenant_id: str,
    actor: str,
    action: str,
    resource_id: str | None,
    detail: dict | None,
) -> None:
    session.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor=actor,
            action=action,
            resource_type="leave_ledger_job",
            resource_id=resource_id,
            detail=detail,
        )
    )


async def get_job(session: AsyncSession, tenant_id: str, job_id: str) -> LeaveLedgerJob:
    job = await session.get(LeaveLedgerJob, job_id)
    if not job or job.tenant_id != tenant_id:
        raise NotFoundError("调休台账任务不存在")
    return job


async def list_sources(session: AsyncSession, job_id: str) -> list[LeaveLedgerSource]:
    stmt = select(LeaveLedgerSource).where(LeaveLedgerSource.job_id == job_id)
    return list((await session.execute(stmt)).scalars().all())


def _open_blocking_warnings(
    warnings: list[dict[str, Any]] | None,
    resolved: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    resolved = resolved or {}
    open_items: list[dict[str, Any]] = []
    for w in warnings or []:
        if not w.get("blocking", True):
            continue
        code = w.get("code") or ""
        detail = w.get("detail") or {}
        # missing source: accept via resolutions.missing_sources[role]=accept
        if code.startswith("missing_source_"):
            role = (detail.get("role") or code.replace("missing_source_", "")).strip()
            if (resolved.get("missing_sources") or {}).get(role) == "accept":
                continue
            open_items.append(w)
            continue
        if code == "approval_not_passed":
            key = detail.get("key") or ""
            entry = (resolved.get("approval_not_passed") or {}).get(key)
            if entry in ("include", "exclude"):
                continue
            open_items.append(w)
            continue
        if code in ("ot_half_day_mismatch", "ot_missing_punch"):
            key = f"{detail.get('person')}:{detail.get('date')}"
            bucket = resolved.get(code) or {}
            if bucket.get(key) in ("accept_full", "accept_half", "exclude"):
                continue
            open_items.append(w)
            continue
        if code == "hq_address_unknown":
            key = f"{detail.get('person')}:{detail.get('start')}:{detail.get('end')}"
            if (resolved.get("hq_address_unknown") or {}).get(key) == "accept":
                continue
            open_items.append(w)
            continue
        # generic: resolved[code] truthy clears
        if resolved.get(code):
            continue
        open_items.append(w)
    return open_items


def _include_unapproved_keys(resolved: dict[str, Any] | None) -> set[str]:
    resolved = resolved or {}
    out: set[str] = set()
    for key, action in (resolved.get("approval_not_passed") or {}).items():
        if action == "include":
            out.add(key)
    return out


def _ot_resolutions_from_resolved(
    resolved: dict[str, Any] | None,
) -> dict[tuple[str, str], str]:
    """Map (person, date_iso) -> exclude|accept_half|accept_full."""
    resolved = resolved or {}
    out: dict[tuple[str, str], str] = {}
    for code in ("ot_missing_punch", "ot_half_day_mismatch"):
        bucket = resolved.get(code) or {}
        if not isinstance(bucket, dict):
            continue
        for key, action in bucket.items():
            if action not in ("exclude", "accept_half", "accept_full"):
                continue
            if not isinstance(key, str) or ":" not in key:
                continue
            person, date_s = key.split(":", 1)
            if person and date_s:
                out[(person, date_s)] = str(action)
    return out


async def _recompute(
    session: AsyncSession,
    job: LeaveLedgerJob,
    storage: FileDocumentStorage,
) -> LeaveLedgerJob:
    # Preserve sticky merge before sources-only recompute replaces compute_result.
    prior_merge_id = (job.compute_result or {}).get("merged_from_job_id")

    settings = get_settings()
    sources = await list_sources(session, job.id)
    present = {s.role for s in sources}
    parsed = ParsedSources()
    with timed_event(logger, "leave_ledger.parse") as meta:
        for src in sources:
            data = storage.read_bytes(src.storage_key)
            if src.role == "travel":
                parsed.travel = parse_travel(data)
                src.parse_preview = {"count": len(parsed.travel)}
            elif src.role == "overtime":
                parsed.overtime = parse_overtime(data)
                src.parse_preview = {"count": len(parsed.overtime)}
            elif src.role == "leave":
                parsed.leave = parse_leave(data)
                src.parse_preview = {"count": len(parsed.leave)}
            elif src.role == "punch":
                parsed.punch = parse_punch(data)
                src.parse_preview = {"count": len(parsed.punch)}
        meta["roles"] = sorted(present)
        meta["travel"] = len(parsed.travel)
        meta["overtime"] = len(parsed.overtime)
        meta["leave"] = len(parsed.leave)
        meta["punch"] = len(parsed.punch)

    holidays = load_holidays(settings)
    with timed_event(logger, "leave_ledger.compute") as meta:
        result = compute_ledger(
            parsed,
            present_roles=present,
            hq_keywords=hq_address_keywords(settings),
            holidays=holidays,
            full_day_hours=settings.leave_ledger_full_day_hours_threshold,
            half_day_hours=settings.leave_ledger_half_day_hours_threshold,
            merge_gap_days=settings.leave_ledger_travel_merge_gap_days,
            include_unapproved=_include_unapproved_keys(job.resolved_warnings),
            ot_resolutions=_ot_resolutions_from_resolved(job.resolved_warnings),
        )
        meta["row_count"] = len(result.rows)
        meta["warning_count"] = len(result.warnings)

    payload = compute_result_to_dict(result)
    payload["parsed"] = parsed_to_dict(parsed)
    job.compute_result = payload
    job.warnings = payload["warnings"]

    if prior_merge_id:
        await _apply_merge_onto_job(session, job, prior_job_id=str(prior_merge_id))

    open_w = _open_blocking_warnings(job.warnings, job.resolved_warnings)
    job.status = "needs_review" if open_w else "parsed"
    log_event(
        logger,
        "leave_ledger.compute.done",
        job_id=job.id,
        status=job.status,
        rows=len((job.compute_result or {}).get("rows") or []),
        warnings=len(job.warnings or []),
        open_warnings=len(open_w),
        merged_from_job_id=prior_merge_id,
    )
    return job


async def _apply_merge_onto_job(
    session: AsyncSession,
    job: LeaveLedgerJob,
    *,
    prior_job_id: str,
) -> str:
    """Merge prior confirmed snapshot into job.compute_result. Returns prior id."""
    prior = await get_job(session, job.tenant_id, prior_job_id)
    if prior.status != "confirmed":
        raise AppError("上月任务必须为已确认状态", status_code=400)

    snap = await session.scalar(
        select(LeaveLedgerSnapshot).where(LeaveLedgerSnapshot.job_id == prior.id)
    )
    prior_rows = (snap.rows if snap else None) or (prior.compute_result or {}).get(
        "rows"
    ) or []
    if not prior_rows:
        raise AppError("上月已确认任务没有可用快照行", status_code=400)

    settings = get_settings()
    current_rows = list((job.compute_result or {}).get("rows") or [])
    merged_rows = merge_ledger_rows(
        prior_rows,
        current_rows,
        merge_gap_days=settings.leave_ledger_travel_merge_gap_days,
    )

    payload = dict(job.compute_result or {})
    payload["rows"] = merged_rows
    payload["totals"] = {
        "person_count": len(merged_rows),
        "total_comp_days": sum(float(r.get("total_comp_days") or 0) for r in merged_rows),
        "used_comp_days": sum(float(r.get("used_comp_days") or 0) for r in merged_rows),
        "remaining_comp_days": sum(
            float(r.get("remaining_comp_days") or 0) for r in merged_rows
        ),
    }
    payload["merged_from_job_id"] = prior.id

    warnings = filter_warnings_covered_by_prior(
        job.warnings, prior_ot_keys(prior_rows)
    )
    job.compute_result = payload
    job.warnings = warnings
    open_w = _open_blocking_warnings(job.warnings, job.resolved_warnings)
    job.status = "needs_review" if open_w else "parsed"
    return prior.id


async def create_empty_job(
    session: AsyncSession,
    *,
    principal: Principal,
) -> LeaveLedgerJob:
    """Create a collecting job with no sources yet (chat incremental flow)."""
    job = LeaveLedgerJob(
        id=new_id(),
        tenant_id=principal.tenant_id,
        status="collecting",
        created_by=principal.user_id,
        resolved_warnings={},
    )
    session.add(job)
    await session.flush()
    await _add_audit(
        session,
        tenant_id=principal.tenant_id,
        actor=_actor(principal),
        action="leave_ledger.job.create",
        resource_id=job.id,
        detail={"roles": [], "file_count": 0},
    )
    await session.commit()
    await session.refresh(job)
    return job


async def create_job_with_files(
    session: AsyncSession,
    *,
    principal: Principal,
    files: list[tuple[str, bytes]],
    storage: FileDocumentStorage,
) -> LeaveLedgerJob:
    if not files:
        raise AppError("请至少上传一个源文件", status_code=400)
    job_id = new_id()
    job = LeaveLedgerJob(
        id=job_id,
        tenant_id=principal.tenant_id,
        status="collecting",
        created_by=principal.user_id,
        resolved_warnings={},
    )
    session.add(job)
    await session.flush()

    seen_roles: set[str] = set()
    for filename, data in files:
        role = classify_source(filename, data)
        if role in seen_roles:
            raise AppError(f"重复上传同一角色文件：{ROLE_LABEL.get(role, role)}", status_code=400)
        seen_roles.add(role)
        storage_key = storage.store_leave_ledger(job_id, role, filename, data)
        session.add(
            LeaveLedgerSource(
                tenant_id=principal.tenant_id,
                job_id=job_id,
                role=role,
                filename=filename,
                storage_key=storage_key,
            )
        )
        log_event(
            logger,
            "leave_ledger.source.uploaded",
            job_id=job_id,
            role=role,
            filename=preview_text(filename, limit=80),
            size=len(data),
        )

    await session.flush()
    await _recompute(session, job, storage)
    await _add_audit(
        session,
        tenant_id=principal.tenant_id,
        actor=_actor(principal),
        action="leave_ledger.job.create",
        resource_id=job.id,
        detail={"roles": sorted(seen_roles), "file_count": len(files)},
    )
    await session.commit()
    await session.refresh(job)
    return job


async def add_source_file(
    session: AsyncSession,
    *,
    principal: Principal,
    job_id: str,
    filename: str,
    data: bytes,
    storage: FileDocumentStorage,
    role: str | None = None,
) -> LeaveLedgerJob:
    job = await get_job(session, principal.tenant_id, job_id)
    if job.status in ("confirmed", "voided"):
        raise AppError("已确认或已作废的任务不可再上传", status_code=400)
    if role:
        if role not in ROLE_LABEL:
            raise AppError(f"未知来源角色：{role}", status_code=400)
        resolved_role = role
    else:
        resolved_role = classify_source(filename, data)
    existing = await list_sources(session, job.id)
    if any(s.role == resolved_role for s in existing):
        raise AppError(
            f"该任务已有{ROLE_LABEL.get(resolved_role, resolved_role)}，请勿重复上传",
            status_code=400,
        )
    storage_key = storage.store_leave_ledger(job.id, resolved_role, filename, data)
    session.add(
        LeaveLedgerSource(
            tenant_id=principal.tenant_id,
            job_id=job.id,
            role=resolved_role,
            filename=filename,
            storage_key=storage_key,
        )
    )
    await session.flush()
    await _recompute(session, job, storage)
    await _add_audit(
        session,
        tenant_id=principal.tenant_id,
        actor=_actor(principal),
        action="leave_ledger.source.upload",
        resource_id=job.id,
        detail={"role": resolved_role, "filename": preview_text(filename, limit=80)},
    )
    await session.commit()
    await session.refresh(job)
    return job


async def review_job(
    session: AsyncSession,
    *,
    principal: Principal,
    job_id: str,
    resolutions: dict[str, Any] | None,
    storage: FileDocumentStorage,
) -> LeaveLedgerJob:
    job = await get_job(session, principal.tenant_id, job_id)
    if job.status in ("confirmed", "voided"):
        raise AppError("已确认或已作废的任务不可复核", status_code=400)
    merged = dict(job.resolved_warnings or {})
    for k, v in (resolutions or {}).items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = {**merged[k], **v}
        else:
            merged[k] = v
    job.resolved_warnings = merged
    await _recompute(session, job, storage)
    await _add_audit(
        session,
        tenant_id=principal.tenant_id,
        actor=_actor(principal),
        action="leave_ledger.job.review",
        resource_id=job.id,
        detail={"resolution_keys": list((resolutions or {}).keys())},
    )
    await session.commit()
    await session.refresh(job)
    return job


async def confirm_job(
    session: AsyncSession,
    *,
    principal: Principal,
    job_id: str,
) -> LeaveLedgerJob:
    job = await get_job(session, principal.tenant_id, job_id)
    if job.status == "voided":
        raise AppError("任务已作废", status_code=400)
    if job.status == "confirmed":
        return job
    open_w = _open_blocking_warnings(job.warnings, job.resolved_warnings)
    if open_w:
        raise AppError(
            f"仍有 {len(open_w)} 条未决议告警，无法确认",
            status_code=400,
        )
    rows = (job.compute_result or {}).get("rows") or []
    sources = await list_sources(session, job.id)
    snap = await session.scalar(
        select(LeaveLedgerSnapshot).where(LeaveLedgerSnapshot.job_id == job.id)
    )
    if snap is None:
        snap = LeaveLedgerSnapshot(
            tenant_id=principal.tenant_id,
            job_id=job.id,
        )
        session.add(snap)
    snap.rows = rows
    snap.source_roles = [s.role for s in sources]
    job.status = "confirmed"
    job.confirmed_at = _utcnow()
    job.confirmed_by = principal.user_id
    await _add_audit(
        session,
        tenant_id=principal.tenant_id,
        actor=_actor(principal),
        action="leave_ledger.job.confirm",
        resource_id=job.id,
        detail={"row_count": len(rows), "person_count": len(rows)},
    )
    log_event(
        logger,
        "leave_ledger.confirm",
        job_id=job.id,
        rows=len(rows),
    )
    await session.commit()
    await session.refresh(job)
    return job


async def void_job(
    session: AsyncSession,
    *,
    principal: Principal,
    job_id: str,
    reason: str | None = None,
) -> LeaveLedgerJob:
    job = await get_job(session, principal.tenant_id, job_id)
    job.status = "voided"
    job.voided_at = _utcnow()
    job.voided_by = principal.user_id
    job.void_reason = reason or ""
    await _add_audit(
        session,
        tenant_id=principal.tenant_id,
        actor=_actor(principal),
        action="leave_ledger.job.void",
        resource_id=job.id,
        detail={"reason": preview_text(reason or "", limit=80)},
    )
    log_event(logger, "leave_ledger.void", job_id=job.id)
    await session.commit()
    await session.refresh(job)
    return job


async def list_confirmed_jobs(
    session: AsyncSession,
    *,
    tenant_id: str,
) -> list[LeaveLedgerJob]:
    stmt = (
        select(LeaveLedgerJob)
        .where(
            LeaveLedgerJob.tenant_id == tenant_id,
            LeaveLedgerJob.status == "confirmed",
        )
        .order_by(LeaveLedgerJob.confirmed_at.desc().nullslast())
    )
    return list((await session.execute(stmt)).scalars().all())


async def merge_job(
    session: AsyncSession,
    *,
    principal: Principal,
    job_id: str,
    prior_job_id: str,
) -> LeaveLedgerJob:
    if not prior_job_id:
        raise AppError("请选择已确认的上月台账任务", status_code=400)
    if prior_job_id == job_id:
        raise AppError("不能与自身合并", status_code=400)

    job = await get_job(session, principal.tenant_id, job_id)
    if job.status in ("confirmed", "voided"):
        raise AppError("已确认或已作废的任务不可再合并写回", status_code=400)
    if not (job.compute_result or {}).get("rows"):
        raise AppError("本月任务尚无计算结果，无法合并", status_code=400)

    prior_id = await _apply_merge_onto_job(session, job, prior_job_id=prior_job_id)
    merged_rows = (job.compute_result or {}).get("rows") or []

    await _add_audit(
        session,
        tenant_id=principal.tenant_id,
        actor=_actor(principal),
        action="leave_ledger.job.merge",
        resource_id=job.id,
        detail={
            "merged_from_job_id": prior_id,
            "row_count": len(merged_rows),
        },
    )
    log_event(
        logger,
        "leave_ledger.merge",
        job_id=job.id,
        prior_job_id=prior_id,
        rows=len(merged_rows),
    )
    await session.commit()
    await session.refresh(job)
    return job


async def export_job_xlsx(
    session: AsyncSession,
    *,
    tenant_id: str,
    job_id: str,
) -> bytes:
    job = await get_job(session, tenant_id, job_id)
    if job.status != "confirmed":
        raise AppError("仅已确认任务可导出正式台账", status_code=400)
    snap = await session.scalar(
        select(LeaveLedgerSnapshot).where(LeaveLedgerSnapshot.job_id == job.id)
    )
    rows = (snap.rows if snap else None) or (job.compute_result or {}).get("rows") or []
    log_event(logger, "leave_ledger.export", job_id=job.id, rows=len(rows))
    return build_ledger_xlsx(rows)


def job_to_out_dict(job: LeaveLedgerJob, sources: list[LeaveLedgerSource]) -> dict[str, Any]:
    return {
        "id": job.id,
        "tenant_id": job.tenant_id,
        "status": job.status,
        "warnings": job.warnings,
        "compute_result": job.compute_result,
        "resolved_warnings": job.resolved_warnings,
        "confirmed_at": job.confirmed_at,
        "created_at": job.created_at,
        "sources": [
            {
                "id": s.id,
                "role": s.role,
                "filename": s.filename,
                "parse_preview": s.parse_preview,
            }
            for s in sources
        ],
    }
