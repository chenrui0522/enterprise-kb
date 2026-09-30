"""Rebuild an Excel-exported daily-report PDF into an in-memory xlsx grid.

The staffing parser only understands workbook cells. This module extracts the
ruled table with pdfplumber (line strategy, then text) and writes every cell
back out, including multi-row headers and blanks. It does not interpret names.
"""

from __future__ import annotations

import io
from datetime import datetime

import pdfplumber
from openpyxl import Workbook

from app.core.errors import AppError

NO_TEXT_LAYER_MESSAGE = (
    "无法解析该 PDF：没有文字层。请上传由 Excel 工作簿导出的 PDF，扫描件和拍照件请先另存为 .xlsx"
)
PDF_OPEN_MESSAGE = "无法解析该 PDF：请上传由 Excel 工作簿导出、带文字层的项目日报"

_LINE_SETTINGS = {
    "vertical_strategy": "lines",
    "horizontal_strategy": "lines",
    "snap_tolerance": 3,
    "join_tolerance": 3,
    "intersection_tolerance": 5,
}
_TEXT_SETTINGS = {
    "vertical_strategy": "text",
    "horizontal_strategy": "text",
}
_DATE_FORMATS = (
    "%Y/%m/%d",
    "%Y-%m-%d",
    "%Y.%m.%d",
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y.%m.%d %H:%M:%S",
    "%Y年%m月%d日",
)


class UnreadableStaffingPdf(Exception):
    """A text-layer PDF whose table cannot be stitched into one daily-report grid."""


def looks_like_pdf(data: bytes, filename: str = "") -> bool:
    if filename.lower().endswith(".pdf"):
        return True
    return data.startswith(b"%PDF")


def extract_pdf_grid(data: bytes) -> list[list[str]]:
    """Return the stitched cell grid. Raises AppError or UnreadableStaffingPdf."""
    pages = _read_pages(data)
    if not any(text.strip() for text, _grid in pages):
        raise AppError(NO_TEXT_LAYER_MESSAGE, status_code=415)
    grids = [grid for _text, grid in pages if grid]
    if not grids:
        raise UnreadableStaffingPdf("未抽出表格")
    return _stitch(grids)


def pdf_to_xlsx_bytes(data: bytes) -> bytes:
    return _grid_to_xlsx(extract_pdf_grid(data))


def _read_pages(data: bytes) -> list[tuple[str, list[list[str]]]]:
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if not pdf.pages:
                raise AppError(PDF_OPEN_MESSAGE, status_code=415)
            return [(page.extract_text() or "", _page_grid(page)) for page in pdf.pages]
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AppError(PDF_OPEN_MESSAGE, status_code=415) from exc


def _page_grid(page) -> list[list[str]]:
    tables = page.extract_tables(_LINE_SETTINGS) or []
    if not _usable(tables):
        tables = page.extract_tables(_TEXT_SETTINGS) or []
    best: list[list[str]] = []
    best_score = 0
    for table in tables:
        cleaned = _clean_table(table)
        score = sum(1 for row in cleaned for cell in row if cell)
        if score > best_score:
            best = cleaned
            best_score = score
    return best


def _usable(tables) -> bool:
    for table in tables:
        cleaned = _clean_table(table)
        width = max((len(row) for row in cleaned), default=0)
        nonempty = sum(1 for row in cleaned for cell in row if cell)
        if width >= 2 and nonempty >= 2:
            return True
    return False


def _clean_table(table) -> list[list[str]]:
    return [["" if cell is None else str(cell).strip() for cell in row] for row in table or []]


def _stitch(pages: list[list[list[str]]]) -> list[list[str]]:
    first = pages[0]
    header = _header_block(first)
    date_col = _date_column(header)
    combined = [list(row) for row in first]
    for page in pages[1:]:
        if not _page_has_date_column(page, date_col):
            raise UnreadableStaffingPdf("后续页没有日期列")
        rows = page
        if header and _prefix_equals(rows, header):
            rows = rows[len(header) :]
        combined.extend(list(row) for row in rows)
    return combined


def _header_block(rows: list[list[str]]) -> list[list[str]]:
    """Rows before the first cell that is itself a calendar date."""
    for index, row in enumerate(rows):
        if any(_parse_date(cell) for cell in row):
            return rows[:index]
    return list(rows)


def _date_column(header: list[list[str]]) -> int | None:
    for row in header:
        for index, cell in enumerate(row):
            if "日期" in cell:
                return index
    return None


def _page_has_date_column(rows: list[list[str]], date_col: int | None) -> bool:
    if any("日期" in cell for row in rows for cell in row):
        return True
    if date_col is None:
        return False
    return any(date_col < len(row) and _parse_date(row[date_col]) for row in rows)


def _prefix_equals(rows: list[list[str]], header: list[list[str]]) -> bool:
    if len(rows) < len(header):
        return False
    width = max(len(row) for row in header + rows[: len(header)])
    for left, right in zip(header, rows, strict=False):
        if _pad(left, width) != _pad(right, width):
            return False
    return True


def _pad(row: list[str], width: int) -> list[str]:
    cells = list(row)
    if len(cells) < width:
        cells.extend([""] * (width - len(cells)))
    return cells[:width]


def _grid_to_xlsx(grid: list[list[str]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    for row_index, row in enumerate(grid, start=1):
        for col_index, cell in enumerate(row, start=1):
            value = _coerce_cell(cell)
            if value is not None:
                sheet.cell(row_index, col_index, value)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _coerce_cell(text: str):
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None
    parsed = _parse_date(raw)
    return parsed if parsed is not None else text


def _parse_date(text: str):
    raw = (text or "").strip()
    if not raw:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None
