## 1. API & orchestrator

- [x] 1.1 Add optional `attachment_ids` on `ChatRequest` (keep `attachment_id`); resolve effective list with a small cap — verify schema/unit test accepts both singular and list forms
- [x] 1.2 In chat stream path, load all effective attachments; when leave_ledger claims the turn, add each auto-classified source in order to the same job and stop at first role-ambiguous file (summarize added vs pending/skipped) — verify orchestrator/integration test: two clear roles in one turn update progress for both; ambiguous mid-batch leaves classified ones in job
- [x] 1.3 Non-leave-ledger turns with multiple ids use only the first attachment (optional brief note) — verify staffing/RAG path still works with a single attachment and does not require `attachment_ids`

## 2. Frontend

- [x] 2.1 Chat composer: `multiple` file input, upload each file, show pending list, send `attachment_ids` — verify UI can attach ≥2 xlsx and network payload includes the list
- [x] 2.2 Clear pending attachments after successful send; keep single-file flow working — verify empty composer after send and singular upload still sends

## 3. Docs

- [x] 3.1 Update `docs/leave-ledger-clerk-guide.md` that chat can multi-select four sources in one send (分次仍可用) — verify the guide states both paths
