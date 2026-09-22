"""End-to-end: bootstrap admin → seed yuan/ma → login matrix → bind requires clearance."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.cli import create_admin, seed_demo
from app.core.db import Base, get_db_session
from app.identity.constants import SESSION_COOKIE_NAME
from app.identity.loader import load_principal
from app.identity.visibility import build_visibility_expr
from app.api.main import app
from app.models.entity import Document
from app.models.identity import OrgUnit, Position, Project, ProjectMember, User


class FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str):
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None):
        self._store[key] = value

    async def incr(self, key: str) -> int:
        value = int(self._store.get(key, "0")) + 1
        self._store[key] = str(value)
        return value

    async def expire(self, key: str, seconds: int) -> None:
        return None

    async def delete(self, *keys: str) -> int:
        n = 0
        for key in keys:
            if self._store.pop(key, None) is not None:
                n += 1
        return n


@pytest.fixture()
def e2e_client(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "e2e.sqlite"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    fake_redis = FakeRedis()

    async def _prepare() -> None:
        import app.models.entity  # noqa: F401
        import app.models.identity  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_prepare())

    monkeypatch.setattr("app.core.db._engine", engine)
    monkeypatch.setattr("app.core.db._session_factory", factory)
    monkeypatch.setattr("app.cli.get_session_factory", lambda: factory)

    async def _noop_dispose() -> None:
        return None

    monkeypatch.setattr("app.cli.dispose_engine", _noop_dispose)

    async def _override_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = _override_db
    monkeypatch.setattr("app.api.routers.auth.get_redis", lambda: fake_redis)

    client = TestClient(app)
    try:
        yield client, factory
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def _login(client: TestClient, username: str, password: str) -> dict:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    assert SESSION_COOKIE_NAME in client.cookies
    return response.json()


def test_e2e_bootstrap_seed_login_matrix_and_bind_clearance(e2e_client):
    client, factory = e2e_client

    async def _bootstrap():
        admin_id = await create_admin(
            username="admin",
            password="AdminPass123!",
            org_code="gm_office",
            clearance="core",
            site="taiyuan",
        )
        await seed_demo()
        return admin_id

    assert asyncio.run(_bootstrap())

    async def _seed_docs():
        async with factory() as session:
            org_rows = (await session.execute(select(OrgUnit))).scalars().all()
            orgs = {row.code: row.id for row in org_rows}
            project = (
                await session.execute(select(Project).where(Project.code == "P-DEMO"))
            ).scalar_one()
            yuan = (await session.execute(select(User).where(User.username == "yuan"))).scalar_one()
            ma = (await session.execute(select(User).where(User.username == "ma"))).scalar_one()
            software_pos = (
                await session.execute(select(Position).where(Position.code == "software_engineer"))
            ).scalar_one()

            now = datetime.now(timezone.utc)
            samples = [
                ("sw-general", orgs["software"], None, None, "general"),
                ("sw-core", orgs["software"], None, None, "core"),
                ("rd-general", orgs["rd"], None, None, "general"),
                ("elec-general", orgs["elec_std_rd"], None, None, "general"),
                ("prod-general", orgs["production"], None, None, "general"),
                ("proc-general", orgs["procurement"], None, None, "general"),
                ("gm-general", orgs["gm_office"], None, None, "general"),
                ("sales-general", orgs["sales"], None, None, "general"),
                ("proj-sw-core", None, project.id, "software", "core"),
                ("proj-elec-core", None, project.id, "electrical", "core"),
                ("proj-sales", None, project.id, "sales", "general"),
            ]
            for title, org_id, project_id, domain, classification in samples:
                session.add(
                    Document(
                        tenant_id="autley",
                        title=title,
                        filename=f"{title}.pdf",
                        status="ready",
                        stage="ready",
                        org_unit_id=org_id,
                        project_id=project_id,
                        domain=domain,
                        classification=classification,
                        created_at=now,
                        updated_at=now,
                    )
                )
            session.add(ProjectMember(project_id=project.id, user_id=yuan.id))
            session.add(ProjectMember(project_id=project.id, user_id=ma.id))
            await session.commit()
            return {
                "orgs": orgs,
                "project_id": project.id,
                "yuan_id": yuan.id,
                "software_pos_id": software_pos.id,
            }

    ids = asyncio.run(_seed_docs())

    # --- admin ---
    admin = _login(client, "admin", "AdminPass123!")
    assert "users:manage" in admin["permissions"]
    assert admin["clearance"] == "core"
    admin_titles = {d["title"] for d in client.get("/api/v1/documents").json()}
    assert "gm-general" in admin_titles
    assert "sw-general" not in admin_titles  # admin does not bypass corpus
    client.post("/api/v1/auth/logout")

    # --- yuan matrix ---
    yuan_me = _login(client, "yuan", "ChangeMe123!")
    assert yuan_me["site"] == "suzhou"
    assert yuan_me["clearance"] == "general"
    assert yuan_me["domains"] == ["software"]
    assert ids["project_id"] in yuan_me["project_ids"]
    assert ids["orgs"]["software"] in yuan_me["org_unit_ids"]
    assert ids["orgs"]["rd"] in yuan_me["org_unit_ids"]
    assert ids["orgs"]["elec_std_rd"] not in yuan_me["org_unit_ids"]

    yuan_titles = {d["title"] for d in client.get("/api/v1/documents").json()}
    assert "sw-general" in yuan_titles
    assert "sw-core" not in yuan_titles
    assert "rd-general" in yuan_titles
    assert "elec-general" not in yuan_titles
    assert "prod-general" not in yuan_titles
    assert "proc-general" not in yuan_titles
    assert "proj-sw-core" in yuan_titles
    assert "proj-elec-core" not in yuan_titles
    client.post("/api/v1/auth/logout")

    # --- ma matrix ---
    ma_me = _login(client, "ma", "ChangeMe123!")
    assert ma_me["site"] == "taiyuan"
    assert set(ma_me["domains"]) == {"sales"}
    assert ids["orgs"]["gm_office"] in ma_me["org_unit_ids"]
    assert ids["orgs"]["sales"] in ma_me["org_unit_ids"]
    ma_titles = {d["title"] for d in client.get("/api/v1/documents").json()}
    assert "gm-general" in ma_titles
    assert "sales-general" in ma_titles
    assert "sw-general" not in ma_titles
    assert "rd-general" not in ma_titles
    assert "proj-sales" in ma_titles
    assert "proj-sw-core" not in ma_titles
    client.post("/api/v1/auth/logout")

    # --- chat visibility expr (same predicate as list) ---
    async def _chat_expr():
        async with factory() as session:
            principal = await load_principal(session, ids["yuan_id"])
            assert principal is not None
            return build_visibility_expr(principal)

    expr = asyncio.run(_chat_expr())
    assert ids["orgs"]["software"] in expr
    assert ids["orgs"]["rd"] in expr
    assert '"core"' not in expr
    assert ids["project_id"] in expr
    assert "software" in expr

    # --- bind/unbind requires clearance ---
    _login(client, "admin", "AdminPass123!")
    created = client.post(
        "/api/v1/users",
        json={
            "username": "temp_bind",
            "password": "TempPass123!",
            "display_name": "Temp",
            "site": "suzhou",
            "clearance": "general",
        },
    )
    assert created.status_code == 200, created.text
    temp_id = created.json()["id"]

    missing = client.post(
        f"/api/v1/users/{temp_id}/positions",
        json={"position_id": ids["software_pos_id"]},
    )
    assert missing.status_code == 422

    empty = client.post(
        f"/api/v1/users/{temp_id}/positions",
        json={"position_id": ids["software_pos_id"], "clearance": ""},
    )
    assert empty.status_code == 422

    ok = client.post(
        f"/api/v1/users/{temp_id}/positions",
        json={"position_id": ids["software_pos_id"], "clearance": "general"},
    )
    assert ok.status_code == 200, ok.text
    assert ids["software_pos_id"] in ok.json()["position_ids"]

    assert (
        client.delete(f"/api/v1/users/{temp_id}/positions/{ids['software_pos_id']}").status_code
        == 422
    )
    unbind_ok = client.delete(
        f"/api/v1/users/{temp_id}/positions/{ids['software_pos_id']}",
        params={"clearance": "general"},
    )
    assert unbind_ok.status_code == 200, unbind_ok.text
