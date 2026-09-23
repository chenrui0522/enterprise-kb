## 1. Stint derivation

- [x] 1.1 Add `build_stints` helper (calendar-gap rule) and verify unit tests for empty, single day, one run, two runs, three runs
- [x] 1.2 Attach `stint_count` + `stints[]` on each person in `project_summary`; verify summary test with gapped dates

## 2. Export and schemas

- [x] 2.1 Extend `PersonSummaryOut` (and export 汇总 sheet) with stint fields; verify xlsx contains 进场次数 and segment entry/exit info
- [x] 2.2 Pass stints through chat `_summary_card`; verify orchestrator/card payload includes them

## 3. UI

- [x] 3.1 StaffingPage / StaffingSummaryPanel show 进场次数 and stint entry/exit; verify dual-stint person renders two segments
- [x] 3.2 Chat staffing summary card shows the same stint info; verify after confirm with fixture data

## 4. Docs and regression

- [x] 4.1 README note: 工期段由连续在场日自动派生（断日新开段）
- [x] 4.2 Run staffing-related pytest and verify green
