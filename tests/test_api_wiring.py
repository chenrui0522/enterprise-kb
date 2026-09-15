"""App startup wiring: the lifespan must build every dependency it references.

Route-level tests build bare FastAPI apps, so a missing name inside `lifespan`
(import typo, renamed helper) would only show up when the real server boots.
This test runs the real lifespan with the external services stubbed.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.api.main as main_module


class _FakeMilvusStore:
    def __init__(self, settings) -> None:  # noqa: ARG002
        self.ensured = False

    def ensure_collection(self) -> None:
        self.ensured = True


class _FakeSaver:
    """Stands in for AsyncPostgresSaver: connecting always fails here, which is
    the degraded path CI actually runs in (no Postgres checkpointer)."""

    @classmethod
    def from_conn_string(cls, url: str):  # noqa: ARG003
        return _FailingSaverContext()


class _FailingSaverContext:
    async def __aenter__(self):
        raise RuntimeError("checkpointer unavailable in tests")

    async def __aexit__(self, *args) -> None:
        return None


@pytest.fixture
def stubbed_app(monkeypatch):
    async def _noop(*args, **kwargs) -> None:  # noqa: ARG001
        return None

    monkeypatch.setattr(main_module, "create_tables_if_needed", _noop)
    monkeypatch.setattr(main_module, "MilvusStore", _FakeMilvusStore)
    monkeypatch.setattr(main_module, "get_redis", lambda: object())
    monkeypatch.setattr(main_module, "close_redis", _noop)
    monkeypatch.setattr(main_module, "dispose_engine", _noop)
    monkeypatch.setattr(main_module, "build_llm", lambda settings: object())
    monkeypatch.setattr(main_module, "build_embedder", lambda settings: object())
    monkeypatch.setattr(main_module, "build_reranker", lambda settings: object())
    monkeypatch.setattr(
        "langgraph.checkpoint.postgres.aio.AsyncPostgresSaver", _FakeSaver, raising=False
    )
    return main_module.create_app()


def test_lifespan_starts_and_stops(stubbed_app) -> None:
    with TestClient(stubbed_app) as client:
        assert client.get("/healthz").status_code == 200
    # The graph must be wired even when the checkpointer falls back to
    # stateless mode - that is where the missing-import bug hid before.
    assert stubbed_app.state.chat_graph is not None
    assert stubbed_app.state.checkpointer is None
    assert stubbed_app.state.milvus_store.ensured is True


def test_openapi_builds(stubbed_app) -> None:
    schema = stubbed_app.openapi()
    assert "/api/v1/documents" in schema["paths"]
    assert "/api/v1/chat/stream" in schema["paths"]