## 1. Identity collision gate

- [x] 1.1 Detect same display name with both kinds in a batch and emit `name_kind_collision`; verify unit fixture with dual 王亮 produces the warning and `needs_review`
- [x] 1.2 Accept review resolutions `split` vs `merge`+`keep_kind`; verify confirm rejected while collision unresolved
- [x] 1.3 On confirm after `split`, persist facts keyed by `(work_date, person_name, person_kind)`; verify same day can hold two active facts for the two kinds
- [x] 1.4 On confirm after `merge`, collapse to chosen kind; verify only one kind remains for that name in written facts
- [x] 1.5 Alembic/adjust uniqueness so active facts allow same name different kinds; verify migration applies cleanly

## 2. Enriched summary API

- [x] 2.1 Extend `project_summary` to aggregate by `(person_name, person_kind)` with dates, project code/name, date range, person_day_total, by_kind subtotals; verify API/schema tests
- [x] 2.2 Map enriched summary into chat staffing `_summary_card` without dropping dates; verify card payload in orchestrator/unit test

## 3. Charts and export

- [x] 3.1 Add shared light chart component (identity person-day bars and/or people bars) fed by summary JSON; verify renders on StaffingPage with sample summary
- [x] 3.2 Add staffing project xlsx export endpoint (汇总 + 明细 sheets) gated by `staffing:read` + project access; verify 403 without access and workbook sheets present with auth
- [x] 3.3 Wire export control on StaffingPage and chat summary card; verify click triggers download

## 4. Chat / page UX for collision + summary

- [x] 4.1 Batch card UI: list colliding names with split/merge controls before confirm; verify confirm button disabled until resolved when collisions exist
- [x] 4.2 Summary card UI: project header, KPIs, by-kind subtotals, expandable dates, chart; verify chat after confirm shows enriched card
- [x] 4.3 Update StaffingPage summary table to name+kind rows matching API; verify dual-kind rows both visible

## 5. Docs and regression

- [x] 5.1 Update README staffing section: name+kind aggregation, collision review, chart, export
- [x] 5.2 Run staffing + chat staffing related pytest and verify green
