"""Ensure catalog permissions/roles in DB match code constants.

Role permission strings live in `ROLE_PERMISSIONS`. Older databases only
received them when someone ran create-admin / seed-demo, so adding a new
permission (e.g. staffing:*) left live roles stale. Call
`ensure_permissions_and_roles` on API startup (and from CLI seeds).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.constants import ROLE_PERMISSIONS
from app.models.entity import new_id
from app.models.identity import Permission, Role, RolePermission

_PERMISSION_DESCRIPTIONS: dict[str, str] = {
    "documents:read": "Read documents",
    "documents:write": "Write documents",
    "chat:use": "Chat",
    "audit:read": "Audit",
    "users:manage": "Users",
    "orgs:manage": "Orgs",
    "projects:manage": "Projects",
    "staffing:read": "Staffing read",
    "staffing:write": "Staffing write",
}


async def ensure_permissions_and_roles(session: AsyncSession, tenant_id: str) -> dict[str, Role]:
    """Idempotently upsert permission rows and role→permission links for tenant."""
    for code, desc in _PERMISSION_DESCRIPTIONS.items():
        if await session.get(Permission, code) is None:
            session.add(Permission(code=code, description=desc))
    # Also ensure every code referenced by ROLE_PERMISSIONS exists (forward-safe).
    for perms in ROLE_PERMISSIONS.values():
        for code in perms:
            if await session.get(Permission, code) is None:
                session.add(
                    Permission(
                        code=code,
                        description=_PERMISSION_DESCRIPTIONS.get(code, code),
                    )
                )
    await session.flush()

    roles: dict[str, Role] = {}
    for code, perms in ROLE_PERMISSIONS.items():
        row = (
            await session.execute(
                select(Role).where(Role.tenant_id == tenant_id, Role.code == code)
            )
        ).scalar_one_or_none()
        if row is None:
            row = Role(id=new_id(), tenant_id=tenant_id, code=code, name=code)
            session.add(row)
            await session.flush()
        roles[code] = row
        for perm in perms:
            exists = (
                await session.execute(
                    select(RolePermission).where(
                        RolePermission.role_id == row.id,
                        RolePermission.permission_code == perm,
                    )
                )
            ).scalar_one_or_none()
            if exists is None:
                session.add(RolePermission(id=new_id(), role_id=row.id, permission_code=perm))
    await session.flush()
    return roles
