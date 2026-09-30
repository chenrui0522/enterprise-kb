## Context

See proposal.md for motivation. Chat tools already support staffing via registry / `route_turn` / `staffing_orchestrator` / SSE cards / `/chat/tool-action`, with `conversation.tool_state` holding `active_tool` and staffing batch context. Leave ledger domain (`app/leave_ledger/*`, `/leave-ledger`, `leave_ledger:read|write`) already supports multi-file jobs: `create_job_with_files`, `add_source_file`, `review_job`, `confirm_job`, `void_job`, `export_job_xlsx`, plus `classify_source`. No chat wiring yet; `apply_tool_action` is staffing-hardcoded.

## Goals / Non-Goals

**Goals:**
- Register `leave_ledger` tool; permission-gate in `/chat/tools` and composer.
- Pre-RAG claim path mirroring staffing; incremental B-flow with progress card.
- Auto role classify with clarify-on-ambiguity; reuse leave_ledger service unchanged for rules.

**Non-Goals:**
- Changing compute rules, parsers, or holiday config.
- Removing `/leave-ledger`.
- Generic LLM tool-calling platform.
- Cross-tool auto-disambiguation beyond fixed clarify copy (staffing vs leave vs RAG).

## Decisions

1. **Parallel orchestrator, shared shell**
   - Add `leave_ledger_orchestrator` (or equivalent) + `TOOL_LEAVE_LEDGER`.
   - `chat.py` / `apply_tool_action`: dispatch by `active_tool` / action namespace.
   - Alternative: stuff leave into staffing orchestrator — rejected (different job model).

2. **tool_state shape**
   - `tool_state.leave_ledger = { job_id, pending_role? }` alongside existing staffing keys.
   - First claiming turn creates job (empty or with first file); later attachments call `add_source_file`.
   - Switching tools or new conversation clears leave_ledger context (same as staffing).

3. **Role assignment: classify first**
   - Call existing `classify_source`; on confident role → add; on ambiguous → ask user to pick travel/overtime/leave/punch (card or short reply); do not invent role.
   - Alternative: always ask — rejected for friction.

4. **Routing (M3-style)**
   - Explicit `active_tool=leave_ledger` wins.
   - Strong: leave keywords / filenames (出差|加班|请假|打卡|调休|台账…) + xlsx + permission.
   - Weak: ambiguous attendance-ish file → clarify leave_ledger vs 只要讲解 (and do not steal staffing strong matches).
   - Conflict staffing vs leave: prefer explicit tool; else stronger keyword set; if still tied → clarify which tool.

5. **Cards + tool-action**
   - Progress card: four roles filled/missing, warnings count, actions: accept missing, resolve warning, confirm, export, void.
   - Confirm/void/export via `/chat/tool-action` only (mirror staffing button-only confirm).
   - Export returns same bytes/path semantics as REST export.

6. **Attachments**
   - Reuse `POST /chat/attachments`; accept ooxml xlsx for leave sources (PDF leave sources out of scope unless domain already supports — currently xlsx-focused).

## Risks / Trade-offs

- [Mis-route staffing日报 into leave or reverse] → Keyword/filename tables separated; weak clarify; explicit tool sticky.
- [Wrong auto role] → Ambiguity path + user override on card before confirm.
- [Partial job abandoned in chat] → Job remains listable on `/leave-ledger`; void available with write perm.
- [tool-action sprawl] → Namespace actions `leave_ledger.*` vs staffing actions.

## Migration Plan

1. Registry + router + orchestrator (create/add/progress).
2. Cards + tool-action (review/confirm/export/void).
3. Clarify copy + conflict tests with staffing.
4. Rollback: remove tool from registry / hide in UI; independent page unchanged.

## Open Questions

（无 — 形态 B 与自动分类优先已在探索中确认）
