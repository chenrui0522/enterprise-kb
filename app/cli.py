"""Bootstrap admin and seed Autley org / demo users."""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import dispose_engine, get_session_factory
from app.identity.bootstrap import ensure_permissions_and_roles
from app.identity.constants import (
    DEFAULT_TENANT_ID,
    RELATION_ESTABLISHMENT,
)
from app.identity.org_seed import seed_org_tree
from app.identity.passwords import hash_password
from app.models.entity import new_id
from app.models.identity import (
    Position,
    PositionRole,
    Project,
    User,
    UserOrgRelation,
    UserPosition,
)


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
    backfill = sub.add_parser(
        "backfill-conversation-titles",
        help="Rule-title conversations still named 新对话 that already have user messages",
    )
    backfill.add_argument("--tenant-id", default=None)
    backfill.add_argument("--limit", type=int, default=500)

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
            elif args.cmd == "backfill-conversation-titles":
                from app.chat.title import backfill_default_titles

                factory = get_session_factory()
                async with factory() as session:
                    n = await backfill_default_titles(
                        session, tenant_id=args.tenant_id, limit=args.limit
                    )
                print(f"backfilled {n} conversation title(s)")
        finally:
            await dispose_engine()

    asyncio.run(_run())


if __name__ == "__main__":
    main(sys.argv[1:])
