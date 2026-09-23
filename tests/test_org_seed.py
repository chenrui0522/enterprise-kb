"""Org seed upsert: full address-book tree + parent moves preserve ids."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.db import Base
from app.identity.constants import DEFAULT_TENANT_ID
from app.identity.org_seed import ORG_SEED_NODES, seed_org_tree
from app.models.identity import OrgUnit


@pytest.fixture()
def seed_session(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'org.sqlite'}")
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


def test_org_seed_node_count_and_no_city_company_labels() -> None:
    codes = {code for _, code, *_ in ORG_SEED_NODES}
    assert len(ORG_SEED_NODES) == len(codes)
    assert "thailand" in codes
    assert "software" in codes
    assert "sales_taiyuan" in codes
    assert "ops_sz_hr_admin" in codes
    names = {name for _, _, name, *_ in ORG_SEED_NODES}
    assert "太原公司" not in names
    assert "朔州公司" not in names
    assert "苏州公司" not in names
    assert "总经理办" in names
    # Confirmed leaves: no invented children under these codes
    child_parents = {parent for _, _, _, parent, _ in ORG_SEED_NODES if parent}
    for leaf in (
        "sales_taiyuan",
        "prod_admin",
        "prod_ops",
        "qa",
        "elec_std_rd",
        "ops_planning",
        "ops_hr",
        "ops_admin",
        "ops_sz_hr_admin",
    ):
        assert leaf not in child_parents


def test_seed_org_tree_upsert_moves_software_under_product(seed_session) -> None:
    factory = seed_session

    async def _run() -> None:
        async with factory() as session:
            first = await seed_org_tree(session, DEFAULT_TENANT_ID)
            await session.commit()
            software_id = first["software"].id
            procurement_id = first["procurement"].id
            assert first["software"].parent_id == first["product"].id
            assert first["gm_office"].name == "总经理办"
            assert first["thailand"].parent_id == first["autley"].id

        async with factory() as session:
            # Simulate legacy parent under production then re-seed
            software = (
                await session.execute(
                    select(OrgUnit).where(
                        OrgUnit.tenant_id == DEFAULT_TENANT_ID, OrgUnit.code == "software"
                    )
                )
            ).scalar_one()
            production = (
                await session.execute(
                    select(OrgUnit).where(
                        OrgUnit.tenant_id == DEFAULT_TENANT_ID, OrgUnit.code == "production"
                    )
                )
            ).scalar_one()
            software.parent_id = production.id
            software.name = "软件部(旧)"
            await session.commit()

        async with factory() as session:
            second = await seed_org_tree(session, DEFAULT_TENANT_ID)
            await session.commit()
            assert second["software"].id == software_id
            assert second["procurement"].id == procurement_id
            assert second["software"].parent_id == second["product"].id
            assert second["software"].name == "软件部"
            assert second["gm_office"].name == "总经理办"
            assert len(second) == len(ORG_SEED_NODES)

    asyncio.run(_run())
