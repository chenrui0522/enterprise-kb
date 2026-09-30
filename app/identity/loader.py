"""Build Principal from live user_positions (sys_user_post) + establishment + projects."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.constants import RELATION_ESTABLISHMENT
from app.identity.feature_gates import compute_feature_org_flags
from app.identity.principal import Principal
from app.models.identity import (
    Position,
    PositionRole,
    ProjectMember,
    RolePermission,
    User,
    UserOrgRelation,
    UserPosition,
)


async def load_principal(db: AsyncSession, user_id: str) -> Principal | None:
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        return None

    posts = (
        await db.execute(
            select(UserPosition, Position)
            .join(Position, Position.id == UserPosition.position_id)
            .where(UserPosition.user_id == user_id, Position.status == "active")
        )
    ).all()

    position_ids = [position.id for _, position in posts]
    org_unit_ids: set[str] = {position.org_unit_id for _, position in posts}
    domains: set[str] = {
        position.domain for _, position in posts if position.domain
    }

    establishments = (
        await db.execute(
            select(UserOrgRelation.org_unit_id).where(
                UserOrgRelation.user_id == user_id,
                UserOrgRelation.relation == RELATION_ESTABLISHMENT,
            )
        )
    ).scalars().all()
    establishment_ids = list(establishments)
    org_unit_ids.update(establishment_ids)

    project_ids = (
        await db.execute(
            select(ProjectMember.project_id).where(ProjectMember.user_id == user_id)
        )
    ).scalars().all()

    permissions: set[str] = set()
    if position_ids:
        perm_rows = (
            await db.execute(
                select(RolePermission.permission_code)
                .join(PositionRole, PositionRole.role_id == RolePermission.role_id)
                .where(PositionRole.position_id.in_(position_ids))
            )
        ).scalars().all()
        permissions.update(perm_rows)

    staffing_org_ok, leave_ledger_org_ok = await compute_feature_org_flags(
        db,
        tenant_id=user.tenant_id,
        org_unit_ids=org_unit_ids,
        permissions=permissions,
    )

    return Principal(
        user_id=user.id,
        tenant_id=user.tenant_id,
        username=user.username,
        display_name=user.display_name or user.username,
        site=user.site,
        clearance=user.clearance,
        org_unit_ids=tuple(sorted(org_unit_ids)),
        domains=tuple(sorted(domains)),
        project_ids=tuple(sorted(project_ids)),
        permissions=tuple(sorted(permissions)),
        position_ids=tuple(sorted(position_ids)),
        establishment_org_unit_ids=tuple(sorted(establishment_ids)),
        staffing_org_ok=staffing_org_ok,
        leave_ledger_org_ok=leave_ledger_org_ok,
    )
