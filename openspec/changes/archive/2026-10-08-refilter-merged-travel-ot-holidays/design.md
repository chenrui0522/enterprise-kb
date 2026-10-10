## Context

See proposal.md - Why. Today `merge_ledger_rows` unions travel (and recomputes 30-day travel credit) and merges OT with prior-wins, then sums credits. It does **not** re-apply Rule 2 (in project actual travel → only statutory body-day OT). Single-pass `compute_ledger` already enforces Rule 2; the gap is only on the merge path after travel expands.

Observed failure: prior credited 6/19–21 under Rule 3 (outside travel); current travel covered June; merged export kept three OT days though holidays file lists only `2026-06-19`.

## Goals / Non-Goals

**Goals:**

- After travel union + OT key merge, drop OT days that fall inside merged actual travel and are not in the holidays set; refresh `holiday` flags; recompute person totals.
- Pass the same holidays set used by `_recompute` into merge from the service layer.
- Unit-test the Dragon-Boat-style case (three OT days → one kept).

**Non-Goals:**

- Changing Rule 2/3 inside `compute_ledger`, or changing resolution bypass (`accept_full` etc.) on the single-pass path.
- Auto-repairing already `confirmed` snapshots.
- Completing/filling the yearly holidays file beyond documenting that it must list body days only (ops maintenance).
- Changing export template shape or merge API shape.

## Decisions

1. **Filter after prior-wins, not instead of it**  
   Keep `(name, date)` prior-wins, then filter. Rationale: prior still wins when both sides have a legal OT day; Rule 2 after union is a hard business constraint that overrides stale Rule-3 credits.  
   Alternative considered: ignore prior OT entirely and recompute from raw sources — heavier, needs both jobs' source files; out of scope.

2. **Drop ineligible days (same as compute `continue`)**  
   Remove the OT day from the merged list rather than setting credit to 0, so export does not need an extra zero-row pass.  
   Alternative: keep credit 0 rows — export already omits zero OT rows, but list noise is unnecessary.

3. **Holidays from `load_holidays(settings)` at merge apply time**  
   Same file as compute. If calendar missing → empty set → all in-travel OT dropped (strict). Matches compute's "no holidays → skip in-travel OT credit" posture when set is empty after warn path; service already loads holidays for compute.

4. **No resolution channel on merge filter (V1)**  
   Merge does not consult `resolved_warnings`. Stale prior credits that violate Rule 2 after union are removed. Clerks who need an exceptional in-travel non-holiday day must use single-pass resolutions on a recompute that includes that OT (existing "人工决议除外" on compute). Documented trade-off.

## Risks / Trade-offs

- [Risk] Prior intentionally kept weekend OT that later falls inside travel → Mitigation: product rule is clear (段内只计法定本体); clerk guide + void/re-merge.
- [Risk] Incomplete holidays file under-credits statutory days → Mitigation: ops maintains `leave_ledger_holidays_*.txt`; not introduced by this change.
- [Risk] Sticky re-merge on review must also pass holidays → Mitigation: single `_apply_merge_onto_job` call site already centralizes merge; wire holidays there once.

## Migration Plan

1. Deploy merge filter + tests.
2. Clerks void or recreate jobs that were confirmed with inflated OT; re-merge prior → confirm → export.
3. No DB migration. Rollback = revert merge filter (behavior returns to prior-wins only).
