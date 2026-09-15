from types import SimpleNamespace

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.ingestion.docling import (
    DoclingConverter,
    docling_available,
    map_docling_payload,
    reset_availability_cache,
)
from app.ingestion.pipeline import IngestionPipeline
from app.ingestion.storage import FileDocumentStorage
from app.ingestion.triage import triage_file


class FakeDoclingServer:
    def __init__(self, *, health_status: int = 200, convert_status: int = 200, payload=None) -> None:
        self.health_status = health_status
        self.convert_status = convert_status
        self.payload = payload if payload is not None else {"markdown": "# Docling 标题\n\nDocling 返回的正文。"}
        self.posts: list[dict] = []

    async def get(self, url: str, **kwargs) -> httpx.Response:  # noqa: ARG002
        if url == "/health":
            return httpx.Response(self.health_status, json={"status": "ok"})
        return httpx.Response(404)

    async def post(self, url: str, **kwargs) -> httpx.Response:
        self.posts.append({"url": url, "kwargs": kwargs})
        return httpx.Response(self.convert_status, json=self.payload)


class FakeAsyncClient:
    def __init__(self, server: FakeDoclingServer, **kwargs) -> None:
        self.server = server

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def get(self, url: str, **kwargs) -> httpx.Response:
        return await self.server.get(url, **kwargs)

    async def post(self, url: str, **kwargs) -> httpx.Response:
        return await self.server.post(url, **kwargs)


def _patch_client(monkeypatch, server: FakeDoclingServer) -> None:
    monkeypatch.setattr(
        "app.ingestion.docling.httpx.AsyncClient",
        lambda *args, **kwargs: FakeAsyncClient(server, **kwargs),
    )


def _settings(**overrides) -> Settings:
    values = {"mineru_url": "", "docling_url": "http://docling.test"}
    values.update(overrides)
    reset_availability_cache()
    return Settings(**values)


def _write_pdf(path, text: str) -> None:
    import fitz

    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text, fontsize=12)
    document.save(path)
    document.close()


@pytest.fixture(autouse=True)
def _clear_availability() -> None:
    reset_availability_cache()


def test_map_docling_payload_uses_markdown_when_no_blocks() -> None:
    result = map_docling_payload({"markdown": "# 保修政策\n\n打印机保修十二个月。", "page_count": 2})
    assert result.page_count == 2
    assert result.structure is not None
    assert [block.type for block in result.structure.blocks] == ["heading", "paragraph"]


def test_map_docling_payload_maps_typed_blocks() -> None:
    result = map_docling_payload(
        {
            "blocks": [
                {"type": "heading", "text": "第一章", "level": 1, "page": 1},
                {"type": "paragraph", "text": "正文内容", "page": 1},
                {"type": "table", "header": ["指标", "权重"], "rows": [["完成率", "40%"]]},
                {"type": "unknown", "text": "兜底段落"},
            ]
        }
    )
    assert result.structure is not None
    types = [block.type for block in result.structure.blocks]
    assert types == ["heading", "paragraph", "table", "paragraph"]
    table = result.structure.blocks[2]
    assert table.header == ["指标", "权重"]
    assert "第一章" in result.markdown


@pytest.mark.asyncio
async def test_docling_converter_posts_file(tmp_path, monkeypatch) -> None:
    server = FakeDoclingServer()
    _patch_client(monkeypatch, server)
    pdf = tmp_path / "manual.pdf"
    _write_pdf(pdf, "Warranty content")

    result = await DoclingConverter(_settings()).convert_async(str(pdf))
    assert "Docling 返回的正文" in result.markdown
    assert server.posts[0]["url"] == "/convert"
    assert server.posts[0]["kwargs"]["data"]["to_formats"] == "md"


@pytest.mark.asyncio
async def test_docling_service_unavailable_raises_skippable_error(tmp_path, monkeypatch) -> None:
    server = FakeDoclingServer(health_status=503)
    _patch_client(monkeypatch, server)
    pdf = tmp_path / "manual.pdf"
    _write_pdf(pdf, "Warranty content")
    with pytest.raises(AppError) as excinfo:
        await DoclingConverter(_settings()).convert_async(str(pdf))
    assert excinfo.value.status_code == 503


@pytest.mark.asyncio
async def test_docling_health_probe_caches_result(monkeypatch) -> None:
    settings = _settings(docling_url="")
    assert await docling_available(settings) is False

    healthy = _settings()
    server = FakeDoclingServer()
    _patch_client(monkeypatch, server)
    assert await docling_available(healthy) is True
    monkeypatch.setattr(
        "app.ingestion.docling.httpx.AsyncClient",
        lambda *args, **kwargs: FakeAsyncClient(FakeDoclingServer(health_status=503), **kwargs),
    )
    # Still cached for a few seconds, so a burst of uploads does not re-probe.
    assert await docling_available(healthy) is True
    assert await docling_available(healthy, force=True) is False


@pytest.mark.asyncio
async def test_pipeline_skips_docling_when_service_fails(tmp_path, monkeypatch) -> None:
    server = FakeDoclingServer(health_status=500)
    _patch_client(monkeypatch, server)

    async def always_candidate(settings, *, force: bool = False) -> bool:  # noqa: ARG001
        return True

    monkeypatch.setattr("app.ingestion.pipeline.docling_available", always_candidate)

    pdf = tmp_path / "manual.pdf"
    _write_pdf(pdf, "Local text layer content for the manual.")
    storage = FileDocumentStorage(str(tmp_path / "docs"))
    pipeline = IngestionPipeline(
        store=object(), embedder=object(), storage=storage, settings=_settings()
    )
    document = SimpleNamespace(filename="manual.pdf")
    version = SimpleNamespace(parse_mode="auto")
    result = await pipeline._convert_to_markdown(document, version, pdf)

    assert "Local text layer content" in result.markdown
    assert pipeline._last_conversion_meta["label"] == "text"
    assert pipeline._last_conversion_meta["fallback_used"] is True
    assert pipeline._last_failures[0]["label"] == "docling"
    assert pipeline._last_plan == ["docling", "text"]


@pytest.mark.asyncio
async def test_pipeline_uses_docling_when_available(tmp_path, monkeypatch) -> None:
    server = FakeDoclingServer()
    _patch_client(monkeypatch, server)

    async def always_candidate(settings, *, force: bool = False) -> bool:  # noqa: ARG001
        return True

    monkeypatch.setattr("app.ingestion.pipeline.docling_available", always_candidate)

    pdf = tmp_path / "manual.pdf"
    _write_pdf(pdf, "Local text layer content for the manual.")
    storage = FileDocumentStorage(str(tmp_path / "docs"))
    pipeline = IngestionPipeline(
        store=object(), embedder=object(), storage=storage, settings=_settings()
    )
    document = SimpleNamespace(filename="manual.pdf")
    version = SimpleNamespace(parse_mode="auto")
    triage = triage_file(pdf, "manual.pdf")
    assert triage.scanned_pages == []

    result = await pipeline._convert_to_markdown(document, version, pdf)
    assert "Docling 返回的正文" in result.markdown
    assert pipeline._last_conversion_meta["label"] == "docling"
    assert pipeline._last_conversion_meta["fallback_used"] is False