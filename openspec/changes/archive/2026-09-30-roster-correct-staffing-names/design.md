## Context

See proposal.md — Why. Today `parse_daily_report` emits raw name tokens from 【公司人员】 and 「我司人员」 cells; `suspected_name_split` only warns on short/long pairs inside the batch. `app/staffing/roster.py` loads `KB_STAFFING_ROSTER_PATH` (default `./data/staffing_roster.xlsx`) solely for export 部门/职务. Confirm already gates on unresolved warnings.

## Goals / Non-Goals

**Goals:**

- Shared post-parse correction step used by page import and chat staffing upload.
- Unique roster corrections applied before pending rows are stored; unresolved cases become resolvable warnings.
- Reuse existing review/confirm UX patterns; extend resolution payloads for roster cases.

**Non-Goals:**

- Rewriting historical confirmed facts.
- Using roster 部门 to change `person_kind`.
- Building a roster upload UI (file path / ops-provided xlsx is enough for this change).
- Fuzzy/edit-distance matching beyond exact and unique prefix/suffix.

## Decisions

### D1 — Correction after parse, before batch persist

Run `correct_names_against_roster(parse_result, roster)` in the import service path (not inside PDF→grid). Keeps parse pure; chat and `/staffing` share one gate.

**Alternative considered:** Correct inside `_parse_names_from_text` — rejected; harder to unit-test and mixes OCR noise with roster policy.

### D2 — Matching rules (strict uniqueness)

For each internal token `t`:

1. If `t` ∈ roster names → keep.
2. Else let `C = { n in roster | n.startswith(t) or n.endswith(t) }` with `len(n) > len(t)` and length delta ≤ 2 (align with existing split heuristic) → if `|C| == 1`, rewrite to that `n` and emit informational `roster_name_corrected` (auto-resolved).
3. Else emit `roster_name_unresolved` (blocking) with candidates (possibly empty).

Also: if short/long both appear and long ∈ roster and short uniquely maps to long, prefer merging to long (may fold into existing `suspected_name_split` by auto-resolving when roster confirms).

**Alternative:** Auto-pick longest candidate when multiple — rejected; user chose human review when unsure.

### D3 — Missing roster is blocking

Empty/missing roster → single batch-level `roster_unavailable` warning; no silent bypass. Prevents “wrong names still import” when file not deployed.

### D4 — Resolution options

For `roster_name_unresolved`: `select_roster_name` (must be in roster), `rename` (free text — still recommended to be in roster; if free text not in roster, keep as acknowledged exception logged), `discard` (drop token from that day/kind).

### D5 — Prefer 非离职 roster rows

Reuse existing roster loader preference for non-离职 when duplicate names exist.

## Risks / Trade-offs

- [Roster stale / incomplete] → Legitimate people blocked until review or roster update; mitigation: clear warning copy + discard/rename resolutions.
- [Very short tokens e.g. 单字] → Many prefix hits → always unresolved (safe); mitigation: UI shows candidate list capped.
- [Auto-correct wrong unique match] → Rare if delta ≤ 2; mitigation: informational warning visible in batch review; void/re-import if needed.
- [Performance] → Roster ~100 rows, cached by mtime; negligible.

## Migration Plan

1. Ensure `data/staffing_roster.xlsx` (or env path) deployed before enabling in prod.
2. Deploy backend + frontend review fields together.
3. Rollback: feature flag optional — if needed, `KB_STAFFING_ROSTER_ENFORCE=false` to restore pre-change confirm behavior (default true). Record in tasks if implemented; otherwise document ops must keep roster present.

## Open Questions

- Free-text `rename` to a name **not** in roster: allow as explicit override (logged) or require roster membership? Default in tasks: allow with `acknowledged_off_roster` for rare exceptions.
