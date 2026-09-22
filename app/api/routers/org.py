from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.service import write_audit
from app.core.db import get_db_session
from app.core.errors import AppError
from app.identity.constants import (
    ORG_UNIT_TYPES,
    PERM_ORGS_MANAGE,
    PERM_PROJECTS_MANAGE,
    PERM_USERS_MANAGE,
)
from app.identity.deps import require_any_permission, require_permission
from app.identity.principal import Principal
from app.models.identity import (
    OrgUnit,
    Position,
    PositionRole,
    Project,
    ProjectMember,
    Role,
)
from app.schemas.identity import (
    OrgUnitCreate,
    OrgUnitOut,
    PositionCreate,
    PositionOut,
    ProjectCreate,
    ProjectMemberRequest,
    validate_domain,
)

router = APIRouter(tags=["org"])


@router.get("/org-units", response_model=list[OrgUnitOut])
async def list_org_units(
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_any_permission(PERM_ORGS_MANAGE, PERM_USERS_MANAGE)),
) -> list[OrgUnitOut]:
    rows = (
        await session.execute(
            select(OrgUnit)
            .where(OrgUnit.tenant_id == principal.tenant_id)
            .order_by(OrgUnit.code)
        )
    ).scalars().all()
    return [OrgUnitOut.model_validate(row) for row in rows]


@router.post("/org-units", response_model=OrgUnitOut, status_code=201)
async def create_org_unit(
    body: OrgUnitCreate,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permission(PERM_ORGS_MANAGE)),
) -> OrgUnitOut:
    if body.type not in ORG_UNIT_TYPES:
        raise AppError("invalid org unit type", status_code=422)
    if body.parent_id:
        parent = await session.get(OrgUnit, body.parent_id)
        if parent is None or parent.tenant_id != principal.tenant_id:
            raise AppError("父节点不存在", status_code=404)
    unit = OrgUnit(
        tenant_id=principal.tenant_id,
        parent_id=body.parent_id,
        type=body.type,
        code=body.code,
        name=body.name,
        default_site=body.default_site,
    )
    session.add(unit)
    await session.commit()
    await session.refresh(unit)
    await write_audit(
        session,
        principal.tenant_id,
        action="org.create",
        resource_type="org_unit",
        resource_id=unit.id,
        detail={"code": unit.code, "name": unit.name},
        actor=principal.username,
    )
    return OrgUnitOut.model_validate(unit)


@router.get("/positions", response_model=list[PositionOut])
async def list_positions(
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_any_permission(PERM_ORGS_MANAGE, PERM_USERS_MANAGE)),
) -> list[PositionOut]:
    rows = (
        await session.execute(
            select(Position).where(Position.tenant_id == principal.tenant_id).order_by(Position.code)
        )
    ).scalars().all()
    out: list[PositionOut] = []
    for row in rows:
        role_codes = (
            await session.execute(
                select(Role.code)
                .join(PositionRole, PositionRole.role_id == Role.id)
                .where(PositionRole.position_id == row.id)
            )
        ).scalars().all()
        item = PositionOut.model_validate(row)
        item.role_codes = list(role_codes)
        out.append(item)
    return out


@router.post("/positions", response_model=PositionOut, status_code=201)
async def create_position(
    body: PositionCreate,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permission(PERM_ORGS_MANAGE)),
) -> PositionOut:
    try:
        domain = validate_domain(body.domain)
    except ValueError as exc:
        raise AppError(str(exc), status_code=422) from exc
    org = await session.get(OrgUnit, body.org_unit_id)
    if org is None or org.tenant_id != principal.tenant_id:
        raise AppError("组织节点不存在", status_code=404)
    position = Position(
        tenant_id=principal.tenant_id,
        org_unit_id=body.org_unit_id,
        code=body.code,
        name=body.name,
        domain=domain,
    )
    session.add(position)
    await session.flush()
    for role_code in body.role_codes:
        role = (
            await session.execute(
                select(Role).where(Role.tenant_id == principal.tenant_id, Role.code == role_code)
            )
        ).scalar_one_or_none()
        if role is None:
            raise AppError(f"角色不存在: {role_code}", status_code=422)
        session.add(PositionRole(position_id=position.id, role_id=role.id))
    await session.commit()
    await session.refresh(position)
    item = PositionOut.model_validate(position)
    item.role_codes = list(body.role_codes)
    await write_audit(
        session,
        principal.tenant_id,
        action="position.create",
        resource_type="position",
        resource_id=position.id,
        detail={"code": position.code, "org_unit_id": position.org_unit_id, "domain": position.domain},
        actor=principal.username,
    )
    return item


@router.post("/projects", response_model=dict, status_code=201)
async def create_project(
    body: ProjectCreate,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permission(PERM_PROJECTS_MANAGE)),
) -> dict:
    project = Project(
        tenant_id=principal.tenant_id,
        code=body.code,
        name=body.name,
    )
    session.add(project)
    await session.commit()
    await write_audit(
        session,
        principal.tenant_id,
        action="project.create",
        resource_type="project",
        resource_id=project.id,
        detail={"code": project.code, "name": project.name},
        actor=principal.username,
    )
    return {"id": project.id, "code": project.code, "name": project.name}


@router.get("/projects", response_model=list[dict])
async def list_projects(
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permission(PERM_PROJECTS_MANAGE)),
) -> list[dict]:
    rows = (
        await session.execute(
            select(Project).where(Project.tenant_id == principal.tenant_id).order_by(Project.code)
        )
    ).scalars().all()
    return [{"id": r.id, "code": r.code, "name": r.name, "status": r.status} for r in rows]


@router.get("/projects/{project_id}/members", response_model=list[dict])
async def list_project_members(
    project_id: str,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permission(PERM_PROJECTS_MANAGE)),
) -> list[dict]:
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != principal.tenant_id:
        raise AppError("项目不存在", status_code=404)
    from app.models.identity import User

    rows = (
        await session.execute(
            select(ProjectMember, User)
            .join(User, User.id == ProjectMember.user_id)
            .where(ProjectMember.project_id == project_id)
            .order_by(User.username)
        )
    ).all()
    return [
        {"user_id": user.id, "username": user.username, "display_name": user.display_name}
        for _, user in rows
    ]


@router.post("/projects/{project_id}/members", status_code=204)
async def add_project_member(
    project_id: str,
    body: ProjectMemberRequest,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permission(PERM_PROJECTS_MANAGE)),
) -> None:
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != principal.tenant_id:
        raise AppError("项目不存在", status_code=404)
    existing = (
        await session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id, ProjectMember.user_id == body.user_id
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(ProjectMember(project_id=project_id, user_id=body.user_id))
        await session.commit()
        await write_audit(
            session,
            principal.tenant_id,
            action="project.member_add",
            resource_type="project",
            resource_id=project_id,
            detail={"user_id": body.user_id},
            actor=principal.username,
        )


@router.delete("/projects/{project_id}/members/{user_id}", status_code=204)
async def remove_project_member(
    project_id: str,
    user_id: str,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permission(PERM_PROJECTS_MANAGE)),
) -> None:
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != principal.tenant_id:
        raise AppError("项目不存在", status_code=404)
    row = (
        await session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if row:
        await session.delete(row)
        await session.commit()
        await write_audit(
            session,
            principal.tenant_id,
            action="project.member_remove",
            resource_type="project",
            resource_id=project_id,
            detail={"user_id": user_id},
            actor=principal.username,
        )
