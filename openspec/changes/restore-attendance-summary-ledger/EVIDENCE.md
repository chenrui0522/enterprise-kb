# Evidence matrix — restore-attendance-summary-ledger

Truth order: archived main specs → `.pyc` symbols/strings → `ChatPage` action ids → unarchived OpenSpec text.

## Recovery technique

| Module | Method | Notes |
|--------|--------|-------|
| `app/models/attendance_summary.py` | **Decompiled** (pycdc) + cleaned | Readable SQLAlchemy models |
| `app/attendance_summary/{calendar,locations,parse,compute,export,service}.py` | **Bytecode-recovered** | `marshal` embed of original 3.12 code objects (`_emit_pyc_modules.py`); decompyle3 unsupported 3.12; pycdc incomplete (`LOAD_FAST_AND_CLEAR` / async) |
| `app/api/routers/attendance_summary.py` | **Bytecode-recovered** | Same marshal embed |
| `app/chat/tools/attendance_summary_{orchestrator,query}.py` | **Bytecode-recovered** | Same marshal embed |
| Identity / chat registry gates | **Reconstructed** | Mirrored leave-ledger pattern + identity-access spec (`ops` subtree) |

## ChatPage action ids (all evidenced in orchestrator pyc)

| Action id | Evidence | Disposition |
|-----------|----------|-------------|
| `attendance_summary.set_prior` | orch strings + ChatPage | **restore** |
| `attendance_summary.confirm_prior` | orch + ChatPage | **restore** |
| `attendance_summary.dismiss_prior` | orch + ChatPage | **restore** |
| `attendance_summary.pick_role` / `pick_role:*` | orch + ChatPage | **restore** |
| `attendance_summary.set_period` / `set_period:YYYY-MM` | orch + ChatPage | **restore** |
| `attendance_summary.confirm_period` | orch + ChatPage | **restore** |
| `attendance_summary.confirm_calendar` | orch + ChatPage | **restore** |
| `attendance_summary.resolve_conflict` | orch + ChatPage | **restore** |
| `attendance_summary.resolve_hr` | orch + ChatPage | **restore** |
| `attendance_summary.ack_data_quality` | orch + ChatPage | **restore** |
| `attendance_summary.recompute` | orch + ChatPage | **restore** |
| `attendance_summary.confirm` | orch + ChatPage | **restore** |
| `attendance_summary.void` | orch + ChatPage | **restore** |
| `attendance_summary.export` | orch + ChatPage | **restore** |
| `attendance_summary.preview_export` | orch + ChatPage | **restore** |

## Pending attendance-* / chat-attendance-* changes

| Change dir | OpenSpec content | Hard evidence (pyc / UI) | Disposition |
|------------|------------------|--------------------------|-------------|
| `chat-attendance-period-choice` | empty (yaml only) | `set_period` / `confirm_period` in orch + ChatPage | **restore** (folded into this change) |
| `attendance-summary-confirm-calendar` | empty | `confirm_calendar`, `calendar_confirmed_at`, `parse_calendar_edit_message` | **restore** |
| `chat-attendance-calendar-edit` | empty | `parse_calendar_edit_message` in calendar pyc; orch calendar prompt | **restore** |
| `attendance-travel-base-punch-clip` | empty | `base_site`, `_location_travel_gate`, `_filter_travels_after_early_return` in compute/locations | **restore** (in compute bytecode) |
| `attendance-punch-travel-half-leave` | empty | half-day leave attrs + travel/punch helpers in compute/parse | **restore** (in compute bytecode) |
| `attendance-required-present-travel-split` | empty | `_add_travel_present`, `_non_company_punch_plan`, `non_company_punch` warnings | **restore** (in compute bytecode) |
| `attendance-summary-audit-workbook` | empty | `preview_export` / `preview.xlsx` distinct from formal export in orch+service | **restore** (preview ≠ formal prior) |
| `attendance-punch-detail-roster-path` | proposal only | no clear punch-detail-path symbols in recovered pyc strings | **defer** |

## Import smoke (venv)

```text
from app.attendance_summary import service, compute, export  → OK
service.create_job / ROLES / export_formal present
compute.compute_month / result_to_dict present
export.build_attendance_summary_xlsx present
models.AttendanceSummaryJob.__tablename__ == attendance_summary_jobs
router routes: 23
orchestrator apply/handle + query.answer_attendance_query → OK
compute_month empty punch smoke: 1 person, required_days=21
```

## Remaining gaps

- Marshal-embedded modules are runnable but not human-editable AST; prefer gradual rewrite to readable Python while keeping pyc as oracle.
- No alembic migration for `attendance_summary_*` tables yet (SQLite metadata create covers tests; add migration when deploying against shared DBs).
- Frontend dedicated page / nav still Phase B (`attendance-summary` redirects home).
- Empty pending change dirs should be archived/superseded after this restore lands.

## Phase A verification (2026-10-10)

- Added `FileDocumentStorage.store_attendance_summary`.
- Pytest green: `tests/test_attendance_summary_{compute,service}.py`, `tests/test_chat_attendance_summary_tool.py`, attendance gate in `tests/test_feature_gates.py` (16 passed).
- Sources under `app/attendance_summary/`, router, orchestrator, query, models are untracked `.py` (not gitignored) ready for commit.
