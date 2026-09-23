from __future__ import annotations

import asyncio
from typing import Any

import httpx
from datetime import datetime

from fastapi import APIRouter, Depends, Response
from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db_session, get_engine
from app.core.redis import get_redis
from app.identity.constants import PERM_AUDIT_READ
from app.identity.deps import require_permission, tenant_from_principal
from app.identity.principal import Principal
from app.models.entity import AuditEvent
from app.retrieval.milvus_store import MilvusStore

router = APIRouter(tags=["system"])


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text_value = value.strip()
    if text_value.endswith("Z"):
        text_value = text_value[:-1] + "+00:00"
    return datetime.fromisoformat(text_value)


async def _check_postgres(timeout: float) -> str:
    try:

        async def _ping() -> None:
            engine = get_engine()
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))

        await asyncio.wait_for(_ping(), timeout=timeout)
        return "ok"
    except Exception:
        return "fail"


async def _check_redis(timeout: float) -> str:
    try:

        async def _ping() -> None:
            redis = get_redis()
            await redis.ping()

        await asyncio.wait_for(_ping(), timeout=timeout)
        return "ok"
    except Exception:
        return "fail"


async def _check_milvus(timeout: float) -> str:
    try:
        settings = get_settings()

        def _ping() -> None:
            store = MilvusStore(settings)
            # Lightweight: ensure client can talk to the server.
            store._client.list_collections()  # noqa: SLF001 - health probe only

        await asyncio.wait_for(asyncio.to_thread(_ping), timeout=timeout)
        return "ok"
    except Exception:
        return "fail"


async def _check_model_service(timeout: float) -> str:
    """Reachability + required embedding/rerank models actually launched.

    Xinference stays healthy with an empty model list after container restart;
    treating that as ok left uploads stuck after OCR with opaque embed 404s.
    """
    settings = get_settings()
    base = settings.embedder_base_url.rstrip("/")
    # OpenAI-compatible root is .../v1; list endpoint is .../v1/models.
    health_url = f"{base}/models" if base.endswith("/v1") else f"{base.rstrip('/')}/v1/models"
    required = {
        settings.embedder_model.strip(),
        settings.reranker_model.strip(),
    }
    required.discard("")
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(health_url)
            resp.raise_for_status()
            payload = resp.json()
        ids = {
            str(item.get("id") or "")
            for item in (payload.get("data") or [])
            if isinstance(item, dict)
        }
        if required and not required.issubset(ids):
            return "fail"
        return "ok"
    except Exception:
        return "fail"


@router.get("/healthz")
async def healthz(response: Response) -> dict[str, Any]:
    settings = get_settings()
    timeout = settings.health_check_timeout_seconds
    postgres, redis, milvus, model_service = await asyncio.gather(
        _check_postgres(timeout),
        _check_redis(timeout),
        _check_milvus(timeout),
        _check_model_service(timeout),
    )
    checks = {
        "postgres": postgres,
        "redis": redis,
        "milvus": milvus,
        "model_service": model_service,
    }
    if postgres == "fail":
        status = "unavailable"
        response.status_code = 503
    elif any(value == "fail" for value in checks.values()):
        status = "degraded"
        response.status_code = 200
    else:
        status = "ok"
        response.status_code = 200
    return {"status": status, "checks": checks}


@router.get("/api/v1/audit/events")
async def list_audit_events(
    limit: int = 100,
    offset: int = 0,
    action: str | None = None,
    actor: str | None = None,
    since: str | None = None,
    until: str | None = None,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permission(PERM_AUDIT_READ)),
    tenant_id: str = Depends(tenant_from_principal),
) -> dict:
    clauses = [AuditEvent.tenant_id == tenant_id]
    if action:
        clauses.append(AuditEvent.action == action)
    if actor:
        clauses.append(AuditEvent.actor == actor)
    try:
        since_dt = _parse_time(since)
        until_dt = _parse_time(until)
    except ValueError as exc:
        from app.core.errors import AppError

        raise AppError(f"无效的时间参数: {exc}", status_code=422) from exc
    if since_dt is not None:
        clauses.append(AuditEvent.created_at >= since_dt)
    if until_dt is not None:
        clauses.append(AuditEvent.created_at <= until_dt)

    where = and_(*clauses)
    total = (
        await session.execute(select(func.count()).select_from(AuditEvent).where(where))
    ).scalar_one()
    result = await session.execute(
        select(AuditEvent)
        .where(where)
        .order_by(AuditEvent.created_at.desc())
        .offset(max(offset, 0))
        .limit(min(max(limit, 1), 500))
    )
    items = [
        {
            "id": event.id,
            "tenant_id": event.tenant_id,
            "actor": event.actor,
            "action": event.action,
            "resource_type": event.resource_type,
            "resource_id": event.resource_id,
            "detail": event.detail,
            "created_at": event.created_at.isoformat(),
        }
        for event in result.scalars()
    ]
    return {"total": total, "offset": max(offset, 0), "limit": min(max(limit, 1), 500), "items": items}
