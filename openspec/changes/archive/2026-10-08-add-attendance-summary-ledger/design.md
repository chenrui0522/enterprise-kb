## Context

See proposal.md - Why. Today `app/attendance/` builds a one-row-per-person symbol month sheet from WeCom exports (optional OT) with no job lifecycle, roster, or Taiyuan dual-row template. `leave_ledger` already parses travel/leave/punch xlsx and owns confirm/alert/export patterns under `ops` org gate. Sample gold layout: title + legend + columns A–AZ, two rows per person (上班/下班), day grid F–AJ, summary AK–AZ.

## Goals / Non-Goals

**Goals:**

- Domain module + REST + dedicated page for attendance-summary jobs (upload 3 sources, prior roster, HR diff alerts, compute, review, confirm, export Taiyuan template).
- Reuse leave_ledger parsers where possible; extend for half-day leave text and punch 上班/下班 detail rows.
- Shared mental model with leave-ledger prior: explicit prior job or official export as roster base; HR file only diffs.

**Non-Goals:**

- Chat tool wiring (V1).
- Auto deduction formulas.
- Replacing leave-ledger credit rules.
- Removing `/attendance` 考勤月表 in this change (may coexist).

## Decisions

1. **Separate domain `attendance_summary` (or `attendance_summary_ledger`), not a leave_ledger job subtype**  
   Different output template, roster lifecycle, and tally semantics. Share parse helpers and org-gate style only.  
   Alternative: overload leave_ledger jobs — rejected (confuses credit vs attendance).

2. **Job model**  
   Persist: tenant, year/month, status (`draft`/`computed`/`confirmed`/`voided`), source file refs, roster snapshot, compute result (per-person day cells + summary + remarks), open alerts, resolutions, `prior_job_id` / roster origin, audit. Confirm freezes snapshot for next-month prior.  
   Alternative: stateless regenerate only — rejected (no prior chain, no alert workflow).

3. **Roster: prior confirmed export primary; HR xlsx secondary diffs**  
   Cold start: upload HR roster or blank Taiyuan template with names. Ongoing: select prior confirmed job (or re-import last official export). HR upload produces add/remove/transfer alerts; operator accepts merges before/with recompute.  
   Alternative: HR always replaces — rejected (loses row order/岗位 continuity).

4. **Company work calendar**  
   Tenant-month config of required work dates (or holiday + makeup-work days). Drives 应出勤 count and whether late/missing count. Same calendar for all roster people in V1.  
   Alternative: per-person calendars — out of V1.

5. **Compute pipeline**  
   ```
   roster x calendar
     + approved travel clipped to month
     + approved leave (half-day aware)
     + punch sides (上班/下班)
     -> per half-day attribution
     -> day symbols (both rows for full-day)
     -> summary columns + remarks
     -> conflict alerts
   ```  
   Half-day key: morning ↔ 上班 row, afternoon ↔ 下班 row. Full-day travel/leave paints both rows. Overseas: location keyword list (config). Makeup (`正常(补卡)`): counts as 缺卡次 + remark tag; no auto 扣款.

6. **Conflict alerts block confirm**  
   At least: same calendar day leave ∩ travel. Resolution chooses winning attribution and clears alert; recompute summary. Extendable later (leave ∩ normal punch, ambiguous overseas, etc.).

7. **Permissions**  
   Actions `attendance_summary:read` / `attendance_summary:write`, org subtree `ops` (same as leave_ledger), `users:manage` bypasses org gate. Dedicated feature gate helper (mirror `can_use_leave_ledger`).

8. **Export**  
   `build_attendance_summary_xlsx` aligned to gold template (merges, legend, dual rows, summary headers). Confirmed-only for “正式” download; preview may allow draft xlsx labeled unofficial if useful — prefer confirm-gated formal export like leave-ledger.

9. **Parser reuse**  
   Prefer shared functions from `leave_ledger.parse` with adapters for: leave start/end as `YYYY/M/D 上午|下午`; punch sheet titled 打卡详情 without header row. Keep attendance symbol engine out of leave_ledger credit code.

## Risks / Trade-offs

- [Risk] Incomplete gold filled sheet for regression → Mitigation: unit tests from explored rules + fixture built from jm samples; clerk spot-check one real month.  
- [Risk] Keyword false positive for overseas → Mitigation: configurable list + alert on unknown/empty location when travel present.  
- [Risk] Punch export shape varies (multi-sheet vs detail-only) → Mitigation: support detail layout from sample + existing headered/parse_punch paths.  
- [Risk] Dual product pages confuse users → Mitigation: nav label「考勤汇总台账」; keep or hide 考勤月表 behind same ops perm until retired.  
- [Trade-off] 补卡仍计缺卡 inflates 缺卡列 vs “true missing” → Accepted; remarks distinguish for human 5-quota deduction.

## Migration Plan

1. Schema + calendar/keyword config + compute + export (API).  
2. Page: upload / prior / HR diff / alerts / preview / confirm / download.  
3. Seed default overseas keywords and empty calendar UI for ops.  
4. Rollback: disable routes/nav; leave_ledger and old `/attendance` unaffected.

## Open Questions

- 人事花名册列布局的正式模板（姓名/中心/岗位列名）待首份样例锁定。  
- 居家 `■` 是否 V1 从某源自动产生（提案未要求；可先不自动填）。  
- 「SHI假」图例文案是否固定为事假（模板如此；实现映射事→事假列即可）。
