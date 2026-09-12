import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.routers.documents as documents_router
from app.api.routers.documents import router
from app.core.db import get_db_session
from app.core.tenant import tenant_dependency


class FakeSession:
    def __init__(self) -> None:
        self.added = []

    def add(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4().hex
        self.added.append(obj)

    async def flush(self) -> None:
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4().hex

    async def commit(self) -> None:
        return None


class FakeSettings:
    def __init__(self, directory: str) -> None:
        self.document_storage_dir = directory
        self.chunker_version = "structure-v1"
        self.mineru_enabled = False


def _client(monkeypatch, tmp_path, session: FakeSession) -> TestClient:
    async def _session_override():
        yield session

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(documents_router, "get_settings", lambda: FakeSettings(str(tmp_path)))
    monkeypatch.setattr(documents_router, "enqueue_job", _noop)
    monkeypatch.setattr(documents_router, "get_redis", lambda: object())
    monkeypatch.setattr(documents_router, "write_audit", _noop)

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_db_session] = _session_override
    app.dependency_overrides[tenant_dependency] = lambda: "t1"
    return TestClient(app)


def test_upload_accepts_valid_doc_type(monkeypatch, tmp_path) -> None:
    session = FakeSession()
    client = _client(monkeypatch, tmp_path, session)
    response = client.post(
        "/api/v1/documents?doc_type=policy",
        files={"file": ("policy.pdf", b"%PDF-1.4 test", "application/pdf")},
    )
    assert response.status_code == 202
    version = next(obj for obj in session.added if obj.__class__.__name__ == "DocumentVersion")
    assert version.doc_type == "policy"


def test_upload_rejects_unknown_doc_type(monkeypatch, tmp_path) -> None:
    session = FakeSession()
    client = _client(monkeypatch, tmp_path, session)
    response = client.post(
        "/api/v1/documents?doc_type=white-paper",
        files={"file": ("policy.pdf", b"%PDF-1.4 test", "application/pdf")},
    )
    assert response.status_code == 422
    assert not session.added