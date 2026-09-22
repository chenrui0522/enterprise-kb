"""Bootstrap admin and seed Autley org / demo users."""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import dispose_engine, get_session_factory
from app.identity.constants import (
    DEFAULT_TENANT_ID,
    RELATION_ESTABLISHMENT,
    ROLE_PERMISSIONS,
)
from app.identity.passwords import hash_password
from app.models.entity import new_id
from app.models.identity import (
    OrgUnit,
    Permission,
    Position,
    PositionRole,
    Project,
    Role,
    RolePermission,
    User,
    UserOrgRelation,
    UserPosition,
)


async def ensure_permissions_and_roles(session, tenant_id: str) -> dict[str, Role]:
    for code, desc in {
        "documents:read": "Read documents",
        "documents:write": "Write documents",
        "chat:use": "Chat",
        "audit:read": "Audit",
        "users:manage": "Users",
        "orgs:manage": "Orgs",
        "projects:manage": "Projects",
    }.items():
        if await session.get(Permission, code) is None:
            session.add(Permission(code=code, description=desc))
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


async def seed_org_tree(session, tenant_id: str) -> dict[str, OrgUnit]:
    """Minimal Autley tree for demos (codes are stable)."""
    nodes = [
        ("company", "autley", "奥特莱物流科技有限公司", None, None),
        ("office", "gm_office", "总经办", "autley", None),
        ("center", "product", "产品中心", "autley", None),
        ("center", "production", "生产中心", "autley", "shuozhou"),
        ("center", "rd", "研发中心", "autley", None),
        ("center", "marketing", "营销中心", "autley", None),
        ("dept", "software", "软件部", "production", "shuozhou"),
        ("dept", "sales", "销售部", "marketing", None),
        ("dept", "elec_std_rd", "电气标准化研发部", "rd", None),
        ("dept", "procurement", "采购部", "production", "shuozhou"),
    ]
    by_code: dict[str, OrgUnit] = {}
    for type_, code, name, parent_code, site in nodes:
        existing = (
            await session.execute(
                select(OrgUnit).where(OrgUnit.tenant_id == tenant_id, OrgUnit.code == code)
            )
        ).scalar_one_or_none()
        if existing:
            by_code[code] = existing
            continue
        parent_id = by_code[parent_code].id if parent_code else None
        unit = OrgUnit(
            id=new_id(),
            tenant_id=tenant_id,
            parent_id=parent_id,
            type=type_,
            code=code,
            name=name,
            default_site=site,
        )
        session.add(unit)
        await session.flush()
        by_code[code] = unit
    return by_code


async def create_admin(
    *,
    username: str,
    password: str,
    org_code: str,
    clearance: str,
    site: str,
) -> str:
    settings = get_settings()
    tenant_id = settings.default_tenant_id or DEFAULT_TENANT_ID
    factory = get_session_factory()
    async with factory() as session:
        roles = await ensure_permissions_and_roles(session, tenant_id)
        orgs = await seed_org_tree(session, tenant_id)
        if org_code not in orgs:
            raise SystemExit(f"unknown org code: {org_code}")
        pos = (
            await session.execute(
                select(Position).where(
                    Position.tenant_id == tenant_id,
                    Position.org_unit_id == orgs[org_code].id,
                    Position.code == "sys_admin",
                )
            )
        ).scalar_one_or_none()
        if pos is None:
            pos = Position(
                id=new_id(),
                tenant_id=tenant_id,
                org_unit_id=orgs[org_code].id,
                code="sys_admin",
                name="系统管理员",
                domain=None,
            )
            session.add(pos)
            await session.flush()
            session.add(PositionRole(id=new_id(), position_id=pos.id, role_id=roles["admin"].id))
        user = (
            await session.execute(
                select(User).where(User.tenant_id == tenant_id, User.username == username)
            )
        ).scalar_one_or_none()
        if user is None:
            user = User(
                id=new_id(),
                tenant_id=tenant_id,
                username=username,
                display_name=username,
                password_hash=hash_password(password),
                site=site,
                clearance=clearance,
                must_change_password=True,
            )
            session.add(user)
            await session.flush()
        else:
            user.password_hash = hash_password(password)
            user.clearance = clearance
            user.site = site
        binding = (
            await session.execute(
                select(UserPosition).where(
                    UserPosition.user_id == user.id, UserPosition.position_id == pos.id
                )
            )
        ).scalar_one_or_none()
        if binding is None:
            session.add(UserPosition(id=new_id(), user_id=user.id, position_id=pos.id))
        await session.commit()
        return user.id


async def seed_demo() -> None:
    settings = get_settings()
    tenant_id = settings.default_tenant_id or DEFAULT_TENANT_ID
    factory = get_session_factory()
    async with factory() as session:
        roles = await ensure_permissions_and_roles(session, tenant_id)
        orgs = await seed_org_tree(session, tenant_id)

        def ensure_position(code: str, name: str, org_code: str, domain: str | None, role: str):
            async def _inner():
                pos = (
                    await session.execute(
                        select(Position).where(
                            Position.tenant_id == tenant_id,
                            Position.org_unit_id == orgs[org_code].id,
                            Position.code == code,
                        )
                    )
                ).scalar_one_or_none()
                if pos is None:
                    pos = Position(
                        id=new_id(),
                        tenant_id=tenant_id,
                        org_unit_id=orgs[org_code].id,
                        code=code,
                        name=name,
                        domain=domain,
                    )
                    session.add(pos)
                    await session.flush()
                    session.add(
                        PositionRole(id=new_id(), position_id=pos.id, role_id=roles[role].id)
                    )
                return pos

            return _inner()

        software_eng = await ensure_position(
            "software_engineer", "软件工程师", "software", "software", "reader"
        )
        gm_assistant = await ensure_position(
            "gm_assistant", "总经理助理", "gm_office", None, "reader"
        )
        sales_km = await ensure_position(
            "key_account_manager", "大客户经理", "sales", "sales", "editor"
        )

        async def ensure_user(username: str, site: str, positions: list, establishment: str | None):
            user = (
                await session.execute(
                    select(User).where(User.tenant_id == tenant_id, User.username == username)
                )
            ).scalar_one_or_none()
            if user is None:
                user = User(
                    id=new_id(),
                    tenant_id=tenant_id,
                    username=username,
                    display_name=username,
                    password_hash=hash_password("ChangeMe123!"),
                    site=site,
                    clearance="general",
                )
                session.add(user)
                await session.flush()
            for pos in positions:
                exists = (
                    await session.execute(
                        select(UserPosition).where(
                            UserPosition.user_id == user.id, UserPosition.position_id == pos.id
                        )
                    )
                ).scalar_one_or_none()
                if exists is None:
                    session.add(UserPosition(id=new_id(), user_id=user.id, position_id=pos.id))
            if establishment:
                exists = (
                    await session.execute(
                        select(UserOrgRelation).where(
                            UserOrgRelation.user_id == user.id,
                            UserOrgRelation.org_unit_id == orgs[establishment].id,
                            UserOrgRelation.relation == RELATION_ESTABLISHMENT,
                        )
                    )
                ).scalar_one_or_none()
                if exists is None:
                    session.add(
                        UserOrgRelation(
                            id=new_id(),
                            user_id=user.id,
                            org_unit_id=orgs[establishment].id,
                            relation=RELATION_ESTABLISHMENT,
                        )
                    )
            return user

        await ensure_user("yuan", "suzhou", [software_eng], "rd")
        await ensure_user("ma", "taiyuan", [gm_assistant, sales_km], None)

        project = (
            await session.execute(
                select(Project).where(Project.tenant_id == tenant_id, Project.code == "P-DEMO")
            )
        ).scalar_one_or_none()
        if project is None:
            session.add(
                Project(id=new_id(), tenant_id=tenant_id, code="P-DEMO", name="示例项目")
            )
        await session.commit()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    admin = sub.add_parser("create-admin", help="Create first admin (password + org + clearance)")
    admin.add_argument("--username", required=True)
    admin.add_argument("--password", required=True)
    admin.add_argument("--org-code", default="gm_office")
    admin.add_argument("--clearance", required=True, choices=["general", "core"])
    admin.add_argument("--site", default="taiyuan")

    sub.add_parser("seed-demo", help="Seed Autley org tree + yuan/ma demo users")

    args = parser.parse_args(argv)

    async def _run() -> None:
        try:
            if args.cmd == "create-admin":
                user_id = await create_admin(
                    username=args.username,
                    password=args.password,
                    org_code=args.org_code,
                    clearance=args.clearance,
                    site=args.site,
                )
                print(f"admin ready id={user_id}")
            elif args.cmd == "seed-demo":
                await seed_demo()
                print("demo seed complete (yuan/ma password=ChangeMe123!)")
        finally:
            await dispose_engine()

    asyncio.run(_run())


if __name__ == "__main__":
    main(sys.argv[1:])
