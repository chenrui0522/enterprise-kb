from types import SimpleNamespace

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import AppError, UpstreamError
from app.ingestion.converters import ConversionResult
from app.ingestion.mineru import MinerUConverter
from app.ingestion.pipeline import IngestionPipeline


def _settings(mineru_url: str = "http://mineru.test", **overrides) -> Settings:
    values = {
        "mineru_url": mineru_url,
        "mineru_timeout_seconds": 5,
        "mineru_poll_interval": 0.01,
    }
    values.update(overrides)
    return Settings(**values)


class FakeMineruServer:
    """In-memory mineru-api stub with a canned status/result lifecycle."""

    def __init__(
        self,
        *,
        status_payload: dict | None = None,
        result_payload: dict | None = None,
        submit_payload: dict | None = None,
    ) -> None:
        self.status_payload = status_payload or {
            "task_id": "task-1",
            "status": "completed",
            "file_names": ["scan.pdf"],
        }
        self.result_payload = result_payload or {
            "backend": "pipeline",
            "version": "3.4",
            "results": {
                "scan.pdf": {
                    "md_content": "# 扫描件标题\n\n这是从扫描件识别出的正文内容。"
                }
            },
        }
        self.submit_payload = submit_payload or {
            "task_id": "task-1",
            "status": "pending",
        }
        self.posts: list[dict] = []
        self.gets: list[str] = []

    async def post(self, url: str, **kwargs) -> httpx.Response:
        self.posts.append({"url": url, "kwargs": kwargs})
        if url == "/tasks":
            return httpx.Response(202, json=self.submit_payload)
        return httpx.Response(404)

    async def get(self, url: str) -> httpx.Response:
        self.gets.append(url)
        if url == "/health":
            return httpx.Response(200, json={"status": "healthy"})
        if url.endswith("/result"):
            return httpx.Response(200, json=self.result_payload)
        return httpx.Response(200, json=self.status_payload)


class FakeAsyncClient:
    def __init__(self, server: FakeMineruServer, **kwargs) -> None:
        self.server = server

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def post(self, url: str, **kwargs) -> httpx.Response:
        return await self.server.post(url, **kwargs)

    async def get(self, url: str) -> httpx.Response:
        return await self.server.get(url)


@pytest.mark.asyncio
async def test_mineru_converter_parses_task_result(tmp_path, monkeypatch) -> None:
    server = FakeMineruServer()

    def factory(*args, **kwargs):
        return FakeAsyncClient(server, **kwargs)

    monkeypatch.setattr("app.ingestion.mineru.httpx.AsyncClient", factory)

    source = tmp_path / "scan.pdf"
    source.write_bytes(b"%PDF-fake-content")
    result = await MinerUConverter(_settings()).convert_async(str(source))

    assert "从扫描件识别出的正文内容" in result.markdown
    assert server.posts[0]["url"] == "/tasks"
    sent = server.posts[0]["kwargs"]
    assert sent["data"]["return_md"] == "true"
    assert sent["data"]["backend"] == "pipeline"
    uploaded = [inner for field, inner in sent["files"] if isinstance(inner, tuple)]
    assert any(parts[0] == "scan.pdf" for parts in uploaded)


@pytest.mark.asyncio
async def test_mineru_converter_supports_legacy_payload(tmp_path, monkeypatch) -> None:
    server = FakeMineruServer(
        result_payload={
            "code": 200,
            "msg": "success",
            "data": {
                "batch_result_list": [
                    {"pdf_info": [], "md_content": "## 旧版接口正文\n\n兼容 MinerU 2.x 结果格式。"}
                ]
            },
        }
    )

    def factory(*args, **kwargs):
        return FakeAsyncClient(server, **kwargs)

    monkeypatch.setattr("app.ingestion.mineru.httpx.AsyncClient", factory)
    source = tmp_path / "legacy.pdf"
    source.write_bytes(b"%PDF-fake")
    result = await MinerUConverter(_settings()).convert_async(str(source))
    assert "兼容 MinerU 2.x 结果格式" in result.markdown


@pytest.mark.asyncio
async def test_mineru_converter_fails_on_task_error(tmp_path, monkeypatch) -> None:
    server = FakeMineruServer(
        status_payload={"task_id": "task-1", "status": "failed", "error": "OCR boom"}
    )

    def factory(*args, **kwargs):
        return FakeAsyncClient(server, **kwargs)

    monkeypatch.setattr("app.ingestion.mineru.httpx.AsyncClient", factory)
    source = tmp_path / "bad.pdf"
    source.write_bytes(b"%PDF-fake")
    with pytest.raises(UpstreamError, match="OCR boom"):
        await MinerUConverter(_settings()).convert_async(str(source))


@pytest.mark.asyncio
async def test_mineru_converter_requires_config(tmp_path) -> None:
    source = tmp_path / "img.png"
    source.write_bytes(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(AppError, match="KB_MINERU_URL"):
        await MinerUConverter(_settings(mineru_url="")).convert_async(str(source))


def test_plan_converters_routes_images_and_pdf(tmp_path) -> None:
    pipeline = IngestionPipeline(
        store=object(),
        embedder=object(),
        storage=object(),
        settings=_settings(),
    )
    image = pipeline._plan_converters("手册.png", "auto", _settings())
    assert image[0][0] == "ocr"
    assert len(image) == 1

    pdf = pipeline._plan_converters("manual.pdf", "auto", _settings())
    assert [label for label, _ in pdf] == ["text", "ocr"]

    with pytest.raises(AppError, match="MinerU"):
        pipeline._plan_converters("手册.png", "auto", _settings(mineru_url=""))

    forced = pipeline._plan_converters("manual.pdf", "ocr", _settings())
    assert forced[0][0] == "ocr"


@pytest.mark.asyncio
async def test_pipeline_falls_back_to_ocr_for_scanned_pdf(tmp_path, monkeypatch) -> None:
    import fitz

    from app.ingestion.mineru import MinerUConverter

    pdf_path = tmp_path / "scanned.pdf"
    document = fitz.open()
    document.new_page()  # image-only page: no extractable text
    document.save(pdf_path)
    document.close()

    async def fake_ocr(self, file_path):
        return ConversionResult(markdown="# OCR 标题\n\n扫描件识别出的内容。", page_count=None)

    monkeypatch.setattr(MinerUConverter, "convert_async", fake_ocr)
    pipeline = IngestionPipeline(
        store=object(),
        embedder=object(),
        storage=object(),
        settings=_settings(),
    )
    document_obj = SimpleNamespace(filename="scanned.pdf")
    version_obj = SimpleNamespace(parse_mode="auto")
    result = await pipeline._convert_to_markdown(document_obj, version_obj, pdf_path)
    assert "扫描件识别出的内容" in result.markdown
