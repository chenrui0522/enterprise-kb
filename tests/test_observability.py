from __future__ import annotations

import io
import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.logging import (
    ContextFilter,
    JsonFormatter,
    bind_context,
    clear_context,
    get_log_context,
    is_valid_request_id,
    log_event,
    logging_context,
    preview_text,
    setup_logging,
)
from app.core.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _reset_log_context():
    clear_context()
    get_settings.cache_clear()
    yield
    clear_context()
    get_settings.cache_clear()


def _capture_json_logs(logger_name: str = "test.observability"):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(ContextFilter())
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger(logger_name)
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger, stream


def test_json_log_includes_request_id_from_context():
    logger, stream = _capture_json_logs()
    with logging_context(request_id="req-abc", tenant_id="autley"):
        log_event(logger, "hello", event="unit.test", duration_ms=12)
    line = stream.getvalue().strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["msg"] == "hello"
    assert payload["event"] == "unit.test"
    assert payload["request_id"] == "req-abc"
    assert payload["tenant_id"] == "autley"
    assert payload["duration_ms"] == 12


def test_scrub_removes_password_and_cookie_from_fields():
    logger, stream = _capture_json_logs("test.scrub")
    log_event(
        logger,
        "login attempt",
        event="auth.probe",
        password="secret-password",
        cookie="session=abc",
        access_token="tok-xyz",
        window_tokens=250,
        username="alice",
    )
    payload = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert payload["password"] == "***"
    assert payload["cookie"] == "***"
    assert payload["access_token"] == "***"
    assert payload["window_tokens"] == 250
    assert payload["username"] == "alice"
    dumped = json.dumps(payload)
    assert "secret-password" not in dumped
    assert "session=abc" not in dumped
    assert "tok-xyz" not in dumped


def test_preview_text_truncates(monkeypatch):
    monkeypatch.setenv("KB_LOG_QUERY_PREVIEW_CHARS", "8")
    get_settings.cache_clear()
    text = "abcdefghijklmnop"
    preview = preview_text(text)
    assert preview.startswith("abcdefgh")
    assert "len=16" in preview
    assert "ijklmnop" not in preview.split("…")[0]


def test_request_id_middleware_generates_and_echoes():
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/ping")
    def ping():
        return {"request_id": get_log_context().get("request_id")}

    client = TestClient(app)
    response = client.get("/ping")
    assert response.status_code == 200
    rid = response.headers.get(REQUEST_ID_HEADER)
    assert rid
    assert is_valid_request_id(rid)
    assert response.json()["request_id"] == rid


def test_request_id_middleware_reuses_client_header():
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    client = TestClient(app)
    response = client.get("/ping", headers={REQUEST_ID_HEADER: "client-req-1"})
    assert response.headers.get(REQUEST_ID_HEADER) == "client-req-1"


def test_setup_logging_json_default(monkeypatch):
    monkeypatch.setenv("KB_LOG_JSON", "true")
    monkeypatch.setenv("KB_LOG_LEVEL", "INFO")
    get_settings.cache_clear()
    setup_logging()
    root = logging.getLogger()
    assert root.handlers
    assert isinstance(root.handlers[0].formatter, JsonFormatter)


def test_healthz_shape(monkeypatch):
    from app.api.routers import system as system_module

    async def _ok(_timeout: float) -> str:
        return "ok"

    async def _fail(_timeout: float) -> str:
        return "fail"

    monkeypatch.setattr(system_module, "_check_postgres", _ok)
    monkeypatch.setattr(system_module, "_check_redis", _ok)
    monkeypatch.setattr(system_module, "_check_milvus", _fail)
    monkeypatch.setattr(system_module, "_check_model_service", _ok)

    app = FastAPI()
    app.include_router(system_module.router)
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["milvus"] == "fail"
    assert body["checks"]["postgres"] == "ok"


@pytest.mark.asyncio
async def test_check_model_service_requires_launched_models(monkeypatch):
    from app.api.routers import system as system_module

    get_settings.cache_clear()
    settings = get_settings()

    class _Resp:
        def __init__(self, payload: dict):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._payload

    class _Client:
        def __init__(self, payload: dict):
            self._payload = payload

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, _url: str):
            return _Resp(self._payload)

    monkeypatch.setattr(
        system_module.httpx,
        "AsyncClient",
        lambda **_kwargs: _Client({"data": []}),
    )
    assert await system_module._check_model_service(2.0) == "fail"

    monkeypatch.setattr(
        system_module.httpx,
        "AsyncClient",
        lambda **_kwargs: _Client(
            {
                "data": [
                    {"id": settings.embedder_model},
                    {"id": settings.reranker_model},
                ]
            }
        ),
    )
    assert await system_module._check_model_service(2.0) == "ok"


def test_healthz_unavailable_when_postgres_down(monkeypatch):
    from app.api.routers import system as system_module

    async def _ok(_timeout: float) -> str:
        return "ok"

    async def _fail(_timeout: float) -> str:
        return "fail"

    monkeypatch.setattr(system_module, "_check_postgres", _fail)
    monkeypatch.setattr(system_module, "_check_redis", _ok)
    monkeypatch.setattr(system_module, "_check_milvus", _ok)
    monkeypatch.setattr(system_module, "_check_model_service", _ok)

    app = FastAPI()
    app.include_router(system_module.router)
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
