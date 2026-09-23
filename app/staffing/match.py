"""Match staffing import to authorized projects."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Project


@dataclass
class ProjectMatch:
    status: str  # matched | unmatched | ambiguous
    project_id: str | None
    candidates: list[dict]
    codes_tried: list[str]


async def match_project(
    session: AsyncSession,
    tenant_id: str,
    authorized_project_ids: tuple[str, ...],
    codes: list[str],
) -> ProjectMatch:
    if not authorized_project_ids:
        return ProjectMatch(
            status="unmatched",
            project_id=None,
            candidates=[],
            codes_tried=codes,
        )

    rows = (
        await session.execute(
            select(Project).where(
                Project.tenant_id == tenant_id,
                Project.id.in_(list(authorized_project_ids)),
                Project.status == "active",
            )
        )
    ).scalars().all()

    hits: list[Project] = []
    for code in codes:
        for p in rows:
            if p.code == code or p.code.startswith(code) or code.startswith(p.code):
                if p not in hits:
                    hits.append(p)

    candidates = [{"id": p.id, "code": p.code, "name": p.name} for p in hits]
    if len(hits) == 1:
        return ProjectMatch(
            status="matched",
            project_id=hits[0].id,
            candidates=candidates,
            codes_tried=codes,
        )
    if len(hits) == 0:
        return ProjectMatch(
            status="unmatched",
            project_id=None,
            candidates=[],
            codes_tried=codes,
        )
    return ProjectMatch(
        status="ambiguous",
        project_id=None,
        candidates=candidates,
        codes_tried=codes,
    )


def match_to_dict(m: ProjectMatch) -> dict:
    return asdict(m)
