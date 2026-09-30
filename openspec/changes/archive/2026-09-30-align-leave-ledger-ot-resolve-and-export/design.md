## Context

See proposal.md for motivation. Domain code lives in `app/leave_ledger/` (`rules.compute_ledger`, `service._recompute` / `review_job`, `export.build_ledger_xlsx`). Today OT warnings clear via `resolved_warnings` but resolutions are not passed into `compute_ledger`, so `accept_full` does not change `ot_comp_days`. Export is one flat row per person. Chat and `/leave-ledger` share the same review/confirm/export APIs.

## Goals / Non-Goals

**Goals:**

- Feed OT resolutions into recompute so credits match `exclude` / `accept_half` / `accept_full`.
- Persist enough segment detail in `compute_result` to build multi-row export without re-parsing at download time.
- Emit Taiyuan-shaped xlsx (2-row header, per-person block, merges, yellow total headers).
- Expose half-day action on both UIs.
- Project-travel OT: only statutory holidays inside actual travel segments auto-credit (template rule 2); outside travel / non-project keep dual-evidence day +1 (rule 3).

**Non-Goals:**

- Changing project-travel 30→2, HQ truncation, or approval include/exclude semantics.
- Merging OT days into approval-span ranges in the export.
- Backfilling already-confirmed snapshots to the new layout.
- Pixel-perfect clone of every sample workbook style beyond the agreed columns/merges/highlights.

## Decisions

### D1 Pass OT resolution map into `compute_ledger`

- Add a typed resolution input (e.g. `ot_resolutions: dict[tuple[person, date], action]` derived from `resolved_warnings["ot_missing_punch"]` / `["ot_half_day_mismatch"]`).
- On each OT day: if action `accept_full` → +1; `accept_half` → +0.5; `exclude` → 0 and no blocking re-emit; if unresolved missing/half-day → warn and +0; else dual evidence → +1.
- Keep clearing open warnings via existing `_open_blocking_warnings` after recompute (warnings regenerated each run; resolutions continue to gate them).

Alternative: post-process row totals after compute. Rejected: easy to drift from per-day OT list used by export.

### D2 Structured person payload for export

- Extend each person result with lists: `travel_segments[]` (system/actual start-end, credit), `ot_days[]` (date, credit, optional holiday flag), `leave_segments[]` (start, end, used days).
- Keep aggregate fields on the person for preview tables and totals.
- Export builds a person block with `nrows = max(len(travel), len(ot>0), len(leave))`, padding shorter columns; merge identity/total columns across the block.

Alternative: only reshape at export by re-running parse. Rejected: snapshot would not freeze segment detail used for the confirmed file.

### D3 Export column contract (A–R)

Two header rows matching the template labels (系统提报/实际出差起止、两列「可调休天数」、加班开始/结束、合计可调休、调休起止、已休、合计已休、剩余、备注). Use 「已休」 wording (not 「已磨」). Yellow fill on 合计可调休天数 and 合计已休天数 header cells. OT start=end=work date; omit days with credit 0.

### D4 UI

- Add 「按半日记」 next to 排除 / 按满日记 on chat card and leave-ledger page (including bulk optional later; V1 per-row is enough, bulk may keep exclude/full only).
- After review, preview numbers MUST reflect recomputed credits (reload job / new card).

## Risks / Trade-offs

- [Risk] Confirmed jobs exported before this change differ in shape from new exports → Mitigation: document BREAKING in README; no silent dual format.
- [Risk] Large OT lists make tall person blocks → Mitigation: acceptable; only credit>0 rows.
- [Trade-off] Multi-row export needs openpyxl merges/styles → slightly more fragile tests; assert headers + sample merges + key cell values.

## Migration Plan

- Deploy code; no DB migration required if segment lists live inside existing JSON `compute_result` / snapshot rows (extend snapshot schema in JSON as needed).
- Re-review open `needs_review` jobs to refresh credits after OT resolutions.
- Rollback: revert release; old single-row export returns.

## Open Questions

- None material; bulk half-day button deferred unless implementer finds it trivial alongside existing bulk OT actions.
