## 1. Registry and routing

- [x] 1.1 Register `attendance_summary` /「考勤汇总台账」in chat tools registry with `can_use_attendance_summary` filter; verify `/chat/tools` returns it only when permitted
- [x] 1.2 Extend `route_turn` / sticky helpers so unbound ambiguous leave-or-attendance turns clarify (调休 / 考勤汇总 / 讲解) before creating jobs; verify unit tests for clarify-first and explicit/sticky bypass
- [x] 1.3 Wire affirm paths so choosing 考勤汇总 sets active tool / pending and choosing 调休 keeps leave path; verify no attendance job created until affirm

## 2. Orchestrator and query

- [x] 2.1 Add attendance summary chat orchestrator: create/bind job with year/month (default current month, parse「N 月」, else ask); verify month parsing tests and default-month create
- [x] 2.2 Support multi-attach classify → `upload_source` (travel/leave/punch), role pick when ambiguous, progress card payload; verify missing-role progress updates after sequential uploads
- [x] 2.3 Support prior select / import official export / HR roster upload + resolve actions via tool-action; verify card actions call domain service and refresh state
- [x] 2.4 Support conflict resolve, recompute, confirm (double-confirm), void, export ack; verify confirm blocked without roster/unresolved warnings per domain rules
- [x] 2.5 Add grounded query helper over `compute_result` for person/summary asks when sticky job exists and no new attachments; verify name lookup and no-fabricate when empty

## 3. Chat API wiring

- [x] 3.1 Dispatch `attendance_summary` from `/chat/stream` and `/chat/tool-action` alongside leave/staffing; verify unauthorized principal gets denied
- [x] 3.2 Persist `tool_state.attendance_summary` sticky `job_id` (and pending flags) on conversation; verify sticky survives clearing composer tool selection

## 4. Frontend

- [x] 4.1 Show「考勤汇总台账」in ChatPage tool dropdown when `can_attendance_summary`; verify hidden without permission
- [x] 4.2 Add `AttendanceSummaryJobCard` (progress, roles, prior/HR/conflict actions, confirm/void/export) and render for card type `attendance_summary_job`; verify export triggers attendance-summary export download
- [x] 4.3 Handle clarify UI choices for leave vs attendance vs 讲解; verify selecting attendance continues workflow in-session

## 5. Tests and docs

- [x] 5.1 Add backend tests covering registry visibility, clarify-first routing, month default/parse, sticky query, and one confirm/export path smoke
- [x] 5.2 Update clerk-facing docs (or short attendance chat note) that dialogue can run full attendance summary; verify doc mentions clarify vs 调休 and default month
- [x] 5.3 Run `openspec validate chat-attendance-summary-tool` (or project equivalent) and fix artifact issues until clean
