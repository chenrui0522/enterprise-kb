## Context

See proposal.md - Why. Today `merge_job` / `_apply_merge_onto_job` take `prior_job_id` of a **confirmed** job and sticky-store it on `compute_result.merged_from_job_id`. Chat exposes add_source / review / confirm / export / void but no merge. Export shape is owned by `build_ledger_xlsx` (Taiyuan dual-header, per-person row blocks).

## Goals / Non-Goals

**Goals:**

- One prior model for page + chat: selectable prior jobs = confirmed OR import-from-export.
- Reverse-parse only the official export template into row dicts compatible with `merge_ledger_rows`.
- Chat tool actions for list/select merge and attach-as-prior; page UI parity for upload+merge.
- Keep sticky re-merge on `_recompute` via `merged_from_job_id` (imported priors are real jobs).

**Non-Goals:**

- Parsing arbitrary historical spreadsheets.
- Implementing attendance/staffing “prior period merge” (document reuse contract only).
- Auto-picking the “right” prior by date heuristics.

## Decisions

1. **Import creates a prior job, then merge by id**  
   Upload → parse rows → persist a tenant job marked as import prior (eligible for prior list; not a normal WeCom-source workflow). Then `merge(prior_job_id)` unchanged.  
   Alternative: stash prior rows only on the current job — rejected (forks sticky path; prior not reusable on page list).

2. **Prior eligibility**  
   Expand list API beyond `status=confirmed` to include import-prior jobs (voided excluded). UI shows source label (系统确认 / 导入导出).  
   Alternative: force import jobs into `confirmed` status — acceptable if audit fields distinguish `origin=export_import`; prefer explicit origin flag over overloading confirm semantics if schema allows a small additive field.

3. **Detect export vs WeCom four-source in chat**  
   Prefer structural detect (dual header / column layout of Taiyuan export) over filename. If export template matched and session has current job with rows → offer “作为上月台账合并” (or tool action), do not `classify_source` into travel/OT/leave/punch.  
   Alternative: require user to pick a separate composer mode first — heavier UX; keep detect + explicit confirm.

4. **API shape**  
   - `POST .../jobs/import-prior` (multipart xlsx) → `{ job_id, person_count, ... }`  
   - Existing `POST .../jobs/{id}/merge` body unchanged (`prior_job_id`).  
   - Chat: `leave_ledger.import_prior` + `leave_ledger.merge` (or single action with file+confirm).  
   Page: upload control next to prior `<select>`, then merge button.

5. **Round-trip fidelity**  
   Importer MUST rebuild `travel_segments` / `ot_days` / `leave_segments` and person totals from the export columns; credit-0 OT rows are absent in export (same as today) — document that imported prior cannot resurrect zero-credit OT days that were never exported. Round-trip test: `build_ledger_xlsx` → import → rows sufficient for merge scenarios in tests.

6. **Attendance follow-on (contract only)**  
   Future staffing/attendance “接上期” should reuse: explicit prior (job | official export file) → import-or-select → domain merge → sticky id. No code in this change.

## Risks / Trade-offs

- [Risk] Export layout drift breaks importer → Mitigation: shared header constants with `export.py`; round-trip unit test in CI.  
- [Risk] User uploads export as “fourth source” by mistake → Mitigation: structural detect + explicit prior confirm; never silent slot fill.  
- [Risk] Import prior clutter in list → Mitigation: label + sort by time; optional later filter (out of V1).  
- [Risk] Partial person blocks in hand-edited export → Mitigation: reject or skip incomplete blocks with clear error; no silent invent.

## Migration Plan

Deploy backend import + list expansion + chat/page UI together. Rollback = disable import endpoint and hide upload controls; existing confirmed-job merge remains. No data migration for old jobs.

## Open Questions

（无 — V1 定案：导入 prior 出现在合并 prior 选择器与审计所需列表；不混入「本月已确认工作流」主卡片浏览，除非产品后续要求。）
