## Context

See proposal.md for motivation. Staffing import/confirm/summary already ship (`staffing-daily-import` + chat tool). Current gaps: summary UI/API too thin; parse/summary silently merge same display name across `internal_formal` / `internal_contract` (formal wins); chat card mirrors the thin summary.

Constraints: reuse existing batch/fact tables and `staffing:*` permissions; keep `/staffing` page; chat cards stay compact (no dashboard chrome).

## Goals / Non-Goals

**Goals:**

- Human gate for same-name dual-kind collisions before confirm.
- Aggregate and display by `(person_name, person_kind)`.
- Enrich summary payload + chat/page rendering; light chart; xlsx export (summary + detail sheets).

**Non-Goals:**

- Employee master / HR ID linkage.
- Full BI dashboards or heavy chart libraries unless a tiny dependency is clearly justified.
- Re-litigating external外包统计.
- Automatic rename suggestions beyond operator-chosen merge/split resolutions.

## Decisions

### D1 — Identity key: `(person_name, person_kind)` after split

- Default detection: within a batch’s parsed internal rows, if any `person_name` maps to both kinds → warning `name_kind_collision`.
- Resolutions stored on batch `resolved_warnings` (or structured sibling):
  - `split`：keep both kinds；confirm may write two facts per day when both present.
  - `merge` + `keep_kind`：collapse to one kind for that name for the batch.
- Same-day both sources listing the same name: no longer auto formal-wins without resolution when collision warning applies; after `merge` keep formal (or chosen kind); after `split` keep two facts that day.
- Unique active fact key becomes `(project_id, work_date, person_name, person_kind)` (migration/constraint update if current unique omits kind).

Alternatives: rename-only (option 1) — rejected per product choice; HR ID — deferred.

### D2 — Summary API shape

Extend `project_summary` (and chat card mapping) with:

- `project_id`, `project_code`, `project_name`
- `date_from`, `date_to`, `person_count`, `person_day_total`
- `by_kind`: `{ formal: { person_count, person_day_total }, contract: { ... } }`
- `people[]`: `{ person_name, person_kind, person_kind_label, days_on_site, dates[] }` keyed by name+kind

Chat `_summary_card` MUST pass through these fields (not strip dates).

### D3 — Charts

- Prefer CSS/SVG bar comparison in React (identity person-days; optional top-N people bars).
- Same component used by `StaffingPage` and chat card.
- No new backend chart endpoint — derive from summary JSON.

### D4 — Export

- `GET /api/v1/staffing/projects/{project_id}/export.xlsx` (or POST) requiring `staffing:read` + project access.
- Workbook: sheet `汇总` (people rows + header meta), sheet `明细` (work_date, name, kind).
- Chat card triggers same URL (blob download with cookies).

### D5 — Chat + page parity

- One shared summary presentational component (or thin wrappers) so KPI/table/chart/export stay aligned.
- Collision UI: on batch card, list colliding names with split/merge controls before ack_and_confirm; server rejects confirm if unresolved.

## Risks / Trade-offs

- [Historical merged data] → Document that old confirms may have collapsed two people; operators may void + re-import after upgrade.
- [Constraint migration on facts] → Add/adjust unique index carefully; backfill treat existing rows as already kind-scoped.
- [Chat card height] → Cap people list / chart height; expand dates behind disclosure.
- [False collision] → Same person truly dual-sourced still needs one click merge; copy must make options clear.

## Migration Plan

1. Ship warning + resolution + confirm gating + summary key change.
2. Alembic: unique `(batch_id, work_date, person_name, person_kind)` or project-level active uniqueness including kind.
3. Enrich summary API + FE table/KPI.
4. Chart component + export endpoint.
5. Wire chat card; regression tests for 王亮 dual-kind fixture.
6. Rollback: feature-flag export/chart only; collision gate should not be silently disabled once shipped (data integrity).

## Open Questions

- Exact Chinese copy for merge vs split buttons (tunable in implement).
- Whether merge default suggestion is formal when both kinds present (default yes; operator can override).
