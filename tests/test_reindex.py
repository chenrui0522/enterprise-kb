import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.db import Base
from app.ingestion.storage import FileDocumentStorage
from app.models.entity import Document, DocumentVersion
from app.reindex import collect_versions, format_summary


@pytest.mark.asyncio
async def test_collect_versions_marks_missing_originals(tmp_path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    storage = FileDocumentStorage(str(tmp_path / "docs"))
    async with session_factory() as session:
        document = Document(tenant_id="t1", title="差旅制度", filename="a.pdf")
        session.add(document)
        await session.flush()
        present = DocumentVersion(
            tenant_id="t1",
            doc_id=document.id,
            storage_key=storage.store(document.id, "v1", "a.pdf", b"%PDF-1.4"),
            doc_type="policy",
        )
        missing = DocumentVersion(tenant_id="t1", doc_id=document.id, storage_key="missing/ghost.pdf")
        session.add_all([present, missing])
        await session.commit()
        items = await collect_versions(session, storage)

    assert len(items) == 2
    assert [item.exists for item in items] == [True, False]
    assert items[0].doc_type == "policy"
    assert items[1].reason

    summary = format_summary({"dry_run": True, "items": items, "skipped": 1})
    assert "DRY-RUN" in summary
    assert "policy" in summary
    assert "SKIP" in summary


def test_format_summary_reports_per_version_results() -> None:
    summary = {
        "queued": 1,
        "skipped": 0,
        "skipped_items": [],
        "chunker_version": "structure-v1",
        "results": {
            "v1": {
                "status": "ready",
                "chunks": 12,
                "chunker_version": "structure-v1:policy",
                "error": "",
            }
        },
    }
    text = format_summary(summary)
    assert "queued=1" in text
    assert "ready" in text
    assert "structure-v1:policy" in text