## 1. Merge engine

- [x] 1.1 Add pure `merge_ledger_rows(prior_rows, current_rows, …)` (travel union + `_merge_project_segments` + 30-day credit recompute; OT/leave key dedupe with prior wins; aggregate refresh) and verify unit tests cover overlap travel credit, same-day OT prior-wins, and leave key dedupe
- [x] 1.2 Add fallback when prior rows lack segment lists (synthesize from aggregates like export) or fail with a clear error; verify with a fixture missing `travel_segments`

## 2. Service & API

- [x] 2.1 Implement `merge_job(session, principal, job_id, prior_job_id)`: gate statuses/tenant, load prior snapshot, write back `compute_result`, filter prior-covered OT warnings, audit `merged_from_job_id`; verify service/API tests for happy path and reject confirmed/voided/missing prior
- [x] 2.2 Add `GET /leave-ledger/jobs?status=confirmed` (tenant-scoped, newest confirmed first) and verify list excludes voided and non-confirmed
- [x] 2.3 Add `POST /leave-ledger/jobs/{job_id}/merge` + schema; verify OpenAPI/client contract and 4xx cases (no prior_job_id, prior not confirmed)

## 3. Frontend

- [x] 3.1 On `LeaveLedgerPage`, add required prior confirmed-job picker + Merge action that calls merge then refreshes job preview; verify picker loads confirmed list and merge updates on-page rows/warnings
- [x] 3.2 (Optional same release) Skip chat card merge UI; verify chat path still confirm/export unchanged

## 4. Docs & regression

- [x] 4.1 Note merge semantics (explicit prior, overlap recompute, prior wins) in leave-ledger README section; verify doc mentions write-back-then-confirm
- [x] 4.2 Run leave-ledger (+ related API) tests and verify suite green
