"""Staffing project match and access helpers."""

from __future__ import annotations

import pytest

from app.core.errors import AppError
from app.identity.constants import PERM_STAFFING_READ, PERM_STAFFING_WRITE, ROLE_PERMISSIONS
from app.identity.principal import Principal
from app.staffing.match import ProjectMatch
from app.staffing.service import ensure_project_access


def test_staffing_perms_on_editor_and_reader() -> None:
    assert PERM_STAFFING_READ in ROLE_PERMISSIONS["editor"]
    assert PERM_STAFFING_WRITE in ROLE_PERMISSIONS["editor"]
    assert PERM_STAFFING_READ in ROLE_PERMISSIONS["reader"]
    assert PERM_STAFFING_WRITE not in ROLE_PERMISSIONS["reader"]


@pytest.mark.asyncio
async def test_ensure_project_access_denies_outsider() -> None:
    p = Principal(
        user_id="u1",
        tenant_id="t1",
        username="u",
        display_name="u",
        site="taiyuan",
        clearance="general",
        project_ids=("p-other",),
        permissions=(PERM_STAFFING_READ,),
    )
    with pytest.raises(AppError) as ei:
        await ensure_project_access(p, "p-target")
    assert ei.value.status_code == 403


@pytest.mark.asyncio
async def test_ensure_project_access_allows_member() -> None:
    p = Principal(
        user_id="u1",
        tenant_id="t1",
        username="u",
        display_name="u",
        site="taiyuan",
        clearance="general",
        project_ids=("p-target",),
        permissions=(PERM_STAFFING_READ,),
    )
    await ensure_project_access(p, "p-target")


def test_match_dataclass() -> None:
    m = ProjectMatch(status="unmatched", project_id=None, candidates=[], codes_tried=["2515"])
    assert m.status == "unmatched"
