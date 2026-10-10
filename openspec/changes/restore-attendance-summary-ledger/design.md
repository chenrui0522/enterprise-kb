## Context

See proposal.md - Why. Main specs already describe V1 + chat tool behavior. Disk has partial `app/attendance_summary/*.py` (Decompyle++), richer `*.pyc`, router/orchestrator/query/model pyc under `__pycache__`, and a large `AttendanceSummaryJobCard` in `ChatPage.jsx`. `origin/main` never contained these sources. Frontend white-screen was caused by missing `AttendanceSummaryPage.jsx` while imports remained.

## Goals / Non-Goals

**Goals:**

- **Phase A (current):** Chat tool path runnable — claim tool, prior/roster, three sources, recompute, resolve, confirm, formal export; commit domain/API/orchestrator sources.
- Prefer recovering semantics from pyc over inventing new rules.
- Fold evidence-backed increments that the chat card can already trigger (period, calendar, punch/travel nuances).
- Keep leave-ledger / staffing paths stable.

**Non-Goals (Phase A):**

- Delivering `AttendanceSummaryPage.jsx` / nav entry (Phase B).
- Perfect byte-identical decompilation.
- Closing every empty unarchived attendance-* change in one go without evidence.
- Redesigning the Taiyuan template or permission model.

## Decisions

1. **Truth order**  
   Archived main specs → pyc disassembly / improved decompile → ChatPage action ids → unarchived OpenSpec text. Conflict: specs win for V1 normative rules; pyc wins for “what was actually shipped locally” when specs are silent; unarchived text alone is backlog.

2. **Recovery technique**  
   Re-decompile or reconstruct modules (`service`, `compute`, `export`, `parse`, `calendar`, `locations`, router, orchestrator, query, models) until imports and golden scenarios pass. Use leave-ledger / existing chat wiring as structural templates where pyc only yields control flow.  
   Alternative: greenfield rewrite from specs — rejected for this change (user chose 恢复优先).

3. **Frontend: chat first, page later**  
   Phase A keeps `attendance-summary` route redirected (or inert) to avoid white-screen; all operator UX goes through `AttendanceSummaryJobCard` + chat tool actions + blob export/preview APIs. Phase B rebuilds `AttendanceSummaryPage.jsx` (no checked-in page artifact exists).

4. **Increments (track B)**  
   Inventory pending change dirs + strings/actions in pyc/UI into a verification matrix in tasks. Implement only rows with ≥1 hard evidence (pyc symbol, card action, or non-empty delta spec). Others stay “待核实”.

5. **Commit gate**  
   Before calling the change done: attendance sources, router, orchestrator, page, and tests MUST be tracked by git (or explicitly staged for user commit). Running-only-from-pyc is a failure mode.

6. **Unarchive hygiene**  
   After restore, overlapping empty/partial attendance-* changes can be archived, superseded, or left—decide post-restore; not blocking first green path.

## Risks / Trade-offs

- [Risk] Decompile errors / wrong types → Mitigation: scenario tests from main spec; compare exports to known sample workbooks if available in repo.  
- [Risk] Scope creep from many pending changes → Mitigation: evidence matrix; default defer.  
- [Risk] Backend/chat works while FE page still missing → Mitigation (accepted): Phase A explicitly defers page; keep route redirect.  
- [Risk] DB models mismatch → Mitigation: read model pyc + alembic history; add migration only if schema gap vs running DB.

## Migration Plan

1. Ensure package import + routers + chat registry/orchestrator load.  
2. Smoke chat/API: create job → sources → recompute → confirm → export.  
3. Evidence-backed increments reachable from the card.  
4. User commits Phase A. Phase B = page/nav. Rollback = revert / disable tool registration.

## Open Questions

- Phase A done 标准：对话路径验收通过即可，不等专页。（已确认：对话优先。）
