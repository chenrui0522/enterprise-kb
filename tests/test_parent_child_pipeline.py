from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.db import Base
from app.ingestion.pipeline import IngestionPipeline
from app.ingestion.storage import FileDocumentStorage
from app.models.entity import ChunkParent, Document, DocumentTable, DocumentVersion


class FakeStore:
    def __init__(self) -> None:
        self.inserted: list[list] = []
        self.deleted: list[str] = []

    def insert(self, chunks) -> int:
        self.inserted.append(list(chunks))
        return len(chunks)

    def delete_by_version(self, version_id: str) -> None:
        self.deleted.append(version_id)


class FakeEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3, 0.4]] * len(texts)


def _write_table_pdf(path) -> None:
    import fitz

    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Expense Policy", fontsize=20)
    page.insert_text(
        (72, 104),
        "The table below lists the reimbursement limits for every category.",
        fontsize=11,
    )
    left, top, col_w, row_h, cols, rows = 72, 140, 90, 20, 2, 3
    for index in range(rows + 1):
        y = top + index * row_h
        page.draw_line(fitz.Point(left, y), fitz.Point(left + cols * col_w, y))
    for index in range(cols + 1):
        x = left + index * col_w
        page.draw_line(fitz.Point(x, top), fitz.Point(x, top + rows * row_h))
    cells = [["Item", "Limit"], ["Hotel", "500"], ["Transport", "Actual"], ["Meal", "100"]]
    for row in range(rows):
        for column in range(cols):
            page.insert_text(
                fitz.Point(left + 6 + column * col_w, top + 14 + row * row_h),
                cells[row][column],
                fontsize=11,
            )
    document.save(path)
    document.close()


def _settings(directory, **overrides) -> Settings:
    values = {
        "mineru_url": "",
        "docling_url": "",
        "document_storage_dir": str(directory),
        "chunker_version": "structure-v2",
    }
    values.update(overrides)
    return Settings(**values)


async def _run_pipeline(tmp_path, settings, *, chunker_version: str, reindex: bool = False):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    pdf = tmp_path / "policy.pdf"
    _write_table_pdf(pdf)
    storage = FileDocumentStorage(settings.document_storage_dir)
    store = FakeStore()
    pipeline = IngestionPipeline(
        store=store, embedder=FakeEmbedder(), storage=storage, settings=settings
    )

    async with session_factory() as session:
        document = Document(tenant_id="t1", title="费用报销制度", filename="policy.pdf")
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
            "reindex": reindex,
        }
        await pipeline.process_job(
            session, job, chunk_size=300, overlap=30, chunker_version=chunker_version
        )
        await session.refresh(version)
        parents = (await session.execute(select(ChunkParent))).scalars().all()
        tables = (await session.execute(select(DocumentTable))).scalars().all()
        return session_factory, version, parents, tables, store, storage


@pytest.mark.asyncio
async def test_v2_pipeline_persists_parents_and_table_assets(tmp_path) -> None:
    settings = _settings(tmp_path / "docs")
    _factory, version, parents, tables, store, storage = await _run_pipeline(
        tmp_path, settings, chunker_version="structure-v2"
    )

    assert version.status == "ready"
    assert version.chunker_version.startswith("structure-v2")
    assert version.parent_count == len(parents) >= 1
    assert version.table_count == len(tables) == 1

    parent_ids = {parent.id for parent in parents}
    chunks = store.inserted[-1]
    child_chunks = [chunk for chunk in chunks if chunk.chunk_kind == "child"]
    assert child_chunks and all(chunk.parent_id in parent_ids for chunk in child_chunks)
    assert all(chunk.doc_type == "policy" for chunk in chunks)

    table_rows = [chunk for chunk in chunks if chunk.chunk_kind == "table_row"]
    summaries = [chunk for chunk in chunks if chunk.chunk_kind == "table_summary"]
    assert len(table_rows) >= 2
    assert [chunk.row_index for chunk in table_rows] == list(range(1, len(table_rows) + 1))
    assert len(summaries) == 1
    assert all(chunk.parent_id == "" for chunk in table_rows + summaries)
    # Parents never reach the vector store.
    assert parent_ids.isdisjoint({chunk.id for chunk in chunks})

    table = tables[0]
    assert table.row_count == len(table_rows)
    assert table.storage_key
    assert table.id == table_rows[0].table_id
    stored = storage.resolve(table.storage_key).read_text(encoding="utf-8")
    assert "Hotel" in stored


@pytest.mark.asyncio
async def test_v1_rollback_creates_no_parents_or_tables(tmp_path) -> None:
    settings = _settings(tmp_path / "docs", chunker_version="structure-v1")
    _factory, version, parents, tables, store, _storage = await _run_pipeline(
        tmp_path, settings, chunker_version="structure-v1"
    )
    assert parents == []
    assert tables == []
    assert version.parent_count == 0
    assert version.table_count == 0
    assert version.chunker_version.startswith("structure-v1")
    assert all(chunk.chunk_kind == "child" for chunk in store.inserted[-1])


@pytest.mark.asyncio
async def test_reindex_does_not_duplicate_parents_or_assets(tmp_path) -> None:
    settings = _settings(tmp_path / "docs")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    pdf = tmp_path / "policy.pdf"
    _write_table_pdf(pdf)
    storage = FileDocumentStorage(settings.document_storage_dir)
    store = FakeStore()
    pipeline = IngestionPipeline(
        store=store, embedder=FakeEmbedder(), storage=storage, settings=settings
    )

    async with session_factory() as session:
        document = Document(tenant_id="t1", title="费用报销制度", filename="policy.pdf")
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
        await pipeline.process_job(
            session, job, chunk_size=300, overlap=30, chunker_version="structure-v2"
        )
        first_parents = (await session.execute(select(ChunkParent))).scalars().all()
        await pipeline.process_job(
            session, job, chunk_size=300, overlap=30, chunker_version="structure-v2"
        )
        second_parents = (await session.execute(select(ChunkParent))).scalars().all()
        tables = (await session.execute(select(DocumentTable))).scalars().all()

    assert len(first_parents) == len(second_parents)
    assert len(tables) == 1
    assert store.deleted == [version.id, version.id]