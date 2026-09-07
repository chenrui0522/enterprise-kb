from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db_session
from app.core.redis import get_redis
from app.models.entity import AuditEvent
from app.core.tenant import tenant_dependency

router = APIRouter(tags=["system"])


@router.get("/healthz")
async def healthz() -> dict:
    settings = get_settings()
    checks: dict[str, str] = {"status": "ok"}
    try:
        redis = get_redis()
        await redis.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "unavailable"
    return checks


@router.get("/api/v1/audit/events")
async def list_audit_events(
    limit: int = 100,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(tenant_dependency),
) -> list[dict]:
    result = await session.execute(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == tenant_id)
        .order_by(AuditEvent.created_at.desc())
        .limit(min(limit, 500))
    )
    return [
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
