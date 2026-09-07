from __future__ import annotations

from abc import ABC, abstractmethod

import fitz
import pdfplumber

from app.core.errors import AppError
from app.ingestion.models import ParsedPage


class PDFParser(ABC):
    """Parser abstraction so future OCR/complex-layout parsers can be swapped in."""

    @abstractmethod
    def parse(self, file_path: str) -> list[ParsedPage]: ...


class TextPdfParser(PDFParser):
    """Extract text (and optional tables) from text-based PDFs."""

    def __init__(self, extract_tables: bool = True) -> None:
        self._extract_tables = extract_tables

    def parse(self, file_path: str) -> list[ParsedPage]:
        try:
            return self._parse(file_path)
        except AppError:
            raise
        except Exception as exc:
            raise AppError(f"PDF 解析失败：{exc}") from exc

    def _parse(self, file_path: str) -> list[ParsedPage]:
        pages: list[ParsedPage] = []
        try:
            document = fitz.open(file_path)
        except Exception as exc:
            raise AppError(f"无法打开 PDF（文件损坏或非 PDF）：{exc}") from exc
        if document.needs_pass:
            raise AppError("暂不支持加密 PDF，请先移除密码")

        table_pages: dict[int, str] = {}
        if self._extract_tables:
            table_pages = self._extract_tables_text(file_path)

        for page_number, page in enumerate(document, start=1):
            text = page.get_text("text").strip()
            table_text = table_pages.get(page_number, "")
            combined = "\n".join(part for part in (text, table_text) if part)
            if combined.strip():
                pages.append(ParsedPage(page_number=page_number, text=combined.strip()))
        document.close()
        return pages

    @staticmethod
    def _extract_tables_text(file_path: str) -> dict[int, str]:
        output: dict[int, str] = {}
        try:
            with pdfplumber.open(file_path) as pdf:
                for page_number, page in enumerate(pdf.pages, start=1):
                    rows: list[str] = []
                    for table in page.extract_tables():
                        for row in table:
                            cells = [str(cell).replace("\n", " ") if cell is not None else "" for cell in row]
                            if any(cells):
                                rows.append(" | ".join(cells))
                    if rows:
                        output[page_number] = "\n".join(rows)
        except Exception:
            # Table extraction is best-effort; never fail the whole document on it.
            return {}
        return output
