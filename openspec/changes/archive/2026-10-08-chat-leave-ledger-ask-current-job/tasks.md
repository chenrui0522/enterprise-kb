## 1. Query helpers & orchestrator

- [x] 1.1 Add pure helpers to match person name in message against rows and format person/task answers from `compute_result` — verify unit tests for longest-name match, missing person, and field keywords (剩余/出差等)
- [x] 1.2 In `handle_leave_ledger_message`, when job is bound, no attachments, and text is a query, return grounded answer + progress card; when not a query keep progress tip; when no rows / no job, do not invent numbers — verify orchestrator tests: ask remaining for a seeded person; ask 多少人; ask unknown name; ask with no job
- [x] 1.3 Support presence asks (`有没有` / `在不在` / `台账…`) with grounded yes/no from rows — verify unit tests for present and absent names
- [x] 1.4 When composer clears `active_tool` but session still has `leave_ledger.job_id`, route to leave_ledger (not weak clarify) — verify `sticky_leave_tool_if_job` unit test

## 2. Docs

- [x] 2.1 Update `docs/leave-ledger-clerk-guide.md` that chat can ask about the current task’s people/totals after data is computed — verify the FAQ or flow mentions 对话查询当前台账（含「有没有某人」）
