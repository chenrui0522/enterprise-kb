"""Name/kind collision review and enriched summary."""

from __future__ import annotations

from dataclasses import asdict

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.db import Base
from app.core.errors import AppError
from app.identity.constants import PERM_STAFFING_READ, PERM_STAFFING_WRITE
from app.identity.principal import Principal
from app.models.identity import Project
from app.models.staffing import StaffingAttendanceFact, StaffingImportBatch
from app.staffing import service as staffing_service
from app.staffing.parse import KIND_CONTRACT, KIND_FORMAL, parse_daily_report
import app.models.entity  # noqa: F401
import app.models.identity  # noqa: F401
import app.models.staffing  # noqa: F401
from tests.test_staffing_parse import _build_sample_xlsx


def _principal(project_ids: tuple[str, ...] = ("proj2515",)) -> Principal:
    return Principal(
        user_id="u1",
        tenant_id="autley",
        username="liu",
        display_name="liu",
        site="taiyuan",
        clearance="general",
        permissions=(PERM_STAFFING_READ, PERM_STAFFING_WRITE),
        project_ids=project_ids,
    )


def _ack_all(warnings: list, collision: dict) -> dict:
    resolutions = {
        w["code"]: "acknowledged"
        for w in warnings
        if w.get("code") and w["code"] != "name_kind_collision"
    }
    resolutions["name_kind_collision"] = collision
    return resolutions


def test_parse_emits_name_kind_collision_for_wang() -> None:
    result = parse_daily_report(_build_sample_xlsx(), filename="2515项目日报.xlsx")
    collide = [
        w
        for w in result.warnings
        if w.code == "name_kind_collision" and w.detail.get("person_name") == "王亮"
    ]
    assert collide
    kinds = {r.person_kind for r in result.rows if r.person_name == "王亮"}
    assert kinds == {KIND_FORMAL, KIND_CONTRACT}


@pytest.mark.asyncio
async def test_confirm_requires_collision_resolution_and_split(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'c.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    principal = _principal()
    project_id = "proj2515"

    async with factory() as session:
        session.add(
            Project(
                id=project_id,
                tenant_id="autley",
                code="2515",
                name="2515",
                status="active",
            )
        )
        result = parse_daily_report(_build_sample_xlsx(), filename="2515项目日报.xlsx")
        warnings = [asdict(w) for w in result.warnings]
        rows = [asdict(r) for r in result.rows]
        session.add(
            StaffingImportBatch(
                id="b1",
                tenant_id="autley",
                project_id=project_id,
                status="needs_review",
                filename="2515项目日报.xlsx",
                storage_key="x",
                uploaded_by=principal.user_id,
                warnings=warnings,
                parse_result={"rows": rows, "warnings": warnings},
                resolved_warnings={},
                match_info={"status": "matched", "project_id": project_id},
            )
        )
        await session.commit()

        with pytest.raises(AppError):
            await staffing_service.confirm_batch(
                session, principal=principal, batch_id="b1"
            )

        await staffing_service.review_batch(
            session,
            principal=principal,
            batch_id="b1",
            resolutions=_ack_all(warnings, {"王亮": {"action": "split"}}),
        )
        confirmed = await staffing_service.confirm_batch(
            session, principal=principal, batch_id="b1"
        )
        assert confirmed.status == "confirmed"

        facts = (
            await session.execute(
                select(StaffingAttendanceFact).where(
                    StaffingAttendanceFact.batch_id == "b1",
                    StaffingAttendanceFact.person_name == "王亮",
                    StaffingAttendanceFact.status == "active",
                )
            )
        ).scalars().all()
        kinds = {f.person_kind for f in facts}
        assert KIND_FORMAL in kinds and KIND_CONTRACT in kinds

        summary = await staffing_service.project_summary(
            session, principal=principal, project_id=project_id
        )
        wang_rows = [p for p in summary["people"] if p["person_name"] == "王亮"]
        assert len(wang_rows) == 2
        assert summary["project_code"] == "2515"
        assert summary["person_day_total"] >= summary["person_count"]

        xlsx = await staffing_service.export_project_xlsx(
            session, principal=principal, project_id=project_id
        )
        assert xlsx[:2] == b"PK"

    await engine.dispose()


@pytest.mark.asyncio
async def test_project_summary_stints_and_export(tmp_path) -> None:
    """Gapped on-site dates yield multiple stints on summary + xlsx 汇总."""
    from datetime import date
    from io import BytesIO

    from openpyxl import load_workbook

    from app.models.entity import new_id

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'stints.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    principal = _principal()
    project_id = "proj2515"

    async with factory() as session:
        session.add(
            Project(
                id=project_id,
                tenant_id="autley",
                code="2515",
                name="2515",
                status="active",
            )
        )
        batch_id = "bstint"
        session.add(
            StaffingImportBatch(
                id=batch_id,
                tenant_id="autley",
                project_id=project_id,
                status="confirmed",
                filename="stints.xlsx",
                storage_key="x",
                uploaded_by=principal.user_id,
                warnings=[],
                parse_result={"rows": []},
                resolved_warnings={},
                match_info={"status": "matched"},
            )
        )
        for d in [
            date(2026, 1, 11),
            date(2026, 1, 12),
            date(2026, 1, 13),
            date(2026, 3, 9),
            date(2026, 3, 10),
            date(2026, 3, 11),
        ]:
            session.add(
                StaffingAttendanceFact(
                    id=new_id(),
                    tenant_id="autley",
                    project_id=project_id,
                    batch_id=batch_id,
                    work_date=d,
                    person_name="张三",
                    person_kind=KIND_FORMAL,
                    status="active",
                )
            )
        await session.commit()

        summary = await staffing_service.project_summary(
            session, principal=principal, project_id=project_id
        )
        person = next(p for p in summary["people"] if p["person_name"] == "张三")
        assert person["days_on_site"] == 6
        assert person["stint_count"] == 2
        assert person["stints"][0]["entry_date"] == "2026-01-11"
        assert person["stints"][0]["exit_date"] == "2026-01-13"
        assert person["stints"][1]["entry_date"] == "2026-03-09"
        assert person["stints"][1]["exit_date"] == "2026-03-11"

        from app.chat.tools.staffing_orchestrator import _summary_card

        card = _summary_card(summary)
        card_person = next(p for p in card["people"] if p["person_name"] == "张三")
        assert card_person["stint_count"] == 2
        assert len(card_person["stints"]) == 2

        xlsx = await staffing_service.export_project_xlsx(
            session, principal=principal, project_id=project_id
        )
        wb = load_workbook(BytesIO(xlsx))
        ws = wb["汇总"]
        headers = [c.value for c in next(ws.iter_rows(min_row=7, max_row=7))]
        assert "进场次数" in headers
        assert "在场摘要" in headers
        assert "第1段入" in headers
        assert "第1段天数" in headers
        assert "第2段出" in headers
        data_row = None
        for row in ws.iter_rows(min_row=8, values_only=True):
            if row and row[0] == "张三":
                data_row = row
                break
        assert data_row is not None
        assert data_row[headers.index("进场次数")] == 2
        assert "第1次" in str(data_row[headers.index("在场摘要")])
        assert data_row[headers.index("第1段入")] == "2026-01-11"
        assert data_row[headers.index("第2段出")] == "2026-03-11"

        ws_stint = wb["工期段"]
        stint_rows = list(ws_stint.iter_rows(min_row=2, values_only=True))
        assert len(stint_rows) == 2
        assert stint_rows[0][:5] == ("张三", "正式我司", 1, "2026-01-11", "2026-01-13")
        assert stint_rows[1][2:5] == (2, "2026-03-09", "2026-03-11")

    await engine.dispose()


@pytest.mark.asyncio
async def test_confirm_merge_keeps_one_kind(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'm.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    principal = _principal()
    project_id = "proj2515"

    async with factory() as session:
        session.add(
            Project(
                id=project_id,
                tenant_id="autley",
                code="2515",
                name="2515",
                status="active",
            )
        )
        result = parse_daily_report(_build_sample_xlsx(), filename="2515项目日报.xlsx")
        warnings = [asdict(w) for w in result.warnings]
        rows = [asdict(r) for r in result.rows]
        session.add(
            StaffingImportBatch(
                id="b2",
                tenant_id="autley",
                project_id=project_id,
                status="needs_review",
                filename="2515项目日报.xlsx",
                storage_key="x",
                uploaded_by=principal.user_id,
                warnings=warnings,
                parse_result={"rows": rows},
                resolved_warnings={},
                match_info={"status": "matched"},
            )
        )
        await session.commit()
        await staffing_service.review_batch(
            session,
            principal=principal,
            batch_id="b2",
            resolutions=_ack_all(
                warnings, {"王亮": {"action": "merge", "keep_kind": KIND_FORMAL}}
            ),
        )
        await staffing_service.confirm_batch(
            session, principal=principal, batch_id="b2"
        )
        facts = (
            await session.execute(
                select(StaffingAttendanceFact).where(
                    StaffingAttendanceFact.batch_id == "b2",
                    StaffingAttendanceFact.person_name == "王亮",
                    StaffingAttendanceFact.status == "active",
                )
            )
        ).scalars().all()
        assert facts
        assert all(f.person_kind == KIND_FORMAL for f in facts)

    await engine.dispose()
