"""Reverse-parse Taiyuan official leave-ledger export xlsx into person rows."""

from __future__ import annotations

import io
from datetime import date, datetime
from typing import Any

from openpyxl import load_workbook

from app.core.errors import AppError
from app.leave_ledger.export import HEADER_ROW1, HEADER_ROW2

ORIGIN_EXPORT_IMPORT = "export_import"


def _cell_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if text.endswith(".0") and text.replace(".", "", 1).isdigit():
        # openpyxl sometimes yields "2026.0" for numeric-looking dates stored oddly
        return text
    return text


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def looks_like_official_export(data: bytes) -> bool:
    """Structural detect for Taiyuan dual-header export (not WeCom four-source)."""
    if not data or len(data) < 4 or data[:2] != b"PK":
        return False
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        rows = ws.iter_rows(min_row=1, max_row=2, max_col=18, values_only=True)
        r1 = next(rows, None)
        r2 = next(rows, None)
        wb.close()
    except Exception:
        return False
    if not r1 or not r2:
        return False
    # Anchor on identity + dual OT header labels from export.py
    if _cell_str(r1[0]) != "姓名":
        return False
    if _cell_str(r1[11]) != "合计可调休天数":
        return False
    if _cell_str(r1[15]) != "合计已休天数":
        return False
    if "加班" not in _cell_str(r2[8]):
        return False
    return True


def parse_official_export_xlsx(data: bytes) -> list[dict[str, Any]]:
    """Parse official export bytes into merge-ready person row dicts."""
    if not looks_like_official_export(data):
        raise AppError(
            "不是本系统导出的太原正式调休台账模板，无法导入为 prior",
            status_code=400,
        )
    try:
        wb = load_workbook(io.BytesIO(data), data_only=True)
        ws = wb.active
    except Exception as exc:  # noqa: BLE001
        raise AppError("无法读取调休台账 Excel", status_code=400) from exc

    # Soft-check header row1 labels we care about (already validated by looks_like)
    _ = HEADER_ROW1, HEADER_ROW2

    people: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def _flush() -> None:
        nonlocal current
        if current is None:
            return
        travel = current["travel_segments"]
        ot_days = current["ot_days"]
        leaves = current["leave_segments"]
        if current.get("total_comp_days") is None:
            current["total_comp_days"] = float(
                sum(float(t.get("credit") or 0) for t in travel)
                + sum(float(o.get("credit") or 0) for o in ot_days)
            )
        if current.get("used_comp_days") is None:
            current["used_comp_days"] = float(
                sum(float(lv.get("used_days") or 0) for lv in leaves)
            )
        if current.get("remaining_comp_days") is None:
            current["remaining_comp_days"] = float(
                current["total_comp_days"] - current["used_comp_days"]
            )
        current["travel_comp_days"] = float(
            sum(float(t.get("credit") or 0) for t in travel)
        )
        current["ot_comp_days"] = float(
            sum(float(o.get("credit") or 0) for o in ot_days)
        )
        people.append(current)
        current = None

    for row_idx in range(3, ws.max_row + 1):
        vals = [_cell_str(ws.cell(row_idx, c).value) for c in range(1, 19)]
        nums = [_as_float(ws.cell(row_idx, c).value) for c in range(1, 19)]
        name = vals[0]
        if name:
            _flush()
            current = {
                "person_name": name,
                "center": vals[1],
                "department": vals[2],
                "travel_segments": [],
                "ot_days": [],
                "leave_segments": [],
                "total_comp_days": nums[11],
                "used_comp_days": nums[15],
                "remaining_comp_days": nums[16],
                "remark": vals[17],
            }

        if current is None:
            continue

        # Travel segment row
        if any(vals[i] for i in (3, 4, 5, 6)) or nums[7] is not None:
            current["travel_segments"].append(
                {
                    "system_start": vals[3],
                    "system_end": vals[4],
                    "actual_start": vals[5],
                    "actual_end": vals[6],
                    "credit": float(nums[7] or 0),
                }
            )

        # OT day (export uses same start/end date)
        ot_date = (vals[8] or vals[9]).replace("(法定)", "").strip()
        if ot_date and (nums[10] is not None and float(nums[10]) > 0):
            current["ot_days"].append(
                {
                    "date": ot_date,
                    "credit": float(nums[10]),
                    "holiday": "(法定)" in (vals[8] + vals[9]),
                }
            )

        # Leave segment
        if vals[12] or vals[13] or (nums[14] is not None and float(nums[14]) != 0):
            current["leave_segments"].append(
                {
                    "start": vals[12],
                    "end": vals[13],
                    "used_days": float(nums[14] or 0),
                }
            )

    _flush()
    wb.close()

    if not people:
        raise AppError("导出台账中没有可识别的人员行", status_code=400)
    return people
