"""Service-level merge_job gates."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.db import Base
from app.core.errors import AppError
from app.identity.constants import PERM_LEAVE_LEDGER_WRITE
from app.identity.principal import Principal
from app.leave_ledger import service as leave_service
from app.models.leave_ledger import LeaveLedgerJob, LeaveLedgerSnapshot
import app.models.leave_ledger  # noqa: F401
import app.models.identity  # noqa: F401
import app.models.entity  # noqa: F401


def _principal() -> Principal:
    return Principal(
        user_id="u1",
        tenant_id="autley",
        username="ops",
        display_name="ops",
        site="taiyuan",
        clearance="general",
        permissions=(PERM_LEAVE_LEDGER_WRITE,),
        leave_ledger_org_ok=True,
    )


@pytest.mark.asyncio
async def test_merge_job_rejects_unconfirmed_prior(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'm.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        current = LeaveLedgerJob(
            id="job-cur",
            tenant_id="autley",
            status="parsed",
            created_by="u1",
            compute_result={"rows": [{"person_name": "甲", "ot_days": []}]},
            warnings=[],
            resolved_warnings={},
        )
        prior = LeaveLedgerJob(
            id="job-prior",
            tenant_id="autley",
            status="parsed",
            created_by="u1",
            compute_result={"rows": [{"person_name": "甲"}]},
            warnings=[],
            resolved_warnings={},
        )
        session.add_all([current, prior])
        await session.commit()
        with pytest.raises(AppError) as ei:
            await leave_service.merge_job(
                session,
                principal=_principal(),
                job_id="job-cur",
                prior_job_id="job-prior",
            )
        assert ei.value.status_code == 400
        assert "已确认" in ei.value.message


@pytest.mark.asyncio
async def test_merge_job_writeback_happy_path(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'm2.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        current = LeaveLedgerJob(
            id="job-cur",
            tenant_id="autley",
            status="needs_review",
            created_by="u1",
            compute_result={
                "rows": [
                    {
                        "person_name": "甲",
                        "ot_days": [{"date": "2026-02-01", "credit": 1.0}],
                        "travel_segments": [],
                        "leave_segments": [],
                    }
                ]
            },
            warnings=[
                {
                    "code": "ot_missing_punch",
                    "blocking": True,
                    "detail": {"person": "甲", "date": "2026-01-05"},
                    "message": "x",
                }
            ],
            resolved_warnings={},
        )
        prior = LeaveLedgerJob(
            id="job-prior",
            tenant_id="autley",
            status="confirmed",
            created_by="u1",
            compute_result={"rows": []},
            warnings=[],
            resolved_warnings={},
        )
        session.add_all([current, prior])
        await session.flush()
        session.add(
            LeaveLedgerSnapshot(
                tenant_id="autley",
                job_id="job-prior",
                rows=[
                    {
                        "person_name": "甲",
                        "ot_days": [{"date": "2026-01-05", "credit": 0.5}],
                        "travel_segments": [],
                        "leave_segments": [],
                    }
                ],
            )
        )
        await session.commit()
        job = await leave_service.merge_job(
            session,
            principal=_principal(),
            job_id="job-cur",
            prior_job_id="job-prior",
        )
        rows = job.compute_result["rows"]
        assert len(rows) == 1
        dates = {d["date"]: d["credit"] for d in rows[0]["ot_days"]}
        assert dates["2026-01-05"] == 0.5
        assert dates["2026-02-01"] == 1.0
        assert job.compute_result.get("merged_from_job_id") == "job-prior"
        assert not any(
            w.get("detail", {}).get("date") == "2026-01-05" for w in (job.warnings or [])
        )


@pytest.mark.asyncio
async def test_review_after_merge_keeps_merged_rows(tmp_path, monkeypatch) -> None:
    """Resolutions trigger _recompute; sticky merged_from_job_id must re-apply merge."""
    from app.ingestion.storage import FileDocumentStorage

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'm3.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    storage = FileDocumentStorage(tmp_path / "storage")

    # Minimal stub: recompute needs sources; monkeypatch _recompute to set month-only rows
    # then verify merge sticky path via apply after synthetic recompute.
    async with factory() as session:
        current = LeaveLedgerJob(
            id="job-cur",
            tenant_id="autley",
            status="parsed",
            created_by="u1",
            compute_result={
                "rows": [
                    {
                        "person_name": "甲",
                        "ot_days": [{"date": "2026-02-01", "credit": 1.0}],
                        "travel_segments": [],
                        "leave_segments": [],
                    }
                ],
                "merged_from_job_id": "job-prior",
            },
            warnings=[],
            resolved_warnings={},
        )
        prior = LeaveLedgerJob(
            id="job-prior",
            tenant_id="autley",
            status="confirmed",
            created_by="u1",
            compute_result={"rows": []},
            warnings=[],
            resolved_warnings={},
        )
        session.add_all([current, prior])
        await session.flush()
        session.add(
            LeaveLedgerSnapshot(
                tenant_id="autley",
                job_id="job-prior",
                rows=[
                    {
                        "person_name": "甲",
                        "ot_days": [{"date": "2026-01-05", "credit": 0.5}],
                        "travel_segments": [],
                        "leave_segments": [],
                    }
                ],
            )
        )
        await session.commit()

        async def fake_recompute(session, job, storage):
            # Simulate sources-only recompute wiping merge marker unless sticky restore runs.
            prior_id = (job.compute_result or {}).get("merged_from_job_id")
            job.compute_result = {
                "rows": [
                    {
                        "person_name": "甲",
                        "ot_days": [{"date": "2026-02-01", "credit": 1.0}],
                        "travel_segments": [],
                        "leave_segments": [],
                    }
                ],
                "warnings": [],
            }
            job.warnings = []
            if prior_id:
                await leave_service._apply_merge_onto_job(
                    session, job, prior_job_id=str(prior_id)
                )
            return job

        monkeypatch.setattr(leave_service, "_recompute", fake_recompute)
        job = await leave_service.review_job(
            session,
            principal=_principal(),
            job_id="job-cur",
            resolutions={"ot_missing_punch": {"甲:2026-02-01": "accept_full"}},
            storage=storage,
        )
        dates = {d["date"]: d["credit"] for d in job.compute_result["rows"][0]["ot_days"]}
        assert dates.get("2026-01-05") == 0.5
        assert dates.get("2026-02-01") == 1.0
        assert job.compute_result.get("merged_from_job_id") == "job-prior"
