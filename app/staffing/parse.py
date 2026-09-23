"""Parse project daily-report workbooks for internal staffing."""

from __future__ import annotations

import io
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

from openpyxl import load_workbook

from app.core.errors import AppError

KIND_FORMAL = "internal_formal"
KIND_CONTRACT = "internal_contract"

_NAME_SPLIT = re.compile(r"[、,，/；;|\s]+")
_COMPANY_BLOCK = re.compile(r"【公司人员】[：:](.*?)(?=【|$)")
_OUTSOURCE_BLOCK = re.compile(r"【外包人员】")  # detect only; content ignored
_CN_NAME = re.compile(r"^[\u4e00-\u9fff]{2,4}$")
_PROJECT_CODE = re.compile(r"(?<!\d)(\d{3,6})(?!\d)")


@dataclass
class ParsedPersonDay:
    work_date: str  # ISO date
    person_name: str
    person_kind: str
    stage: str | None = None
    source_row: int | None = None


@dataclass
class ParseWarning:
    code: str
    message: str
    row: int | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParseResult:
    title_text: str
    rows: list[ParsedPersonDay]
    warnings: list[ParseWarning]
    raw_day_count: int
    filename_codes: list[str]


def is_ooxml_xlsx(data: bytes) -> bool:
    return len(data) >= 4 and data[:2] == b"PK"


def extract_project_codes(*texts: str) -> list[str]:
    found: list[str] = []
    for text in texts:
        if not text:
            continue
        for m in _PROJECT_CODE.finditer(text):
            code = m.group(1)
            if code not in found:
                found.append(code)
    return found


def _cell_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.isoformat()
    return str(value).replace("\n", " ").strip()


def _parse_names_from_text(text: str) -> tuple[list[str], list[str]]:
    """Return (clean_names, ambiguous_tokens)."""
    names: list[str] = []
    ambiguous: list[str] = []
    cleaned = re.sub(r"\d+\s*人", " ", text)
    cleaned = re.sub(r"[（(][^）)]*[）)]", " ", cleaned)
    for part in _NAME_SPLIT.split(cleaned):
        token = part.strip(" ，,。；;:：")
        if not token or token in {"公司人员", "外包人员", "无"}:
            continue
        if _CN_NAME.fullmatch(token):
            if token.endswith("工") and len(token) >= 3:
                ambiguous.append(token)
            if token not in names:
                names.append(token)
        elif re.search(r"[\u4e00-\u9fff]", token) and 2 <= len(token) <= 6:
            # e.g. 王磊工
            ambiguous.append(token)
            if token not in names:
                names.append(token)
    return names, ambiguous


def _extract_formal_names(personnel_text: str) -> tuple[list[str], list[str]]:
    text = personnel_text.replace("\n", " ")
    m = _COMPANY_BLOCK.search(text)
    if not m:
        # Fallback: leading names before 外包 marker
        if _OUTSOURCE_BLOCK.search(text) and "公司" not in text:
            return [], []
        if "【公司人员】" not in text and "公司人员" not in text:
            return [], []
        return [], []
    return _parse_names_from_text(m.group(1))


def _find_columns(ws) -> tuple[int | None, int | None, list[int], int]:
    """Return (date_col, personnel_col, contract_name_cols, data_start_row) 1-based."""
    date_col = None
    personnel_col = None
    contract_cols: list[int] = []
    header_end = 1
    max_scan = min(ws.max_row or 1, 15)
    max_col = min(ws.max_column or 1, 40)

    for r in range(1, max_scan + 1):
        for c in range(1, max_col + 1):
            val = _cell_str(ws.cell(r, c).value)
            if not val:
                continue
            if date_col is None and val == "日期":
                date_col = c
                header_end = max(header_end, r)
            if personnel_col is None and "现场施工人员" in val:
                personnel_col = c
                header_end = max(header_end, r)
            if "我司人员" in val:
                contract_cols.append(c)
                header_end = max(header_end, r)

    # Also catch name sub-columns under 我司人员 (e.g. K7=姓名 next to K6)
    for r in range(1, max_scan + 1):
        for c in range(1, max_col + 1):
            val = _cell_str(ws.cell(r, c).value)
            if val != "姓名":
                continue
            # look upward/left for 我司人员
            for rr in range(max(1, r - 3), r + 1):
                for cc in range(max(1, c - 2), c + 1):
                    if "我司人员" in _cell_str(ws.cell(rr, cc).value):
                        if c not in contract_cols:
                            contract_cols.append(c)
                        header_end = max(header_end, r)

    data_start = header_end + 1
    # Sample sheets often have 4-7 header rows
    if date_col and data_start < 8:
        # bump if row data_start still looks like header
        probe = _cell_str(ws.cell(data_start, date_col).value)
        if probe in {"", "合计", "姓名"}:
            data_start = 8
    return date_col, personnel_col, sorted(set(contract_cols)), data_start


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def parse_daily_report(data: bytes, filename: str = "") -> ParseResult:
    if not is_ooxml_xlsx(data):
        raise AppError(
            "无法解析该文件：请另存为标准 Excel 工作簿（.xlsx）后再上传",
            status_code=415,
        )

    try:
        wb = load_workbook(io.BytesIO(data), data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise AppError(
            "无法解析该文件：请另存为标准 Excel 工作簿（.xlsx）后再上传",
            status_code=415,
        ) from exc

    ws = wb.active
    title_text = _cell_str(ws.cell(1, 1).value)
    if ws.max_row and ws.max_row >= 3:
        title_text = title_text or _cell_str(ws.cell(3, 1).value)
        if not title_text or "日报" in title_text and len(title_text) < 8:
            title_text = _cell_str(ws.cell(3, 1).value)

    date_col, personnel_col, contract_cols, data_start = _find_columns(ws)
    warnings: list[ParseWarning] = []
    if date_col is None or personnel_col is None:
        warnings.append(
            ParseWarning(
                code="unreadable_workbook",
                message="未找到「日期」或「现场施工人员」列",
            )
        )
        return ParseResult(
            title_text=title_text,
            rows=[],
            warnings=warnings,
            raw_day_count=0,
            filename_codes=extract_project_codes(filename, title_text),
        )

    # stage column optional
    stage_col = None
    for c in range(1, min(ws.max_column or 1, 20) + 1):
        for r in range(1, 8):
            if _cell_str(ws.cell(r, c).value) == "当前阶段":
                stage_col = c
                break

    day_people: dict[str, dict[str, set[str]]] = {}  # date -> name -> kinds
    day_rows: dict[str, list[int]] = {}
    raw_day_count = 0

    for r in range(data_start, (ws.max_row or 0) + 1):
        dval = ws.cell(r, date_col).value
        work_date = _as_date(dval)
        if work_date is None:
            # skip empty trailing rows
            personnel = _cell_str(ws.cell(r, personnel_col).value)
            if not personnel and all(
                not _cell_str(ws.cell(r, c).value) for c in contract_cols[:1]
            ):
                continue
            warnings.append(
                ParseWarning(code="missing_date", message="数据行缺少可识别日期", row=r)
            )
            continue

        raw_day_count += 1
        iso = work_date.isoformat()
        day_rows.setdefault(iso, []).append(r)
        stage = _cell_str(ws.cell(r, stage_col).value) if stage_col else None

        personnel_text = _cell_str(ws.cell(r, personnel_col).value)
        formal, amb_f = _extract_formal_names(personnel_text)
        for token in amb_f:
            warnings.append(
                ParseWarning(
                    code="ambiguous_person_token",
                    message=f"人名令牌可能含称谓或噪声：{token}",
                    row=r,
                    detail={"token": token},
                )
            )

        contract: list[str] = []
        for c in contract_cols:
            names, amb_c = _parse_names_from_text(_cell_str(ws.cell(r, c).value))
            for token in amb_c:
                warnings.append(
                    ParseWarning(
                        code="ambiguous_person_token",
                        message=f"人名令牌可能含称谓或噪声：{token}",
                        row=r,
                        detail={"token": token},
                    )
                )
            for n in names:
                if n not in contract:
                    contract.append(n)

        # Keep both kinds when present; do not silently formal-win.
        bucket = day_people.setdefault(iso, {})
        for n in contract:
            bucket.setdefault(n, set()).add(KIND_CONTRACT)
        for n in formal:
            bucket.setdefault(n, set()).add(KIND_FORMAL)

        if formal and contract:
            formal_set, contract_set = set(formal), set(contract)
            if formal_set.isdisjoint(contract_set):
                warnings.append(
                    ParseWarning(
                        code="source_mismatch",
                        message="当日公司人员段与我司姓名格名单无交集",
                        row=r,
                        detail={"formal": formal, "contract": contract, "stage": stage},
                    )
                )

    # same-day multi-row already merged; flag if >1 source rows
    for iso, rows in day_rows.items():
        if len(rows) > 1:
            warnings.append(
                ParseWarning(
                    code="same_day_conflict",
                    message=f"同一日期出现 {len(rows)} 行，已按人去重合并",
                    detail={"date": iso, "rows": rows},
                )
            )

    parsed_rows: list[ParsedPersonDay] = []
    kinds_by_name: dict[str, set[str]] = {}
    for iso, people in sorted(day_people.items()):
        src = day_rows.get(iso, [None])[0]
        for name, kinds in people.items():
            kinds_by_name.setdefault(name, set()).update(kinds)
            for kind in sorted(kinds):
                parsed_rows.append(
                    ParsedPersonDay(
                        work_date=iso,
                        person_name=name,
                        person_kind=kind,
                        source_row=src,
                    )
                )

    for name, kinds in sorted(kinds_by_name.items()):
        if KIND_FORMAL in kinds and KIND_CONTRACT in kinds:
            warnings.append(
                ParseWarning(
                    code="name_kind_collision",
                    message=(
                        f"「{name}」同时出现正式我司与我司·外包性质，"
                        "可能不是同一人，请人工判定"
                    ),
                    detail={"person_name": name, "kinds": sorted(kinds)},
                )
            )

    return ParseResult(
        title_text=title_text,
        rows=parsed_rows,
        warnings=warnings,
        raw_day_count=raw_day_count,
        filename_codes=extract_project_codes(filename, title_text),
    )


def parse_result_to_dict(result: ParseResult) -> dict[str, Any]:
    return {
        "title_text": result.title_text,
        "rows": [asdict(r) for r in result.rows],
        "warnings": [asdict(w) for w in result.warnings],
        "raw_day_count": result.raw_day_count,
        "filename_codes": result.filename_codes,
    }
