## Context

See proposal.md for motivation. Current implementation seeds the full WeCom address-book folder tree via `app/identity/org_seed.py` (upsert by code). `OrgUnit.type` allows `company|office|center|dept|committee`. Auth stays node-local (no subtree).

Confirmed leaves (no children): 太原销售部；综合管理部 / 生产部 / 质检部；电气标准化研发部；计划运营部 / 人力资源管理部 / 行政部 / 朔州人事行政.

## Goals / Non-Goals

**Goals:**

- Replace/extend seed so `org_units` mirrors address-book folders under one company root.
- Stable `code` per node; upsert by `(tenant_id, code)` so re-seed is idempotent.
- Migrate existing demo codes that remain valid (`software`, `procurement` parent change; `gm_office` rename display).
- Document full target tree (with suggested codes) for implementers.

**Non-Goals:**

- Creating or syncing users/positions from address-book people.
- Changing Principal / visibility formulas (no subtree scope).
- New org `type` values (groups use `dept` for now).
- Building ☆太原/朔州/苏州公司 as org units or second company roots.
- Automatic WeCom API sync (manual/seed list is enough for this change).

## Decisions

### D1 — Single company root; Thailand as sibling dept

Company `autley` remains the only root. Direct children: 总经理办 (`office`), eight centers (`center`), 泰国公司 (`dept`, code `thailand`).

Alternatives considered: Thailand as `center` or under marketing — rejected (user: T1 + dept).

### D2 — ☆ city companies are labels only

Do not insert org nodes for 太原/朔州/苏州公司. Keep `User.site` ∈ {taiyuan, shuozhou, suzhou}. Regional depts with city names in the title are real nodes (苏州销售部, 太原销售部 under sales; 朔州人事行政 under ops).

### D3 — Depth = full folder fidelity

Every folder including L5/L6 teams becomes an `org_unit` with `type=dept` (L2 office/center unchanged). No `team` type this change.

### D4 — Seed as declarative list + parent-aware upsert

Keep a ordered list of `(type, code, name, parent_code, default_site|None)` in `seed_org_tree` (or a dedicated module imported by CLI). On existing row: update `name`, `parent_id`, `type`, `default_site` to match list. Prefer updating parents for `software`/`procurement` over creating duplicate codes.

Alternatives: wipe-and-reseed — rejected for envs with live users/docs tied to org ids.

### D5 — Naming

Display name 总经理办 (not 总经办). Keep code `gm_office` for stability. Project management: 项目管理部 (`project_mgmt`), with 项目一部 / 项目二部 as **siblings** under it (assume siblings unless later corrected; screenshot nesting was ambiguous).

### D6 — default_site

Leave `default_site` null for most nodes. Optional hints only where address-book strongly implies location (e.g. 苏州销售部 → suzhou, 太原销售部 → taiyuan, 朔州人事行政 → shuozhou). Do not set production center default to shuozhou solely from old demo.

## Full target tree (harvested)

Codes are suggestions for implementers; names must match address book.

```
autley (company) 奥特莱物流科技有限公司
|-- gm_office (office) 总经理办
|   |-- gm_risk_audit (dept) 风控审计部
|   |-- gm_new_hire (dept) 新员工成长部
|   |-- gm_ext_advisor (dept) 外部顾问
|-- strategy (center) 战略发展中心
|   |-- strategy_policy (dept) 政策研究部
|   |-- strategy_market (dept) 市场发展部
|   |-- strategy_supplier (dept) 供应商管理部
|-- marketing (center) 营销中心
|   |-- sales (dept) 销售部
|   |   |-- sales_suzhou (dept) 苏州销售部
|   |   |   |-- sales_sz_g1 (dept) 销售一组
|   |   |   |-- sales_sz_g2 (dept) 销售二组
|   |   |   |-- sales_sz_g3 (dept) 销售三组
|   |   |   |-- sales_sz_tech_g1 (dept) 技术型销售一组
|   |   |   |-- sales_sz_tech_g2 (dept) 技术型销售二组
|   |   |   |-- sales_sz_tech_g3 (dept) 技术型销售三组
|   |   |   |-- sales_sz_foreign (dept) 外贸组
|   |   |   |   |-- sales_sz_foreign_dev (dept) 客户开发组
|   |   |   |   |-- sales_sz_foreign_tech (dept) 技术支撑组
|   |   |   |-- sales_sz_forklift (dept) 叉车业务组
|   |   |-- sales_taiyuan (dept) 太原销售部   (leaf)
|   |   |-- sales_external (dept) 外部人员
|   |-- project_mgmt (dept) 项目管理部
|   |   |-- project_div_1 (dept) 项目一部
|   |   |-- project_div_2 (dept) 项目二部
|   |-- after_sales (dept) 售后服务部
|-- product (center) 产品中心
|   |-- product_stacker (dept) 堆垛机产品部
|   |-- product_fourway (dept) 四向车产品部
|   |-- product_fourway_dense (dept) 四向车密集库实施部
|   |-- product_overall (dept) 项目总体细化部
|   |-- product_dev (dept) 产品发展部
|   |-- elec_impl (dept) 电气项目实施部
|   |   |-- elec_impl_g1..g4 (dept) 项目实施一/二/三/四组
|   |-- software (dept) 软件部          <-- was under production in demo
|   |-- procurement (dept) 采购部       <-- was under production in demo
|   |-- archives (dept) 资料室
|-- production (center) 生产中心
|   |-- prod_admin (dept) 综合管理部    (leaf)
|   |-- prod_ops (dept) 生产部          (leaf)
|   |-- qa (dept) 质检部               (leaf)
|-- rd (center) 研发中心
|   |-- elec_std_rd (dept) 电气标准化研发部  (leaf)
|-- quality_safety (center) 品质安全中心   (leaf)
|-- ops (center) 运营管理中心
|   |-- ops_planning (dept) 计划运营部     (leaf)
|   |-- ops_hr (dept) 人力资源管理部       (leaf)
|   |-- ops_admin (dept) 行政部           (leaf)
|   |-- ops_sz_hr_admin (dept) 朔州人事行政  (leaf)
|-- finance (center) 财务中心             (leaf)
|-- thailand (dept) 泰国公司
```

Not in tree: 太原公司 / 朔州公司 / 苏州公司.

## Risks / Trade-offs

- [Deep tree + node-local scope] → People hung on L5 only see that team’s docs; document in README; subtree scope out of scope.
- [Parent moves for software/procurement] → Positions keep `org_unit_id`; updating parent_id on same row preserves bindings. Documents keyed by org_unit_id stay valid.
- [Demo users/tests assume old parents] → Update seed-demo narrative and failing tests in same change.
- [项目一部/二部 nesting ambiguous] → Assume siblings; easy to reparent later via upsert.

## Migration Plan

1. Expand `seed_org_tree` (or module) with full list; upsert by code.
2. Run seed on existing DB: renames/parent fixes + inserts.
3. Update `seed-demo` users/positions that reference moved nodes if needed.
4. Fix identity/org tests and README org diagram.
5. Rollback: restore previous seed list and re-upsert (ids preserved for known codes); new codes remain unused orphans—acceptable for demo.

## Open Questions

- Whether 外部顾问 / 外部人员 should later become `committee` instead of `dept` (default `dept` now).
