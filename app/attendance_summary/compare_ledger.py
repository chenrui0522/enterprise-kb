"""Compare system Taiyuan attendance export vs 正确表 with exemption filtering."""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

TALLY_LABELS = [
    "应出勤",
    "实出勤",
    "国内出差",
    "国外出差",
    "居家",
    "事假",
    "年假",
    "病假",
    "产假",
    "婚假",
    "丧假",
    "调休",
    "迟到",
    "缺卡",
    "旷工",
]

LABEL_ALIAS = {
    "产/产检/陪产假": "产假",
    "迟到（次）": "迟到",
    "缺卡（次）": "缺卡",
    "SHI假": "事假",
}

DEFAULT_EXEMPTIONS = (
    Path(__file__).resolve().parent / "correct_ledger_exemptions.json"
)


def _norm_sym(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    if s in {"√", "✓", "☑"}:
        return "√"
    if s in {"￥", "¥"}:
        return "￥"
    if s in {"＄", "$"}:
        return "＄"
    if s in {"×", "x", "X", "✕"}:
        return "×"
    if s in {"★", "*"}:
        return "★"
    return s


def _num(v):
    if v is None or v == "":
        return 0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    if not s:
        return 0
    try:
        return float(s)
    except ValueError:
        return s


def _find_sheet(wb):
    for name in wb.sheetnames:
        if "考勤" in name:
            return wb[name]
    return wb[wb.sheetnames[0]]


def parse_workbook(path: Path) -> dict[str, dict]:
    wb = load_workbook(path, data_only=True)
    ws = _find_sheet(wb)
    header_row = None
    day_cols: dict[int, int] = {}
    tally_cols: dict[str, int] = {}

    for r in range(1, min(10, ws.max_row + 1)):
        vals = [ws.cell(r, c).value for c in range(1, min(60, ws.max_column + 1))]
        if "序号" in vals and any(isinstance(v, datetime) for v in vals):
            header_row = r
            break
    if not header_row:
        raise RuntimeError(f"cannot find header in {path}")

    for c in range(1, ws.max_column + 1):
        val = ws.cell(header_row, c).value
        if isinstance(val, datetime):
            day_cols[val.day] = c
        elif isinstance(val, str) and re.fullmatch(r"\d{1,2}", val.strip()):
            day_cols[int(val.strip())] = c

    for rr in range(header_row, min(header_row + 3, ws.max_row + 1)):
        for c in range(1, ws.max_column + 1):
            lab = ws.cell(rr, c).value
            if not isinstance(lab, str):
                continue
            alias = LABEL_ALIAS.get(lab.strip(), lab.strip())
            if alias in TALLY_LABELS and alias not in tally_cols:
                tally_cols[alias] = c

    name_col = side_col = None
    for r in range(header_row + 1, min(header_row + 8, ws.max_row + 1)):
        for c in range(1, 8):
            if ws.cell(r, c).value == "上班":
                side_col = c
                for cc in range(c - 1, 0, -1):
                    v = ws.cell(r, cc).value
                    if isinstance(v, str) and v.strip() and v.strip() not in (
                        "中心",
                        "岗位",
                        "姓名",
                    ):
                        name_col = cc
                        break
                break
        if name_col and side_col:
            break
    if not name_col or not side_col:
        name_col, side_col = 4, 5

    people: dict[str, dict] = {}
    r = header_row + 1
    while r <= ws.max_row:
        side = ws.cell(r, side_col).value
        name = ws.cell(r, name_col).value
        if side == "上班" and name and str(name).strip():
            pname = str(name).strip()
            pname_key = re.sub(r"[（(].*?离职.*?[）)]", "", pname).strip()
            pname_key = re.sub(r"\s+", "", pname_key)
            in_row = r
            out_row = r + 1
            for rr in (r + 1, r + 2):
                if ws.cell(rr, side_col).value in ("下班", "下"):
                    out_row = rr
                    break
            days = {
                day: (
                    _norm_sym(ws.cell(in_row, col).value),
                    _norm_sym(ws.cell(out_row, col).value),
                )
                for day, col in day_cols.items()
            }
            tallies = {
                lab: _num(ws.cell(in_row, col).value) for lab, col in tally_cols.items()
            }
            people[pname_key] = {
                "name": pname_key,
                "seq": ws.cell(in_row, 1).value,
                "days": days,
                "tallies": tallies,
            }
            r = out_row + 1
            continue
        r += 1
    return people


def load_exemptions(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or DEFAULT_EXEMPTIONS
    data = json.loads(p.read_text(encoding="utf-8"))
    items = data.get("exemptions") or []
    if not isinstance(items, list):
        raise ValueError("exemptions must be a list")
    return items


@dataclass
class DiffItem:
    person: str
    kind: str  # tally | day
    column: str | None = None
    day: int | None = None
    system: Any = None
    correct: Any = None
    exempt: bool = False
    exemption_reason: str | None = None


@dataclass
class CompareResult:
    n_sys: int
    n_cor: int
    exact: list[str] = field(default_factory=list)
    diffs: list[DiffItem] = field(default_factory=list)
    only_sys: list[str] = field(default_factory=list)
    only_cor: list[str] = field(default_factory=list)

    @property
    def non_exempt(self) -> list[DiffItem]:
        return [d for d in self.diffs if not d.exempt]

    @property
    def exempt_count(self) -> int:
        return sum(1 for d in self.diffs if d.exempt)


def _exemption_covers(ex: dict[str, Any], *, person: str, column: str | None, day: int | None) -> str | None:
    if ex.get("person") != person:
        return None
    cols = ex.get("columns") or []
    days = ex.get("days") or []
    reason = str(ex.get("reason") or "exempt")
    if column and cols and column not in cols:
        return None
    if day is not None and days and day not in days:
        # column-only exemption still covers tallies when days listed only for day cells
        if column and cols and column in cols and day is None:
            return reason
        if column and cols and column in cols:
            # tally diffs have day=None
            return reason
        return None
    if day is not None and days and day not in days:
        return None
    if day is not None and days and day in days:
        if cols and column and column not in cols:
            # day cell exemption: allow without column match when column is day-symbol
            if column in ("日格", None) or not cols:
                return reason
        return reason
    if column and cols and column in cols and day is None:
        return reason
    if not cols and not days:
        return reason
    if column and cols and column in cols:
        return reason
    return None


def _match_exemption(
    exemptions: list[dict[str, Any]],
    *,
    person: str,
    column: str | None = None,
    day: int | None = None,
) -> str | None:
    for ex in exemptions:
        if ex.get("person") != person:
            continue
        cols = list(ex.get("columns") or [])
        days = list(ex.get("days") or [])
        reason = str(ex.get("reason") or "exempt")
        if day is None:
            # tally
            if cols and column in cols:
                return reason
            if not cols and not days:
                return reason
        else:
            # day cell
            day_ok = (not days) or (day in days)
            # day-symbol diffs use column "日格"
            col_ok = (not cols) or (column in cols) or (column == "日格")
            if day_ok and col_ok:
                # if columns listed and only tallies intended, still allow day when days listed
                if days and day in days:
                    return reason
                if not days and col_ok:
                    return reason
    return None


def compare_people(
    sys_p: dict[str, dict],
    cor_p: dict[str, dict],
    *,
    exemptions: list[dict[str, Any]] | None = None,
) -> CompareResult:
    exemptions = exemptions or []
    only_sys = sorted(set(sys_p) - set(cor_p))
    only_cor = sorted(set(cor_p) - set(sys_p))
    exact: list[str] = []
    diffs: list[DiffItem] = []

    for name in sorted(set(sys_p) & set(cor_p)):
        s, c = sys_p[name], cor_p[name]
        person_diffs: list[DiffItem] = []
        for lab in TALLY_LABELS:
            sv, cv = s["tallies"].get(lab, 0), c["tallies"].get(lab, 0)
            if isinstance(sv, float) or isinstance(cv, float):
                try:
                    if abs(float(sv) - float(cv)) < 1e-9:
                        continue
                except (TypeError, ValueError):
                    pass
            elif sv == cv:
                continue
            reason = _match_exemption(
                exemptions, person=name, column=lab, day=None
            )
            person_diffs.append(
                DiffItem(
                    person=name,
                    kind="tally",
                    column=lab,
                    system=sv,
                    correct=cv,
                    exempt=bool(reason),
                    exemption_reason=reason,
                )
            )
        for d in sorted(set(s["days"]) | set(c["days"])):
            sd = s["days"].get(d, ("", ""))
            cd = c["days"].get(d, ("", ""))
            if sd == cd:
                continue
            reason = _match_exemption(
                exemptions, person=name, column="日格", day=d
            )
            person_diffs.append(
                DiffItem(
                    person=name,
                    kind="day",
                    column="日格",
                    day=d,
                    system=f"{sd[0]}/{sd[1]}",
                    correct=f"{cd[0]}/{cd[1]}",
                    exempt=bool(reason),
                    exemption_reason=reason,
                )
            )
        if not person_diffs:
            exact.append(name)
        else:
            diffs.extend(person_diffs)

    return CompareResult(
        n_sys=len(sys_p),
        n_cor=len(cor_p),
        exact=exact,
        diffs=diffs,
        only_sys=only_sys,
        only_cor=only_cor,
    )


def compare_files(
    system_xlsx: Path,
    correct_xlsx: Path,
    *,
    exemptions_path: Path | None = None,
) -> CompareResult:
    return compare_people(
        parse_workbook(system_xlsx),
        parse_workbook(correct_xlsx),
        exemptions=load_exemptions(exemptions_path),
    )


def summarize(result: CompareResult) -> dict[str, Any]:
    col_freq = Counter(
        d.column for d in result.non_exempt if d.kind == "tally" and d.column
    )
    return {
        "n_sys": result.n_sys,
        "n_cor": result.n_cor,
        "exact": len(result.exact),
        "non_exempt_diffs": len(result.non_exempt),
        "exempt_diffs": result.exempt_count,
        "only_sys": result.only_sys,
        "only_cor": result.only_cor,
        "non_exempt_tally_columns": dict(col_freq),
        "non_exempt_sample": [
            {
                "person": d.person,
                "kind": d.kind,
                "column": d.column,
                "day": d.day,
                "system": d.system,
                "correct": d.correct,
            }
            for d in result.non_exempt[:30]
        ],
    }
