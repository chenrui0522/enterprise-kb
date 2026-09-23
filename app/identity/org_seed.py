"""Declarative Autley org tree seed (WeCom address-book fidelity).

☆太原/朔州/苏州公司 are site labels only — not seeded as org_units.
Leaves confirmed with no children: 太原销售部; 综合管理部/生产部/质检部;
电气标准化研发部; 计划运营部/人力资源管理部/行政部/朔州人事行政.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entity import new_id
from app.models.identity import OrgUnit

# (type, code, name, parent_code, default_site)
# Parents must appear before children. Codes are stable across re-seeds.
ORG_SEED_NODES: list[tuple[str, str, str, str | None, str | None]] = [
    ("company", "autley", "奥特莱物流科技有限公司", None, None),
    # L2 — office / centers / Thailand
    ("office", "gm_office", "总经理办", "autley", None),
    ("center", "strategy", "战略发展中心", "autley", None),
    ("center", "marketing", "营销中心", "autley", None),
    ("center", "product", "产品中心", "autley", None),
    ("center", "production", "生产中心", "autley", None),
    ("center", "rd", "研发中心", "autley", None),
    ("center", "quality_safety", "品质安全中心", "autley", None),
    ("center", "ops", "运营管理中心", "autley", None),
    ("center", "finance", "财务中心", "autley", None),
    ("dept", "thailand", "泰国公司", "autley", None),
    # 总经理办
    ("dept", "gm_risk_audit", "风控审计部", "gm_office", None),
    ("dept", "gm_new_hire", "新员工成长部", "gm_office", None),
    ("dept", "gm_ext_advisor", "外部顾问", "gm_office", None),
    # 战略发展中心
    ("dept", "strategy_policy", "政策研究部", "strategy", None),
    ("dept", "strategy_market", "市场发展部", "strategy", None),
    ("dept", "strategy_supplier", "供应商管理部", "strategy", None),
    # 营销中心
    ("dept", "sales", "销售部", "marketing", None),
    ("dept", "sales_suzhou", "苏州销售部", "sales", "suzhou"),
    ("dept", "sales_sz_g1", "销售一组", "sales_suzhou", "suzhou"),
    ("dept", "sales_sz_g2", "销售二组", "sales_suzhou", "suzhou"),
    ("dept", "sales_sz_g3", "销售三组", "sales_suzhou", "suzhou"),
    ("dept", "sales_sz_tech_g1", "技术型销售一组", "sales_suzhou", "suzhou"),
    ("dept", "sales_sz_tech_g2", "技术型销售二组", "sales_suzhou", "suzhou"),
    ("dept", "sales_sz_tech_g3", "技术型销售三组", "sales_suzhou", "suzhou"),
    ("dept", "sales_sz_foreign", "外贸组", "sales_suzhou", "suzhou"),
    ("dept", "sales_sz_foreign_dev", "客户开发组", "sales_sz_foreign", "suzhou"),
    ("dept", "sales_sz_foreign_tech", "技术支撑组", "sales_sz_foreign", "suzhou"),
    ("dept", "sales_sz_forklift", "叉车业务组", "sales_suzhou", "suzhou"),
    ("dept", "sales_taiyuan", "太原销售部", "sales", "taiyuan"),  # leaf
    ("dept", "sales_external", "外部人员", "sales", None),
    ("dept", "project_mgmt", "项目管理部", "marketing", None),
    ("dept", "project_div_1", "项目一部", "project_mgmt", None),
    ("dept", "project_div_2", "项目二部", "project_mgmt", None),
    ("dept", "after_sales", "售后服务部", "marketing", None),
    # 产品中心
    ("dept", "product_stacker", "堆垛机产品部", "product", None),
    ("dept", "product_fourway", "四向车产品部", "product", None),
    ("dept", "product_fourway_dense", "四向车密集库实施部", "product", None),
    ("dept", "product_overall", "项目总体细化部", "product", None),
    ("dept", "product_dev", "产品发展部", "product", None),
    ("dept", "elec_impl", "电气项目实施部", "product", None),
    ("dept", "elec_impl_g1", "项目实施一组", "elec_impl", None),
    ("dept", "elec_impl_g2", "项目实施二组", "elec_impl", None),
    ("dept", "elec_impl_g3", "项目实施三组", "elec_impl", None),
    ("dept", "elec_impl_g4", "项目实施四组", "elec_impl", None),
    ("dept", "software", "软件部", "product", None),
    ("dept", "procurement", "采购部", "product", None),
    ("dept", "archives", "资料室", "product", None),
    # 生产中心 (三部均为叶子)
    ("dept", "prod_admin", "综合管理部", "production", None),
    ("dept", "prod_ops", "生产部", "production", None),
    ("dept", "qa", "质检部", "production", None),
    # 研发中心
    ("dept", "elec_std_rd", "电气标准化研发部", "rd", None),  # leaf
    # 运营管理中心 (四部均为叶子)
    ("dept", "ops_planning", "计划运营部", "ops", None),
    ("dept", "ops_hr", "人力资源管理部", "ops", None),
    ("dept", "ops_admin", "行政部", "ops", None),
    ("dept", "ops_sz_hr_admin", "朔州人事行政", "ops", "shuozhou"),
]


async def seed_org_tree(session: AsyncSession, tenant_id: str) -> dict[str, OrgUnit]:
    """Upsert org units by (tenant_id, code); parents resolved from earlier codes."""
    by_code: dict[str, OrgUnit] = {}
    for type_, code, name, parent_code, site in ORG_SEED_NODES:
        parent_id = by_code[parent_code].id if parent_code else None
        existing = (
            await session.execute(
                select(OrgUnit).where(OrgUnit.tenant_id == tenant_id, OrgUnit.code == code)
            )
        ).scalar_one_or_none()
        if existing:
            existing.name = name
            existing.type = type_
            existing.parent_id = parent_id
            existing.default_site = site
            by_code[code] = existing
            continue
        unit = OrgUnit(
            id=new_id(),
            tenant_id=tenant_id,
            parent_id=parent_id,
            type=type_,
            code=code,
            name=name,
            default_site=site,
        )
        session.add(unit)
        await session.flush()
        by_code[code] = unit
    await session.flush()
    return by_code
