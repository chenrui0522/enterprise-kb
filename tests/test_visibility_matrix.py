"""Yuan/Ma visibility matrix without a live database."""

from __future__ import annotations

from app.identity.principal import Principal
from app.identity.visibility import build_visibility_expr, can_upload_to


def test_yuan_general_software_dept_visible_core_hidden() -> None:
    yuan = Principal(
        user_id="yuan",
        tenant_id="autley",
        username="yuan",
        display_name="袁工",
        site="suzhou",
        clearance="general",
        org_unit_ids=("software", "rd"),
        domains=("software",),
        project_ids=(),
        permissions=("documents:read", "chat:use"),
    )
    expr = build_visibility_expr(yuan)
    assert "software" in expr and "rd" in expr
    assert '"general"' in expr
    assert '"core"' not in expr  # general clearance → only general class in org path
    assert can_upload_to(yuan, org_unit_id="software", project_id=None, domain=None)
    assert not can_upload_to(yuan, org_unit_id="procurement", project_id=None, domain=None)


def test_yuan_project_software_core_visible_electrical_hidden() -> None:
    yuan = Principal(
        user_id="yuan",
        tenant_id="autley",
        username="yuan",
        display_name="袁工",
        site="suzhou",
        clearance="general",
        org_unit_ids=("software", "rd"),
        domains=("software",),
        project_ids=("P-DEMO",),
        permissions=("documents:read",),
    )
    expr = build_visibility_expr(yuan)
    assert "P-DEMO" in expr
    assert "software" in expr
    assert can_upload_to(yuan, org_unit_id=None, project_id="P-DEMO", domain="software")
    assert not can_upload_to(yuan, org_unit_id=None, project_id="P-DEMO", domain="electrical")


def test_ma_sales_project_slice_empty_domain_adds_nothing() -> None:
    ma = Principal(
        user_id="ma",
        tenant_id="autley",
        username="ma",
        display_name="马工",
        site="taiyuan",
        clearance="general",
        org_unit_ids=("gm_office", "sales"),
        domains=("sales",),  # empty-domain assistant contributes nothing
        project_ids=("P-DEMO",),
        permissions=("documents:read", "documents:write"),
    )
    expr = build_visibility_expr(ma)
    assert "gm_office" in expr and "sales" in expr
    assert "sales" in expr
    assert can_upload_to(ma, org_unit_id=None, project_id="P-DEMO", domain="sales")
    assert not can_upload_to(ma, org_unit_id=None, project_id="P-DEMO", domain="software")


def test_admin_without_org_scope_sees_nothing() -> None:
    admin = Principal(
        user_id="admin",
        tenant_id="autley",
        username="admin",
        display_name="admin",
        site="taiyuan",
        clearance="core",
        org_unit_ids=(),
        domains=(),
        project_ids=(),
        permissions=("users:manage", "orgs:manage", "documents:read"),
    )
    assert build_visibility_expr(admin) == 'id == "__none__"'
