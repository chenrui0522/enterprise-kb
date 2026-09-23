"""Permission catalog bootstrap must keep DB roles aligned with ROLE_PERMISSIONS."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.db import Base
from app.identity.bootstrap import ensure_permissions_and_roles
from app.identity.constants import (
    DEFAULT_TENANT_ID,
    PERM_STAFFING_READ,
    PERM_STAFFING_WRITE,
    ROLE_PERMISSIONS,
)
from app.models.entity import new_id
from app.models.identity import Permission, Role, RolePermission


@pytest.fixture()
def session_factory(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'boot.sqlite'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _prepare() -> None:
        import app.models.entity  # noqa: F401
        import app.models.identity  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_prepare())
    try:
        yield factory
    finally:
        asyncio.run(engine.dispose())


def test_ensure_permissions_backfills_missing_staffing(session_factory) -> None:
    """Simulate pre-staffing DB: editor/reader exist without staffing links."""

    async def _run() -> None:
        async with session_factory() as session:
            # Stale catalog: docs/chat only
            for code in ("documents:read", "documents:write", "chat:use"):
                session.add(Permission(code=code, description=code))
            await session.flush()
            editor = Role(id=new_id(), tenant_id=DEFAULT_TENANT_ID, code="editor", name="editor")
            reader = Role(id=new_id(), tenant_id=DEFAULT_TENANT_ID, code="reader", name="reader")
            session.add_all([editor, reader])
            await session.flush()
            session.add_all(
                [
                    RolePermission(
                        id=new_id(), role_id=editor.id, permission_code="documents:read"
                    ),
                    RolePermission(
                        id=new_id(), role_id=editor.id, permission_code="documents:write"
                    ),
                    RolePermission(id=new_id(), role_id=editor.id, permission_code="chat:use"),
                    RolePermission(
                        id=new_id(), role_id=reader.id, permission_code="documents:read"
                    ),
                    RolePermission(id=new_id(), role_id=reader.id, permission_code="chat:use"),
                ]
            )
            await session.commit()

        async with session_factory() as session:
            await ensure_permissions_and_roles(session, DEFAULT_TENANT_ID)
            await session.commit()

            assert await session.get(Permission, PERM_STAFFING_READ) is not None
            assert await session.get(Permission, PERM_STAFFING_WRITE) is not None

            editor = (
                await session.execute(
                    select(Role).where(
                        Role.tenant_id == DEFAULT_TENANT_ID, Role.code == "editor"
                    )
                )
            ).scalar_one()
            reader = (
                await session.execute(
                    select(Role).where(
                        Role.tenant_id == DEFAULT_TENANT_ID, Role.code == "reader"
                    )
                )
            ).scalar_one()
            editor_perms = set(
                (
                    await session.execute(
                        select(RolePermission.permission_code).where(
                            RolePermission.role_id == editor.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            reader_perms = set(
                (
                    await session.execute(
                        select(RolePermission.permission_code).where(
                            RolePermission.role_id == reader.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert set(ROLE_PERMISSIONS["editor"]) <= editor_perms
            assert set(ROLE_PERMISSIONS["reader"]) <= reader_perms
            assert PERM_STAFFING_READ in editor_perms
            assert PERM_STAFFING_WRITE in editor_perms
            assert PERM_STAFFING_READ in reader_perms

    asyncio.run(_run())
