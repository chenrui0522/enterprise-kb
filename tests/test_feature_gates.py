"""Department dual-gates for staffing / leave-ledger."""

from __future__ import annotations

import pytest

from app.identity.constants import (
    PERM_LEAVE_LEDGER_READ,
    PERM_LEAVE_LEDGER_WRITE,
    PERM_STAFFING_READ,
    PERM_STAFFING_WRITE,
    PERM_USERS_MANAGE,
)
from app.identity.feature_gates import (
    can_use_leave_ledger,
    can_use_staffing,
    descendant_org_codes,
)
from app.identity.principal import Principal


def test_descendant_codes_project_mgmt_includes_divs() -> None:
    codes = descendant_org_codes({"project_mgmt"})
    assert "project_mgmt" in codes
    assert "project_div_1" in codes
    assert "project_div_2" in codes
    assert "ops" not in codes


def test_descendant_codes_ops_center() -> None:
    codes = descendant_org_codes({"ops"})
    assert "ops" in codes
    assert "ops_planning" in codes
    assert "ops_hr" in codes
    assert "ops_admin" in codes
    assert "ops_sz_hr_admin" in codes
    assert "project_mgmt" not in codes


def _p(*, perms: tuple[str, ...] = (), staffing_ok: bool = False, leave_ok: bool = False) -> Principal:
    return Principal(
        user_id="u1",
        tenant_id="autley",
        username="u",
        display_name="u",
        site="taiyuan",
        clearance="general",
        permissions=perms,
        staffing_org_ok=staffing_ok,
        leave_ledger_org_ok=leave_ok,
    )


def test_staffing_requires_org_and_perm() -> None:
    assert not can_use_staffing(
        _p(perms=(PERM_STAFFING_WRITE,), staffing_ok=False), write=True
    )
    assert can_use_staffing(
        _p(perms=(PERM_STAFFING_WRITE,), staffing_ok=True), write=True
    )
    assert can_use_staffing(
        _p(perms=(PERM_STAFFING_READ,), staffing_ok=True), write=None
    )
    assert not can_use_staffing(
        _p(perms=(PERM_STAFFING_READ,), staffing_ok=True), write=True
    )


def test_leave_requires_org_and_perm() -> None:
    assert not can_use_leave_ledger(
        _p(perms=(PERM_LEAVE_LEDGER_WRITE,), leave_ok=False), write=True
    )
    assert can_use_leave_ledger(
        _p(perms=(PERM_LEAVE_LEDGER_WRITE,), leave_ok=True), write=True
    )


def test_admin_flag_allows_org() -> None:
    # load_principal sets both org flags True when users:manage is present;
    # helpers trust the flags.
    p = _p(
        perms=(PERM_USERS_MANAGE, PERM_STAFFING_WRITE, PERM_LEAVE_LEDGER_WRITE),
        staffing_ok=True,
        leave_ok=True,
    )
    assert can_use_staffing(p, write=True)
    assert can_use_leave_ledger(p, write=True)


@pytest.mark.asyncio
async def test_resolve_feature_org_ids_includes_wecom_named_root(tmp_path, monkeypatch) -> None:
    """WeCom numeric-code 项目管理部 must count even when seed uses project_mgmt."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.db import Base
    from app.identity.feature_gates import FEATURE_STAFFING, resolve_feature_org_ids
    from app.models.entity import new_id
    from app.models.identity import OrgUnit
    import app.models.identity  # noqa: F401

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'org.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        marketing = OrgUnit(
            id=new_id(), tenant_id="autley", code="marketing", name="营销中心", type="center"
        )
        wecom = OrgUnit(
            id=new_id(),
            tenant_id="autley",
            code="001",
            name="项目管理部",
            type="dept",
            parent_id=marketing.id,
        )
        seed = OrgUnit(
            id=new_id(),
            tenant_id="autley",
            code="project_mgmt",
            name="项目管理部",
            type="dept",
            parent_id=marketing.id,
        )
        session.add_all([marketing, wecom, seed])
        await session.commit()
        ids = await resolve_feature_org_ids(
            session, tenant_id="autley", feature=FEATURE_STAFFING
        )
        assert wecom.id in ids
        assert seed.id in ids
