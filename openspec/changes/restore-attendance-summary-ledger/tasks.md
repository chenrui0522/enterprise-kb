## 1. Evidence & inventory

- [x] 1.1 Build evidence matrix: pending `attendance-*` / `chat-attendance-*` changes × pyc symbols × `ChatPage` action ids — verify a checked-in note (table in design appendix or `tasks` comments via completed rows) marking each as restore / defer
- [x] 1.2 Improve decompile or reconstruct `app/attendance_summary/{service,compute,export,parse,calendar,locations}.py` until they import and key functions exist — verify `python -c "from app.attendance_summary import service, compute, export"` succeeds

## 2. Backend V1 restore

- [x] 2.1 Restore `app/models/attendance_summary.py` from model pyc + alembic/DB reality — verify metadata create / existing migration aligns or add migration if columns missing
- [x] 2.2 Restore `app/api/routers/attendance_summary.py` from router pyc; keep mounted in `main.py` — verify OpenAPI lists attendance-summary routes and unauthorized calls 401/403
- [x] 2.3 Restore identity gates/constants registration for `attendance_summary:read/write` if gaps — verify ops principal can pass gate; non-ops without manage gets 403
- [x] 2.4 Service path: create job → set prior / import export prior → add travel/leave/punch → compute → resolve conflict → confirm → export xlsx — verify API or service tests cover happy path + unconfirmed export rejected

## 3. Chat tool restore（本阶段关键路径）

- [x] 3.1 Restore `attendance_summary_orchestrator.py` (+ query helper if pyc present) and wire `chat.py` / registry / router — verify tool listed for permitted user; sticky job routes leave/attendance clarify still works
- [x] 3.2 Map ChatPage card actions to real `apply_attendance_summary_action` handlers (confirm/void/export/prior/conflict/HR/period/calendar as evidenced) — verify orchestrator tests for at least confirm + merge/set_prior + one conflict resolve
- [x] 3.3 Restore current-job leave-style Q&A for attendance numbers from `compute_result` — verify unit/orchestrator ask for 实出勤 or summary does not invent
- [x] 3.4 End-to-end chat/API smoke: create → prior/cold-start → upload three sources → recompute → confirm → formal export blob — verify unconfirmed formal export rejected; confirmed export downloads xlsx（**Phase A 验收门闩**）

## 4. Frontend page（Phase B — 本阶段延后）

- [x] 4.1 Rebuild `AttendanceSummaryPage.jsx` and restore nav — **deferred**; keep `attendance-summary` redirect to avoid white-screen
- [x] 4.2 Chat blob helpers in `api.js` (`exportAttendanceSummaryXlsx` / `previewAttendanceSummaryXlsx`) hit `/attendance-summary/jobs/.../export|preview.xlsx` — page-oriented clients still **deferred**
- [x] 4.3 Re-enable `AttendanceSummaryJobCard` against live actions — verify card renders and one action round-trips（仍属 Phase A，依赖 3.2/3.4）

## 5. Evidence-backed increments（对话可触达者优先）

- [x] 5.1 Period/month choice where evidenced via card actions — verify non-default month bounds compute/export
- [x] 5.2 Calendar confirm/edit where evidenced via card — verify compute uses confirmed calendar
- [x] 5.3 Punch×travel / base-site clip / half-leave rules in compute pyc — verify ≥1 unit scenario
- [x] 5.4 Audit/preview workbook distinction if evidenced — verify preview ≠ formal prior export

## 6. Hardening（Phase A 最小集）

- [x] 6.1 Add/repair tests for chat/API restore path (create→compute→confirm→export) — related pytest selection green
- [x] 6.2 Ensure attendance `.py` sources (not only pyc) are git-trackable for Phase A commit — page `.jsx` may wait for Phase B
