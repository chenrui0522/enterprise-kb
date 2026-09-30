## Context

See proposal.md for motivation. Leave-ledger jobs are independent today: `compute_ledger` reads only the job’s four sources; `confirm_job` freezes `LeaveLedgerSnapshot.rows`. Person rows already carry `travel_segments` / `ot_days` / `leave_segments` (post OT/export alignment). There is no job list API—only `GET /leave-ledger/jobs/{id}`—so prior selection needs a confirmed-jobs list. UI: `LeaveLedgerPage.jsx` (+ optional chat card later).

## Goals / Non-Goals

**Goals:**

- Pure merge of prior snapshot rows + current `compute_result.rows` with overlap-safe segment rules; write back to current job.
- Explicit `prior_job_id` (must be `confirmed`); list confirmed jobs for the picker.
- Preserve existing confirm/export path unchanged after merge.

**Non-Goals:**

- Creating a third “merge job” entity or period/month fields on jobs.
- Re-parsing prior month source files or re-running punch/HQ truncation on historical travel.
- Auto-picking “latest confirmed” without user selection.
- Chat-first merge UX (page is enough for V1; chat may call the same API later).
- Back-merging into already-confirmed jobs.

## Decisions

### D1 Write-back lifecycle (not a new job)

- `POST /leave-ledger/jobs/{job_id}/merge` with body `{ "prior_job_id": "..." }`.
- Preconditions: current ∈ {`parsed`, `needs_review`} (or any non-terminal with `compute_result`); prior.status == `confirmed`; same `tenant_id`; prior ≠ current.
- Effect: replace `job.compute_result["rows"]` (and refresh row-derived totals); filter warnings; set `resolved_warnings` / audit detail with `merged_from_job_id`; leave status as `needs_review` if any open blocking warnings remain, else `parsed` (match existing post-recompute conventions).
- Confirm still required before export.

Alternative considered: new merge job with `parent_ids`. Rejected per product choice—write back current month then confirm.

### D2 Merge algorithm (pure function)

Implement e.g. `merge_ledger_rows(prior_rows, current_rows, *, merge_gap_days) -> list[row dicts]`:

```
per person_name (union of names):
  travel: collect actual ranges (+ system bounds) from both sides
          -> _merge_project_segments -> recompute credit per merged span
  ot:     dict by date; if date in prior: keep prior entry; else current
  leave:  dict by (start, end); prior wins on collision
  recompute aggregates + remark from merged travel
```

Reuse `_merge_project_segments` / 30-day credit math from `rules.py` rather than duplicating. Prefer operating on dict row shapes already stored in JSON (same as snapshot).

### D3 Warning hygiene after merge

- Drop open blocking warnings whose `detail.person` + `detail.date` match an OT day present in the **prior** snapshot (prior credit already authoritative).
- Do not invent new OT warnings during merge (no punches available from prior).
- Operator re-reviews any remaining current-only warnings before confirm.

### D4 List confirmed jobs

- `GET /leave-ledger/jobs?status=confirmed` (tenant-scoped), newest `confirmed_at` first; return id, status, confirmed_at, light totals if cheap.
- Picker on LeaveLedgerPage: required select before Merge; no default selection.

### D5 Identity / org fields

- On name match: prefer current `center`/`department` if non-empty, else prior (current month roster fresher).
- No fuzzy name matching in V1.

## Risks / Trade-offs

- [Risk] Prior snapshot from before segment lists existed → Mitigation: export already synthesizes segments from aggregates; merge SHOULD apply the same fallback so old confirmed jobs remain usable, or reject merge with a clear error if segments cannot be recovered.
- [Risk] Adjacent short trips across months gain credit only after union recompute → Mitigation: intentional; document in UI copy (“合并会按出差并集重算额度”).
- [Risk] Operator merges wrong prior → Mitigation: explicit picker + audit `merged_from_job_id`; no auto-select.
- [Trade-off] Overwriting current `compute_result` loses pure-month view → Mitigation: audit only in V1; undo = re-upload/recompute from sources then merge again.

## Migration Plan

- No DB schema change if merge metadata lives in audit (+ optional JSON field on job later).
- Deploy API + UI; existing confirmed snapshots unchanged until used as prior.
- Rollback: revert release; merge endpoint 404; jobs remain independently usable.

## Open Questions

- Whether chat `LeaveLedgerJobCard` exposes merge in the same release (default: page only).
