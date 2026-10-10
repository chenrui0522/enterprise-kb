## 1. Export → prior import (backend)

- [x] 1.1 Add reverse parser from Taiyuan official export xlsx (`build_ledger_xlsx` layout) into person-row dicts with travel/ot/leave segments — verify round-trip unit test: export sample rows → import → segments/credits match for merge inputs; reject non-template xlsx
- [x] 1.2 Persist import as a tenant prior-eligible job (origin/import flag; not voided) and expose via prior list alongside confirmed jobs — verify list API returns import prior with distinguishable source and excludes voided
- [x] 1.3 Add `import-prior` API (multipart) requiring leave-ledger write + org gate; import alone MUST NOT merge into a current job — verify API test: import OK; merge still needs explicit `prior_job_id` on current job

## 2. Merge path reuse

- [x] 2.1 Allow `merge_job` to accept import-prior jobs as `prior_job_id` (same sticky `merged_from_job_id` / re-merge) — verify service test: merge current draft with imported prior writes rows and sticky id
- [x] 2.2 Keep page merge select wired to expanded prior list — verify existing merge UI still works with a confirmed prior after list change

## 3. Chat tool actions

- [x] 3.1 Add chat actions to list/select prior and `leave_ledger.merge` for the bound current job — verify orchestrator/API test: merge with confirmed prior updates card; missing prior_id rejected
- [x] 3.2 Detect official export attachment in leave-ledger chat; do not fill four-source slots; on explicit confirm import(+merge) — verify: export xlsx does not set travel/ot/leave/punch; confirm merge path updates compute_result
- [x] 3.3 Chat progress card UI: prior picker + upload/merge controls — verify manual or component-level behavior: can select prior and trigger merge without leaving chat

## 4. Page UI + docs

- [x] 4.1 Leave-ledger page merge section: upload official export → import prior → select → merge — verify page flow against import+merge API (or e2e/smoke)
- [x] 4.2 Update `docs/leave-ledger-clerk-guide.md` for chat + page paths (选系统 prior / 上传导出台账) — verify guide no longer says merge is page-only or Excel-only-impossible
