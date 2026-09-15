import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.db import Base
from app.ingestion.pipeline import IngestionPipeline
from app.ingestion.storage import FileDocumentStorage
from app.models.entity import Document, DocumentVersion
from app.retrieval.milvus_store import MilvusStore


class FakeStore:
    def __init__(self) -> None:
        self.inserted: list[list[dict]] = []
        self.deleted: list[str] = []

    def insert(self, chunks) -> int:
        self.inserted.append(chunks)
        return len(chunks)

    def delete_by_version(self, version_id: str) -> None:
        self.deleted.append(version_id)


class FakeEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3, 0.4]] * len(texts)


def _write_pdf(path, text: str) -> None:
    import fitz

    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text, fontsize=12)
    document.save(path)
    document.close()


@pytest.mark.asyncio
async def test_pipeline_indexes_and_marks_ready(tmp_path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    pdf = tmp_path / "manual.pdf"
    _write_pdf(str(pdf), "Warranty for product ZB-100 covers twelve months. Policy section one content here.")
    storage = FileDocumentStorage(str(tmp_path / "docs"))
    store = FakeStore()
    pipeline = IngestionPipeline(store=store, embedder=FakeEmbedder(), storage=storage)

    async with session_factory() as session:
        document = Document(tenant_id="t1", title="产品手册", filename="manual.pdf")
        session.add(document)
        await session.flush()
        version = DocumentVersion(
            tenant_id="t1", doc_id=document.id, storage_key=storage.store(document.id, "v1", "manual.pdf", pdf.read_bytes())
        )
        session.add(version)
        await session.commit()

        await pipeline.process_job(
            session,
            {"doc_id": document.id, "version_id": version.id, "tenant_id": "t1", "storage_key": version.storage_key},
            chunk_size=200,
            overlap=20,
        )

        await session.refresh(document)
        await session.refresh(version)
        assert document.status == "ready"
        assert document.current_version_id == version.id
        assert version.chunk_count > 0
        assert store.inserted and not store.deleted


@pytest.mark.asyncio
async def test_reupload_replaces_old_version_chunks(tmp_path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    pdf = tmp_path / "manual.pdf"
    _write_pdf(str(pdf), "ZB-100 product manual version two with new warranty policy content.")
    storage = FileDocumentStorage(str(docs_dir))
    store = FakeStore()
    pipeline = IngestionPipeline(store=store, embedder=FakeEmbedder(), storage=storage)

    async with session_factory() as session:
        document = Document(tenant_id="t1", title="产品手册", filename="manual.pdf")
        session.add(document)
        await session.flush()
        v1 = DocumentVersion(tenant_id="t1", doc_id=document.id, storage_key=storage.store(document.id, "v1", "manual.pdf", pdf.read_bytes()))
        session.add(v1)
        await session.commit()
        document.current_version_id = v1.id
        await session.commit()

        v2 = DocumentVersion(tenant_id="t1", doc_id=document.id, storage_key=storage.store(document.id, "v2", "manual.pdf", pdf.read_bytes()))
        session.add(v2)
        await session.commit()
        await pipeline.process_job(
            session,
            {"doc_id": document.id, "version_id": v2.id, "tenant_id": "t1", "storage_key": v2.storage_key},
            chunk_size=200,
            overlap=20,
        )
        await session.refresh(document)
        assert document.current_version_id == v2.id
        assert store.deleted == [v1.id]


@pytest.mark.asyncio
async def test_failed_document_does_not_affect_ready_state(tmp_path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    storage = FileDocumentStorage(str(tmp_path / "docs"))
    store = FakeStore()
    pipeline = IngestionPipeline(store=store, embedder=FakeEmbedder(), storage=storage)
    async with session_factory() as session:
        bad = Document(tenant_id="t1", title="坏文档", filename="broken.pdf")
        session.add(bad)
        await session.flush()
        version = DocumentVersion(tenant_id="t1", doc_id=bad.id, storage_key="missing/file.pdf")
        session.add(version)
        await session.commit()
        await pipeline.process_job(
            session,
            {"doc_id": bad.id, "version_id": version.id, "tenant_id": "t1", "storage_key": version.storage_key},
            chunk_size=200,
            overlap=20,
        )
        await session.refresh(bad)
        assert bad.status == "failed"
        assert bad.error_message


@pytest.mark.asyncio
async def test_reindex_job_is_idempotent_and_records_chunker_version(tmp_path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    pdf = tmp_path / "policy.pdf"
    _write_pdf(str(pdf), "Policy content about travel approval and reimbursement limits.")
    storage = FileDocumentStorage(str(tmp_path / "docs"))
    store = FakeStore()
    pipeline = IngestionPipeline(store=store, embedder=FakeEmbedder(), storage=storage)

    async with session_factory() as session:
        document = Document(tenant_id="t1", title="差旅制度", filename="policy.pdf")
        session.add(document)
        await session.flush()
        version = DocumentVersion(
            tenant_id="t1",
            doc_id=document.id,
            storage_key=storage.store(document.id, "v1", "policy.pdf", pdf.read_bytes()),
            doc_type="policy",
        )
        session.add(version)
        await session.commit()

        job = {
            "doc_id": document.id,
            "version_id": version.id,
            "tenant_id": "t1",
            "storage_key": version.storage_key,
            "doc_type": "policy",
            "reindex": True,
        }
        await pipeline.process_job(session, job, chunk_size=200, overlap=20)
        first_count = len(store.inserted[0])
        await pipeline.process_job(session, job, chunk_size=200, overlap=20)
        second_count = len(store.inserted[1])

        assert first_count == second_count > 0
        assert store.deleted == [version.id, version.id]
        await session.refresh(version)
        assert version.doc_type == "policy"
        assert version.chunker_version == "structure-v1:policy"

@pytest.mark.asyncio
async def test_pipeline_extracts_and_indexes_images(tmp_path) -> None:
    import io

    import fitz as fitz_module

    from PIL import Image
    from sqlalchemy import select

    from app.models.entity import DocumentImage

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    buffer = io.BytesIO()
    Image.frombytes("RGB", (200, 200), __import__("os").urandom(200 * 200 * 3)).save(buffer, format="PNG")
    figure = tmp_path / "figure.png"
    figure.write_bytes(buffer.getvalue())

    pdf = tmp_path / "with_image.pdf"
    document_pdf = fitz_module.open()
    page = document_pdf.new_page()
    page.insert_text((72, 72), "架构说明", fontsize=12)
    page.insert_image(fitz_module.Rect(72, 100, 372, 400), filename=str(figure))
    document_pdf.save(str(pdf))
    document_pdf.close()

    storage = FileDocumentStorage(str(tmp_path / "docs"))
    store = FakeStore()
    pipeline = IngestionPipeline(store=store, embedder=FakeEmbedder(), storage=storage)

    async with session_factory() as session:
        document = Document(tenant_id="t1", title="含图手册", filename="with_image.pdf")
        session.add(document)
        await session.flush()
        version = DocumentVersion(
            tenant_id="t1",
            doc_id=document.id,
            storage_key=storage.store(document.id, "v1", "with_image.pdf", pdf.read_bytes()),
            doc_type="generic",
        )
        session.add(version)
        await session.commit()

        job = {
            "doc_id": document.id,
            "version_id": version.id,
            "tenant_id": "t1",
            "storage_key": version.storage_key,
            "doc_type": "generic",
        }
        await pipeline.process_job(session, job, chunk_size=400, overlap=40)
        await session.refresh(version)
        assert version.status == "ready"

        images = (
            await session.execute(select(DocumentImage).where(DocumentImage.version_id == version.id))
        ).scalars().all()
        assert len(images) == 1
        chunks = store.inserted[0]
        assert any(chunk.chunk_type == "image" and chunk.image_id == images[0].id for chunk in chunks)

        stored = list((tmp_path / "docs" / document.id / version.id / "images").glob("*"))
        assert stored

        job["reindex"] = True
        await pipeline.process_job(session, job, chunk_size=400, overlap=40)
        images_after = (
            await session.execute(select(DocumentImage).where(DocumentImage.version_id == version.id))
        ).scalars().all()
        assert len(images_after) == 1
        stored_after = list((tmp_path / "docs" / document.id / version.id / "images").glob("*"))
        assert stored_after

@pytest.mark.asyncio
async def test_pipeline_warns_when_image_extraction_fails(tmp_path, monkeypatch) -> None:
    import app.ingestion.pipeline as pipeline_module

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    pdf = tmp_path / "plain.pdf"
    _write_pdf(str(pdf), "Plain text without images at all.")

    def _boom(*args, **kwargs):
        raise RuntimeError("extractor unavailable")

    monkeypatch.setattr(pipeline_module, "extract_images_local", _boom)

    storage = FileDocumentStorage(str(tmp_path / "docs"))
    pipeline = IngestionPipeline(store=FakeStore(), embedder=FakeEmbedder(), storage=storage)
    async with session_factory() as session:
        document = Document(tenant_id="t1", title="纯文本", filename="plain.pdf")
        session.add(document)
        await session.flush()
        version = DocumentVersion(
            tenant_id="t1",
            doc_id=document.id,
            storage_key=storage.store(document.id, "v1", "plain.pdf", pdf.read_bytes()),
            doc_type="generic",
        )
        session.add(version)
        await session.commit()
        await pipeline.process_job(
            session,
            {"doc_id": document.id, "version_id": version.id, "tenant_id": "t1", "storage_key": version.storage_key},
            chunk_size=300,
            overlap=30,
        )
        await session.refresh(version)
        assert version.status == "ready"
        assert (version.error_message or "").startswith("warning:")

@pytest.mark.asyncio
async def test_pipeline_records_conversion_report(tmp_path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    pdf = tmp_path / "report.pdf"
    _write_pdf(str(pdf), "Conversion report smoke content for ZB-100.")

    storage = FileDocumentStorage(str(tmp_path / "docs"))
    pipeline = IngestionPipeline(store=FakeStore(), embedder=FakeEmbedder(), storage=storage)

    async with session_factory() as session:
        document = Document(tenant_id="t1", title="报告样例", filename="report.pdf")
        session.add(document)
        await session.flush()
        version = DocumentVersion(
            tenant_id="t1",
            doc_id=document.id,
            storage_key=storage.store(document.id, "v1", "report.pdf", pdf.read_bytes()),
            doc_type="generic",
        )
        session.add(version)
        await session.commit()

        await pipeline.process_job(
            session,
            {"doc_id": document.id, "version_id": version.id, "tenant_id": "t1", "storage_key": version.storage_key},
            chunk_size=300,
            overlap=30,
        )
        await session.refresh(version)
        report = version.conversion_report
        assert report and report["converter"]
        assert report["attempts"] >= 1
        assert report["markdown_chars"] > 0
        assert "elapsed_ms" in report
        # Report contract: converter identity, triage evidence and counts are
        # all queryable from the document version.
        assert report["converter_version"]
        assert report["label"] in {"text", "ocr", "docling", "hybrid", "xlsx"}
        assert report["cache_hit"] is False
        assert report["page_count"] == 1
        assert report["tables"] == 0
        assert report["images"] == 0
        assert report["plan"][0] == report["label"]
        assert report["triage"]["kind"] == "pdf_text"
        assert report["failed"] == []
        assert report["table_files"] == []