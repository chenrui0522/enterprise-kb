from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.ingestion.cache import ParseCache
from app.ingestion.converters import PDFMarkdownConverter
from app.ingestion.pipeline import IngestionPipeline
from app.ingestion.storage import FileDocumentStorage


def _write_pdf(path, text: str) -> None:
    import fitz

    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text, fontsize=12)
    document.save(path)
    document.close()


def _settings(directory, **overrides) -> Settings:
    values = {"mineru_url": "", "docling_url": "", "document_storage_dir": str(directory)}
    values.update(overrides)
    return Settings(**values)


def _pipeline(tmp_path, settings, storage) -> IngestionPipeline:
    return IngestionPipeline(
        store=object(), embedder=object(), storage=storage, settings=settings
    )


@pytest.mark.asyncio
async def test_second_ingest_reuses_cached_parse(tmp_path, monkeypatch) -> None:
    pdf = tmp_path / "manual.pdf"
    _write_pdf(pdf, "Warranty for ZB-100 covers twelve months.")
    storage = FileDocumentStorage(str(tmp_path / "docs"))
    settings = _settings(tmp_path / "docs")
    pipeline = _pipeline(tmp_path, settings, storage)

    calls = {"count": 0}
    original = PDFMarkdownConverter.convert

    def counting_convert(self, file_path):
        calls["count"] += 1
        return original(self, file_path)

    monkeypatch.setattr(PDFMarkdownConverter, "convert", counting_convert)

    document = SimpleNamespace(filename="manual.pdf")
    version = SimpleNamespace(parse_mode="auto")

    first = await pipeline._convert_to_markdown(document, version, pdf)
    assert pipeline._last_conversion_meta["cache_hit"] is False
    second = await pipeline._convert_to_markdown(document, version, pdf)
    assert pipeline._last_conversion_meta["cache_hit"] is True

    assert calls["count"] == 1
    assert second.markdown == first.markdown
    assert len(second.structure.blocks) == len(first.structure.blocks)


@pytest.mark.asyncio
async def test_changed_file_content_misses_cache(tmp_path) -> None:
    storage = FileDocumentStorage(str(tmp_path / "docs"))
    settings = _settings(tmp_path / "docs")
    pipeline = _pipeline(tmp_path, settings, storage)
    document = SimpleNamespace(filename="manual.pdf")
    version = SimpleNamespace(parse_mode="auto")

    first_pdf = tmp_path / "first.pdf"
    _write_pdf(first_pdf, "First revision of the warranty policy.")
    await pipeline._convert_to_markdown(document, version, first_pdf)

    second_pdf = tmp_path / "second.pdf"
    _write_pdf(second_pdf, "Second revision of the warranty policy.")
    await pipeline._convert_to_markdown(document, version, second_pdf)
    assert pipeline._last_conversion_meta["cache_hit"] is False


def test_converter_upgrade_invalidates_cache_key(tmp_path) -> None:
    pdf = tmp_path / "manual.pdf"
    _write_pdf(pdf, "Warranty for ZB-100 covers twelve months.")
    cache = ParseCache(str(tmp_path / "cache"))
    digest = cache.file_digest(pdf)

    converter = PDFMarkdownConverter()
    original_key = cache.key_for(digest, converter)

    class UpgradedConverter(PDFMarkdownConverter):
        version = "2"

    upgraded_key = cache.key_for(digest, UpgradedConverter())
    assert original_key != upgraded_key

    toggled = PDFMarkdownConverter(extract_tables=False)
    assert cache.key_for(digest, toggled) != original_key
    assert cache.key_for(digest, PDFMarkdownConverter()) == original_key


def test_cache_round_trips_images_and_tables(tmp_path) -> None:
    from app.ingestion.converters import ConversionResult
    from app.ingestion.images import ImageAsset
    from app.ingestion.structure import BLOCK_TABLE, Block, DocumentStructure, TableArtifact

    cache = ParseCache(str(tmp_path / "cache"))
    result = ConversionResult(
        markdown="# 标题\n\n正文\n",
        page_count=3,
        structure=DocumentStructure(
            blocks=[Block(type=BLOCK_TABLE, header=["指标"], rows=[["完成率"]])]
        ),
        images=[ImageAsset(data=b"png-bytes", mime="image/png", page=2, heading_path="第一章")],
        tables=[TableArtifact(sheet="Sheet1", header=["a"], rows=[["1"]])],
        triage={"kind": "pdf_text"},
        ocr_pages=[2],
    )
    key = cache.signature_key("digest", {"converter": "t", "version": "1"})
    assert cache.save(key, result) is True

    loaded = cache.load(key)
    assert loaded is not None
    assert loaded.markdown == result.markdown
    assert loaded.page_count == 3
    assert loaded.images[0].data == b"png-bytes"
    assert loaded.images[0].heading_path == "第一章"
    assert loaded.tables[0].sheet == "Sheet1"
    assert loaded.ocr_pages == [2]
    assert loaded.structure is not None
    assert loaded.structure.blocks[0].header == ["指标"]


def test_cache_disabled_writes_nothing(tmp_path) -> None:
    cache = ParseCache(str(tmp_path / "cache"), enabled=False)
    assert cache.enabled is False
    from app.ingestion.converters import ConversionResult

    assert cache.save("key", ConversionResult(markdown="x")) is False
    assert cache.load("key") is None