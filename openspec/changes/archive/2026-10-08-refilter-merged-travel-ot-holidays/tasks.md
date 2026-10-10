## 1. Merge path re-filter

- [x] 1.1 After OT prior-wins and travel union, drop OT days that fall inside merged actual travel and are not in the holidays set; refresh `holiday` flags and person totals — verify with unit test: prior has 6/19–21 credits outside travel, current travel covers June, holidays=`{2026-06-19}` → merged `ot_comp_days == 1` and only `2026-06-19` remains
- [x] 1.2 Pass `load_holidays(settings)` (or empty set) into `merge_ledger_rows` from `_apply_merge_onto_job` (including sticky re-merge) — verify merge service/integration path still succeeds and uses the same holidays file as compute

## 2. Docs

- [x] 2.1 Update `docs/leave-ledger-clerk-guide.md` to state that after merge, in-travel non-statutory OT days are removed (e.g. 端午连休只留法定当天) — verify the guide mentions merge re-check of statutory OT
