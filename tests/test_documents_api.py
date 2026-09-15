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

def test_document_image_endpoint_serves_file(monkeypatch, tmp_path) -> None:
    import types

    from app.models.entity import DocumentImage

    storage_dir = tmp_path / "docs"
    image_rel = "d1/v1/images/abc.png"
    image_file = storage_dir / image_rel
    image_file.parent.mkdir(parents=True, exist_ok=True)
    image_file.write_bytes(b"\x89PNG\r\n\x1a\nfakepng")

    fake_image = types.SimpleNamespace(
        id="img1",
        tenant_id="t1",
        doc_id="d1",
        storage_key=image_rel,
        mime="image/png",
        caption="",
        page=1,
    )

    class ImageSession(FakeSession):
        async def get(self, model, ident):
            return fake_image if model is DocumentImage and ident == "img1" else None

    session = ImageSession()
    client = _client(monkeypatch, storage_dir, session)
    response = client.get("/api/v1/documents/d1/images/img1")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")

    from app.core.errors import NotFoundError

    fake_image.tenant_id = "other"
    with pytest.raises(NotFoundError):
        client.get("/api/v1/documents/d1/images/img1")


def test_conversion_report_endpoint(monkeypatch, tmp_path) -> None:
    import types

    from app.models.entity import Document

    document = types.SimpleNamespace(id="d1", tenant_id="t1")
    version = types.SimpleNamespace(
        id="v1",
        status="ready",
        stage="ready",
        doc_type="policy",
        parse_mode="auto",
        chunker_version="structure-v1:policy",
        chunk_count=12,
        error_message=None,
        conversion_report={
            "converter": "pdf-local",
            "converter_version": "1",
            "label": "text",
            "attempts": 1,
            "fallback_used": False,
            "cache_hit": False,
            "elapsed_ms": 42,
            "page_count": 3,
            "tables": 0,
            "images": 2,
            "triage": {"kind": "pdf_text"},
        },
    )

    class _Result:
        def scalar_one_or_none(self):
            return version

    class ReportSession(FakeSession):
        async def get(self, model, ident):  # noqa: ARG002
            return document if model is Document else None

        async def execute(self, statement):  # noqa: ARG002
            return _Result()

    client = _client(monkeypatch, tmp_path, ReportSession())
    response = client.get("/api/v1/documents/d1/conversion-report")
    assert response.status_code == 200
    payload = response.json()
    assert payload["version_id"] == "v1"
    assert payload["conversion_report"]["converter"] == "pdf-local"
    assert payload["conversion_report"]["triage"]["kind"] == "pdf_text"
    assert payload["chunk_count"] == 12


def test_conversion_report_missing_document(monkeypatch, tmp_path) -> None:
    from app.core.errors import NotFoundError

    class EmptySession(FakeSession):
        async def get(self, model, ident):  # noqa: ARG002
            return None

    client = _client(monkeypatch, tmp_path, EmptySession())
    with pytest.raises(NotFoundError):
        client.get("/api/v1/documents/d1/conversion-report")