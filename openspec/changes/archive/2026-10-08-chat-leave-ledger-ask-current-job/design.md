## Context

See proposal.md - Why. Today `handle_leave_ledger_message`, when `job_id` is set and there is no attachment batch, always returns a fixed progress tip. Staffing already detects summary-like questions (`有谁|汇总|…`) and returns structured data — leave-ledger can mirror that pattern against `job.compute_result["rows"]`.

## Goals / Non-Goals

**Goals:**

- Intercept plain-text turns on an active leave-ledger job and answer from rows / totals / warning counts.
- Rule-first intent: person lookup, task summary, leftover progress tip only when not a query.
- Keep upload / role-pick / confirm / void paths unchanged.

**Non-Goals:**

- Historical confirmed-job Q&A, export-file RAG, LLM-required answers in V1.
- Mutating ledger data via chat questions.
- Full natural-language analytics (排序 TOP N、复杂条件) beyond simple patterns — can extend later.

## Decisions

1. **Hook inside `handle_leave_ledger_message` after batch/pending handling**  
   If `job_id` and text looks like a query → answer; else keep existing progress tip.  
   Alternative: route unknown text to RAG graph — rejected (violates grounded numbers).

2. **Rule-first parsers (V1)**  
   - Person: extract a name by matching `person_name` substrings in the message (prefer longest match); fields from keywords `剩余|已休|出差|加班|合计|备注`.  
   - Presence: keywords `有没有|有无|在不在|包含|台账` → yes + person summary, or no + name hint.  
   - Summary: keywords `多少人|几个人|合计|汇总|总览|进度|告警`.  
   - If both person and summary, person wins when a name matches.  
   Alternative: LLM classify — defer; add only if rules prove too brittle.

2b. **Sticky job beats weak clarify**  
   Frontend may send `active_tool=""` (clears sticky tool selection) while `leave_ledger.job_id` remains. Resolve `active_tool` via `sticky_leave_tool_if_job` so presence/field asks hit the leave handler instead of LEAVE weak-clarify copy.

3. **Answer format**  
   Short Chinese prose + key numbers; still attach progress `card` so UI stays consistent. No new card type required for V1.

4. **Empty rows**  
   Job exists but `rows` empty → say 尚无预览行（可能缺源或未算出），not fake zeros as people.

5. **Permissions**  
   Existing `ensure_tool_allowed` / org gate on leave_ledger path; read-only query needs at least leave_ledger read (already implied by tool visibility).

## Risks / Trade-offs

- [Risk] Name collisions / partial matches → Mitigation: longest `person_name` match; if multiple equal, list candidates.
- [Risk] Users expect free-form NL → Mitigation: document supported asks; unmatched → honest fallback.
- [Risk] Confirmed vs draft job — same job_id in session is fine; numbers are whatever last compute/merge wrote.

## Migration Plan

Deploy orchestrator + tests; optional clerk-guide line. Rollback = revert handler branch.
