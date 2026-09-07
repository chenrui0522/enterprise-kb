from __future__ import annotations

from contextvars import ContextVar

from fastapi import Header

_current_tenant: ContextVar[str] = ContextVar("current_tenant", default="default")


def set_current_tenant(tenant_id: str) -> None:
    _current_tenant.set(tenant_id or "default")


def current_tenant() -> str:
    return _current_tenant.get()


async def tenant_dependency(x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID")) -> str:
    """Resolve tenant from request header; defaults to a local placeholder tenant."""
    tenant = x_tenant_id or "default"
    set_current_tenant(tenant)
    return tenant
