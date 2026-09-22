from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routers import system as system_module
from app.core.db import Base, get_db_session
from app.identity.constants import PERM_AUDIT_READ, PERM_CHAT_USE
from app.identity.deps import get_current_principal, require_permission, tenant_from_principal
from app.identity.principal import Principal
from app.models.entity import AuditEvent
import app.models.entity  # noqa: F401
import app.models.identity  # noqa: F401


def _principal(*, perms: tuple[str, ...], username: str = "auditor") -> Principal:
    return Principal(
        user_id="u-audit",
        tenant_id="autley",
        username=username,
        display_name=username,
        site="taiyuan",
        clearance="general",
        permissions=perms,
    )


class _SyncSessionBridge:
    """Minimal async-looking wrapper so FastAPI async deps can use sync SQLite."""

    def __init__(self, sync_session) -> None:
        self._session = sync_session

    async def execute(self, *args, **kwargs):
        return self._session.execute(*args, **kwargs)

    async def commit(self) -> None:
        self._session.commit()

    async def refresh(self, obj) -> None:
        self._session.refresh(obj)

    def add(self, obj) -> None:
        self._session.add(obj)


@pytest.fixture
def seeded_engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    with SessionLocal() as session:
        session.add_all(
            [
                AuditEvent(
                    tenant_id="autley",
                    actor="admin",
                    action="user.bind_position",
                    resource_type="user",
                    resource_id="u1",
                    detail={"position_id": "p1"},
                ),
                AuditEvent(
                    tenant_id="autley",
                    actor="admin",
                    action="auth.login",
                    resource_type="user",
                    resource_id="u1",
                ),
                AuditEvent(
                    tenant_id="other",
                    actor="outsider",
                    action="auth.login",
                    resource_type="user",
                    resource_id="x",
                ),
            ]
        )
        session.commit()
    return SessionLocal


def _client(SessionLocal, principal: Principal) -> TestClient:
    async def _db():
        sync = SessionLocal()
        try:
            yield _SyncSessionBridge(sync)
        finally:
            sync.close()

    from fastapi.responses import JSONResponse

    from app.core.errors import AppError

    app = FastAPI()

    @app.exception_handler(AppError)
    async def _app_error(_request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    app.include_router(system_module.router)
    app.dependency_overrides[get_db_session] = _db
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[tenant_from_principal] = lambda: principal.tenant_id
    app.dependency_overrides[require_permission(PERM_AUDIT_READ)] = lambda: principal
    return TestClient(app)


def test_audit_list_forbidden_without_permission(seeded_engine):
    reader = _principal(perms=(PERM_CHAT_USE,), username="reader")
    client = _client(seeded_engine, reader)
    # Override with a dependency that raises 403 like require_permission would.
    from app.core.errors import AppError

    def _deny():
        raise AppError("缺少所需权限", status_code=403)

    app = client.app
    app.dependency_overrides[require_permission(PERM_AUDIT_READ)] = _deny
    response = client.get("/api/v1/audit/events")
    assert response.status_code == 403


def test_audit_list_filters_tenant_and_action(seeded_engine):
    auditor = _principal(perms=(PERM_AUDIT_READ, PERM_CHAT_USE))
    client = _client(seeded_engine, auditor)
    response = client.get("/api/v1/audit/events", params={"action": "auth.login", "limit": 10})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["action"] == "auth.login"
    assert body["items"][0]["actor"] == "admin"
    assert all(item["tenant_id"] == "autley" for item in body["items"])

    all_events = client.get("/api/v1/audit/events", params={"limit": 50})
    assert all_events.status_code == 200
    assert all_events.json()["total"] == 2
