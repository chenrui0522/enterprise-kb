## 1. Seed data model

- [x] 1.1 Encode design.md full tree as ordered seed tuples `(type, code, name, parent_code, default_site)` (exclude ☆太原/朔州/苏州公司; include `thailand`) and verify the list length matches harvested nodes plus TBD placeholders documented in comments
- [x] 1.2 Change `seed_org_tree` to upsert by `(tenant_id, code)`: update name/parent/type/default_site on existing rows; verify re-running seed moves `software` and `procurement` under `product` without changing their ids
- [x] 1.3 Rename display of `gm_office` to「总经理办」and verify API/list org units shows the new name for that code

## 2. Gap confirmation (before calling sync complete)

- [x] 2.1 Confirm or capture children for 太原销售部; if none, document「无下级」in design/README and leave node leaf — verify seed has no invented child codes
- [x] 2.2 Confirm or capture children for 综合管理部 / 生产部 / 质检部; verify seed matches confirmation
- [x] 2.3 Confirm or capture children for 电气标准化研发部; verify seed matches confirmation
- [x] 2.4 Confirm or capture children for 计划运营部 / 人力资源管理部 / 行政部 / 朔州人事行政; verify seed matches confirmation

## 3. Demo + docs + tests

- [x] 3.1 Update `seed-demo` (and any hardcoded org assumptions) so demo users hang on valid codes under the new tree; verify `uv run python -m app.cli seed-demo` completes
- [x] 3.2 Fix identity/org/staffing tests that assert software under production or old center set; verify relevant pytest suite passes
- [x] 3.3 Update README org diagram to 总经理办 + 八中心 + 泰国公司, note ☆城市公司 are site labels only; verify docs mention node-local scope with deep teams

## 4. Spec hygiene

- [x] 4.1 After apply, ensure main `openspec/specs/identity-access/spec.md` scenarios no longer claim软件部 under生产中心 (archive/merge will handle; smoke-read delta vs main for conflicts)
