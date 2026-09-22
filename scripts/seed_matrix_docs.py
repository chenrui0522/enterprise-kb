"""Insert labeled sample documents for live visibility checks."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.db import dispose_engine, get_session_factory
from app.models.entity import Document
from app.models.identity import OrgUnit, Project, ProjectMember, User


async def main() -> None:
    factory = get_session_factory()
    async with factory() as session:
        orgs = {
            row.code: row.id
            for row in (await session.execute(select(OrgUnit))).scalars().all()
        }
        project = (
            await session.execute(select(Project).where(Project.code == "P-DEMO"))
        ).scalar_one()
        yuan = (await session.execute(select(User).where(User.username == "yuan"))).scalar_one()
        ma = (await session.execute(select(User).where(User.username == "ma"))).scalar_one()

        for user in (yuan, ma):
            exists = (
                await session.execute(
                    select(ProjectMember).where(
                        ProjectMember.project_id == project.id,
                        ProjectMember.user_id == user.id,
                    )
                )
            ).scalar_one_or_none()
            if exists is None:
                session.add(ProjectMember(project_id=project.id, user_id=user.id))

        now = datetime.now(timezone.utc)
        samples = [
            ("sw-general", orgs["software"], None, None, "general"),
            ("sw-core", orgs["software"], None, None, "core"),
            ("rd-general", orgs["rd"], None, None, "general"),
            ("elec-general", orgs["elec_std_rd"], None, None, "general"),
            ("prod-general", orgs["production"], None, None, "general"),
            ("proc-general", orgs["procurement"], None, None, "general"),
            ("gm-general", orgs["gm_office"], None, None, "general"),
            ("sales-general", orgs["sales"], None, None, "general"),
            ("proj-sw-core", None, project.id, "software", "core"),
            ("proj-elec-core", None, project.id, "electrical", "core"),
            ("proj-sales", None, project.id, "sales", "general"),
        ]
        existing = {
            row.title
            for row in (
                await session.execute(select(Document).where(Document.tenant_id == "autley"))
            ).scalars().all()
        }
        for title, org_id, project_id, domain, classification in samples:
            if title in existing:
                continue
            session.add(
                Document(
                    tenant_id="autley",
                    title=title,
                    filename=f"{title}.pdf",
                    status="ready",
                    stage="ready",
                    org_unit_id=org_id,
                    project_id=project_id,
                    domain=domain,
                    classification=classification,
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.commit()
        print("sample docs ready")
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
