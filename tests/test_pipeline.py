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