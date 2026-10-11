## Context

See proposal.md - Why. Domain stack already runs via recovered `app/attendance_summary/*` and chat tool path (`restore-attendance-summary-ledger` Phase A). Latest export vs `26年8月太原考勤汇总表jm.xlsx` still shows ~25 exact / ~48 red-box diffs. Conversation rules (base-site clip, late depart, leave-as-travel, departed cutoff, calendar 8/8+8/22, manual non-work punch resolutions) exist in bytecode/behavior but are under-specified in main specs. Empty shell change `attendance-travel-base-punch-clip` overlaps naming only.

## Goals / Non-Goals

**Goals:**

- Encode conversation-proven, ruleable behaviors as normative requirements and implement/fix gaps against them.
- Keep a maintainable **exemption list** for correct-ledger manual cells.
- Transition path: temporary default base site 太原 → roster field wins → remove force default.
- Chat can apply `present` / `full_day` / `ignore` for non-work punch blockers.

**Non-Goals:**

- Byte-identical match to every correct-ledger cell.
- Auto-resolving non-work punches without operator action.
- Rebuilding AttendanceSummaryPage (Phase B).
- Closing every empty attendance-* change in the same PR.

## Decisions

1. **Truth for acceptance**  
   Ruleable subset of correct ledger + same inputs/resolutions/calendar. Manual exceptions live in an explicit list (markdown or JSON fixture), cited in compare report.  
   Alternative: treat entire correct ledger as MUST — rejected (user: 含手工例外).

2. **Where rules live**  
   Prefer adjusting `compute` / `locations` / `parse` behavior to match specs; keep service/orchestrator as wiring. Do not invent a parallel calculator.

3. **Base site transition**  
   Config or job flag: `default_base_site` (太原) used only when roster `base_site` empty. When roster field populated, always prefer roster. Document removal of “force all 太原” once roster data quality is accepted.  
   Alternative: keep forcing all rows to 太原 — rejected for post-roster phase.

4. **Non-work punch**  
   Remain blocking + manual prefer. Seed from existing `非出勤日打卡-人工决议.json` for Aug-2026 regression only; production path stays operator-driven in chat/API.

5. **Regression harness**  
   Reuse/extend `_compare_att_xlsx.py` (or pytest wrapping it): load system export + correct ledger, apply exemption list, fail on non-exempt red-box/day diffs for selected columns (至少 应出勤/实出勤/国内出差/国外出差/假勤分列/迟到/缺卡/旷工).

6. **Relation to empty changes**  
   This change is the normative home for travel/base clip + related conversation rules. It **supersedes** the empty shell `attendance-travel-base-punch-clip` (no proposal/specs/tasks there). Closing or archiving that directory is a separate cleanup step and is **not** required in this PR.

## Risks / Trade-offs

- [Risk] Correct ledger “manual” vs “rule bug” misclassified → Mitigation: exemption list requires short reason; default is ruleable (must fix).  
- [Risk] Late-depart / clip edge cases overfit Aug-2026 → Mitigation: scenario tests with synthetic rows, not only one month file.  
- [Risk] Default 太原 hides multi-site errors → Mitigation: warn when default applied; remove force when roster ready.  
- [Risk] Chat prefer labels drift from domain → Mitigation: single enum shared or explicit mapping table in orchestrator tests.

## Migration Plan

1. Land specs + exemption list + failing compare gate (or xfail with tracked gaps).  
2. Implement compute/parse gaps; re-run Aug-2026 sources + resolutions + calendar.  
3. Shrink non-exempt diffs; update exemptions only with reason.  
4. When roster carries base_site: turn off force-all; keep default-only-for-empty.  
5. Rollback = revert commit; prior exports remain historical.

## Open Questions

（无阻塞项 — 真源策略、驻地过渡、非出勤日人工决议已确认。）

## Deferred（后续改规则时纳入，本期不实现）

1. **生产中心应出勤月历与其它部门不同**  
   运营确认：生产中心人员应出勤天数/应出勤日集合与公司其它部门不一致。  
   2026-08 正确表证据：生产中心（张翔宇、靳占鹏）应出勤 **26**；其余中心/部门多为 **23**；系统 V1 仍全员共用任务月历（23），差额暂以豁免挂账。  
   后续若改应出勤规则，MUST 支持按组织（至少按花名册「生产中心」）使用独立应出勤日集合，MUST NOT 继续假定「全员同一应出勤」。具体多出的日期集合以运营/正确表或排班源为准，落地时再固化场景测试。

## Late decisions（实现中补入）

1. **审批断档后外勤打卡仍计出差**  
   已通过行程结束日 D 后，自 D+1 起连续外勤（`field`，不在公司地点）且未回司时合成国内出差续差；**不要求**与原出差地点文本有交集。不把 `other_company`/驻地公司当续差。证据：张霄鹏 8/31。
