## Context

See proposal.md - Why. Chat already short-circuits before RAG via `route_turn` + `leave_ledger` / `staffing` orchestrators, `/chat/tools`, `/chat/tool-action`, and `LeaveLedgerJobCard`. Attendance summary domain APIs live under `/attendance-summary/*` with dual ops gate; no chat wiring yet. Leave and attendance share WeCom travel/leave/punch xlsx shapes.

## Goals / Non-Goals

**Goals:**

- Parallel chat tool `attendance_summary` with leave-parity lifecycle in-session.
- Ambiguous leave-vs-attendance turns always clarify before creating attendance jobs or confirming.
- Year/month: default current calendar month; parse explicit month from message; else ask.
- Reuse domain `app.attendance_summary.service` (no second compute path).

**Non-Goals:**

- Moving calendar / overseas-keyword config into chat UI.
- Auto-picking prior by heuristics.
- OT as a fourth attendance source.
- Changing leave or staffing compute rules.

## Decisions

1. **Tool id and registry**  
   Add `TOOL_ATTENDANCE_SUMMARY = "attendance_summary"` / label「考勤汇总台账」; `list_tools_for_principal` filters with `can_use_attendance_summary`.  
   Alternative: reuse leave tool with a mode flag — rejected (different job model, prior/HR, export).

2. **Routing: clarify-first between leave and attendance**  
   When `active_tool` unset and no sticky leave/attendance job: if turn looks like leave **or** attendance (xlsx + 出差/请假/打卡/考勤/调休等), return a clarify kind that offers 调休台账 / 考勤汇总台账 / 只要讲解 — do not strong-route to leave on bare three-source uploads. Explicit tool and sticky job still win. Staffing vs (leave|attendance) keeps existing conflict path; after user picks leave or attendance, proceed.  
   Alternative: keyword auto-pick — rejected by product (always ask when unclear).

3. **Sticky state**  
   Mirror leave: `conversation.tool_state.attendance_summary.job_id` (+ pending role / pending prior / pending month clarify as needed). `sticky_attendance_tool_if_job` restores tool when composer clears selection.

4. **Orchestrator shape**  
   New `attendance_summary_orchestrator.py` (+ small `attendance_summary_query.py`) patterned on leave: attach → classify roles (travel/leave/punch) → `upload_source`; detect official export → pending prior confirm; HR roster upload → `upload_hr_diff` + resolve actions; text → query helper; actions via `/chat/tool-action` (`attendance_summary.*`). Card type `attendance_summary_job`.  
   Alternative: call REST only from frontend chat — rejected (lose streaming/clarify consistency with leave).

5. **Year/month**  
   On first need to `create_job`: parse message for month (and year if present); else use today‘s year/month; if parse ambiguous (e.g. only「上个月」without rule) ask once and stash pending. Do not recreate job silently when month changes mid-session without user confirm.  
   Alternative: always ask month — rejected (extra friction).

6. **Prior / HR parity**  
   Chat actions wrap existing `set_prior`, `import_prior_export`, `upload_hr_diff`, `resolve_hr_diff`, `resolve_conflict`, `recompute`, `confirm`, `void_job`, export download URL. Progress card lists missing roles, warning counts, roster readiness (no prior → block confirm with clear copy).

7. **Query helper**  
   Rule/template over `compute_result` people rows (实出勤、假种、迟到/缺卡/旷工、备注摘要、人数). No LLM required for V1; unanswered → say so.

8. **Frontend**  
   Extend ChatPage tool menu + `AttendanceSummaryJobCard` (clone leave card structure: progress, pick_role, prior, HR/conflict resolve, confirm, void, export). Export uses existing attendance-summary export endpoint after action ack.

## Risks / Trade-offs

- [Risk] Clarify fatigue on every three-source upload → Mitigation: sticky + explicit tool skip clarify; only fire when unbound.  
- [Risk] User confirms leave when they meant attendance → Mitigation: clear option labels; progress card title shows「考勤汇总」vs「调休」; void/recreate path.  
- [Risk] Job created for wrong month → Mitigation: show year/month on card; allow「改成 N 月」confirm before heavy uploads when possible.  
- [Risk] Dual sticky leave+attendance in one conversation → Mitigation: prefer explicit active_tool; if both job_ids exist without explicit tool, ask which to continue (same clarify family).  
- [Risk] Domain errors (no calendar / no roster) surface poorly in chat → Mitigation: map AppError to plain Chinese on card/message; link to专页 for config.

## Migration Plan

Ship registry + router clarify + orchestrator + card together. Rollback: hide tool from `/chat/tools` and ignore `attendance_summary` actions; domain page unchanged. No DB migration beyond existing attendance_summary tables.

## Open Questions

（无 — 路由澄清、全套对齐、年月默认当月已定。）
