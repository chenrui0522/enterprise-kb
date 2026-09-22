from __future__ import annotations

from app.identity.constants import CLEARANCE_RANK, ROLE_PERMISSIONS
from app.identity.passwords import hash_password, verify_password
from app.identity.principal import Principal
from app.identity.visibility import build_visibility_expr, can_upload_to
from app.models.identity import OrgUnit, Position, User, UserPosition


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("secret-pass")
    assert hashed != "secret-pass"
    assert verify_password(hashed, "secret-pass")
    assert not verify_password(hashed, "wrong")


def test_role_permission_catalog() -> None:
    assert "documents:write" in ROLE_PERMISSIONS["editor"]
    assert "documents:write" not in ROLE_PERMISSIONS["reader"]
    assert "users:manage" in ROLE_PERMISSIONS["admin"]


def test_identity_model_tablename() -> None:
    assert User.__tablename__ == "users"
    assert UserPosition.__tablename__ == "user_positions"
    assert Position.__tablename__ == "positions"
    assert OrgUnit.__tablename__ == "org_units"
    assert Position.org_unit_id.property.columns[0].nullable is False


def test_principal_clearance_rank() -> None:
    p = Principal(
        user_id="u1",
        tenant_id="autley",
        username="yuan",
        display_name="袁工",
        site="suzhou",
        clearance="general",
        org_unit_ids=("software",),
        domains=("software",),
    )
    assert p.clearance_rank() == CLEARANCE_RANK["general"]
    assert p.has_permission("documents:read") is False


def test_visibility_expr_org_and_project() -> None:
    p = Principal(
        user_id="u1",
        tenant_id="autley",
        username="yuan",
        display_name="袁工",
        site="suzhou",
        clearance="general",
        org_unit_ids=("org-software", "org-rd"),
        domains=("software",),
        project_ids=("p1",),
        permissions=("documents:read",),
    )
    expr = build_visibility_expr(p)
    assert 'org_unit_id in ["org-rd", "org-software"]' in expr or 'org_unit_id in ["org-software", "org-rd"]' in expr
    assert '"general"' in expr
    assert "project_id in" in expr
    assert "software" in expr


def test_visibility_empty_scope_sees_nothing() -> None:
    p = Principal(
        user_id="admin",
        tenant_id="autley",
        username="admin",
        display_name="admin",
        site="taiyuan",
        clearance="core",
    )
    assert build_visibility_expr(p) == 'id == "__none__"'


def test_can_upload_rules() -> None:
    p = Principal(
        user_id="u1",
        tenant_id="autley",
        username="yuan",
        display_name="袁工",
        site="suzhou",
        clearance="general",
        org_unit_ids=("org-software",),
        domains=("software",),
        project_ids=("p1",),
        permissions=("documents:write",),
    )
    assert can_upload_to(p, org_unit_id="org-software", project_id=None, domain=None)
    assert not can_upload_to(p, org_unit_id="org-procurement", project_id=None, domain=None)
    assert can_upload_to(p, org_unit_id=None, project_id="p1", domain="software")
    assert not can_upload_to(p, org_unit_id=None, project_id="p1", domain="electrical")
