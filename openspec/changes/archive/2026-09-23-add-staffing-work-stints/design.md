## Context

See proposal.md. Attendance facts are daily; `project_summary` already returns `dates[]` per `(person_name, person_kind)`. Original staffing design noted stints as derived continuous runs. No entry/exit event table exists.

## Goals / Non-Goals

**Goals:**

- Pure function: dates → ordered stints `{ index, entry_date, exit_date, days }`.
- Expose on summary API, chat card, StaffingPage table, xlsx 汇总 sheet.
- Gap rule: calendar day difference > 1 starts a new stint.

**Non-Goals:**

- Manual edit of stint boundaries.
- Weekend/holiday-aware “workday adjacency” (use calendar days only).
- New persistence tables or changing fact write path.

## Decisions

### D1 — Gap rule = calendar day

Sort unique ISO dates; walk sequentially; if `next - prev == 1 day` continue stint, else close and open new. Single day ⇒ entry == exit, days == 1.

Alternative: business-day adjacency — rejected for v1 (needs holiday calendar).

### D2 — API shape on each person in summary

```json
{
  "stint_count": 2,
  "stints": [
    {"index": 1, "entry_date": "2026-01-11", "exit_date": "2026-01-13", "days": 3},
    {"index": 2, "entry_date": "2026-03-09", "exit_date": "2026-03-11", "days": 3}
  ]
}
```

`days_on_site` remains `len(dates)` (sum of stint days).

### D3 — Presentation

- Table columns: 进场次数; 工期段 as compact text `1: 01-11~01-13; 2: 03-09~03-11` or expandable list.
- Export: columns `进场次数`, `第1段入`, `第1段出`, … up to max stints in the export set (or one cell with joined text). Prefer joined text + `进场次数` to avoid unbounded columns; if max stints ≤ 5, also emit numbered columns.

### D4 — Shared helper

`app/staffing/stints.py::build_stints(dates: list[str]) -> list[dict]` used by `project_summary` and unit-tested in isolation.

## Risks / Trade-offs

- [Sparse reporting days look like exits] → Document that “出” = last reported on-site day in the run, not HR leave date.
- [Wide export] → Cap numbered columns or use joined cell (D3).

## Migration Plan

1. Add helper + unit tests (1/2/3 stints, single day, empty).
2. Extend summary schema + export.
3. FE table + chat card.
4. No DB migration.

## Open Questions

- Display format preference for many stints (joined vs expandable) — default joined in table, expandable in chat if >3.
