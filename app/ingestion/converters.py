from __future__ import annotations

import asyncio
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import fitz
import pdfplumber

from app.core.errors import AppError


class NoExtractableContentError(AppError):
    """Raised when a file contains no extractable text (e.g. a scanned PDF)."""


@dataclass
class ConversionResult:
    """Normalized output for any supported source file."""

    markdown: str
    page_count: int | None = None


class FileConverter(ABC):
    """Converts a source file into Markdown before chunking.

    PDFs keep explicit `<!-- PAGE:N -->` markers so citations can still point
    at the original page; pageless formats (Word/Markdown/TXT) use sections.
    """

    @abstractmethod
    def convert(self, file_path: str) -> ConversionResult: ...

    async def convert_async(self, file_path: str) -> ConversionResult:
        """Default async path: run the blocking converter in a worker thread."""
        return await asyncio.to_thread(self.convert, file_path)


class PDFMarkdownConverter(FileConverter):
    """Text/table PDF -> Markdown with page markers."""

    def __init__(self, extract_tables: bool = True) -> None:
        self._extract_tables = extract_tables

    def convert(self, file_path: str) -> ConversionResult:
        try:
            return self._convert(file_path)
        except AppError:
            raise
        except Exception as exc:
            raise AppError(f"PDF 转 Markdown 失败：{exc}") from exc

    def _convert(self, file_path: str) -> ConversionResult:
        try:
            document = fitz.open(file_path)
        except Exception as exc:
            raise AppError(f"无法打开 PDF（文件损坏或非 PDF）：{exc}") from exc
        if document.needs_pass:
            raise AppError("暂不支持加密 PDF，请先移除密码")

        page_tables: dict[int, list[str]] = {}
        if self._extract_tables:
            page_tables = self._extract_tables_to_markdown(file_path)

        parts: list[str] = []
        page_count = document.page_count
        for page_number, page in enumerate(document, start=1):
            text = page.get_text("text").strip()
            table_rows = page_tables.get(page_number, [])
            if not text and not table_rows:
                continue
            parts.append(f"\n\n<!-- PAGE:{page_number} -->\n")
            if text:
                parts.append(text)
                parts.append("\n")
            if table_rows:
                parts.append("\n".join(table_rows))
                parts.append("\n")
        document.close()
        if not "".join(parts).strip():
            raise NoExtractableContentError("未能从 PDF 中提取任何文本或表格内容（可能是扫描件）")
        return ConversionResult(markdown="".join(parts), page_count=page_count)

    @staticmethod
    def _extract_tables_to_markdown(file_path: str) -> dict[int, list[str]]:
        output: dict[int, list[str]] = {}
        try:
            with pdfplumber.open(file_path) as pdf:
                for page_number, page in enumerate(pdf.pages, start=1):
                    rows: list[str] = []
                    for table in page.extract_tables():
                        if not table:
                            continue
                        rows.append(
                            "| "
                            + " | ".join(" " if cell is None else str(cell).replace("\n", " ") for cell in table[0])
                            + " |"
                        )
                        rows.append("|" + "---|" * len(table[0]))
                        for row in table[1:]:
                            rows.append(
                                "| "
                                + " | ".join(" " if cell is None else str(cell).replace("\n", " ") for cell in row)
                                + " |"
                            )
                        rows.append("")
                    if rows:
                        output[page_number] = rows
        except Exception:
            # Table extraction is best-effort; never fail the whole conversion on it.
            return {}
        return output


class DocxMarkdownConverter(FileConverter):
    """Word (.docx) -> Markdown preserving headings and tables in document order."""

    def convert(self, file_path: str) -> ConversionResult:
        try:
            from docx import Document as DocxDocument
            from docx.table import Table
            from docx.text.paragraph import Paragraph
        except ImportError as exc:  # pragma: no cover
            raise AppError("服务端缺少 python-docx 依赖，无法转换 Word 文件") from exc

        try:
            doc = DocxDocument(file_path)
        except Exception as exc:
            raise AppError(f"无法打开 Word 文档（仅支持 .docx）：{exc}") from exc

        parts: list[str] = []

        def flush_paragraph(paragraph: Paragraph) -> None:
            text = paragraph.text.strip()
            if not text:
                return
            style = (paragraph.style.name if paragraph.style else "") or ""
            heading = re.match(r"^Heading\s*(\d+)$", style, re.IGNORECASE)
            if heading:
                level = min(int(heading.group(1)), 6)
                parts.append(f"\n{'#' * level} {text}\n")
            elif "title" in style.lower():
                parts.append(f"\n# {text}\n")
            else:
                parts.append(text)
                parts.append("\n\n")

        def flush_table(table: Table) -> None:
            rows: list[str] = []
            for row_index, row in enumerate(table.rows):
                cells = [cell.text.replace("\n", " ").strip() for cell in row.cells]
                rows.append("| " + " | ".join(cells) + " |")
                if row_index == 0:
                    rows.append("|" + "---|" * len(cells))
            if rows:
                parts.append("\n" + "\n".join(rows) + "\n\n")

        for child in doc.element.body.iterchildren():
            tag = child.tag.split("}")[-1]
            if tag == "p":
                flush_paragraph(Paragraph(child, doc))
            elif tag == "tbl":
                flush_table(Table(child, doc))

        markdown = "".join(parts).strip()
        if not markdown:
            raise AppError("未能从 Word 文档中提取任何内容")
        return ConversionResult(markdown=markdown, page_count=None)


class TextMarkdownConverter(FileConverter):
    """Markdown / plain-text passthrough."""

    def convert(self, file_path: str) -> ConversionResult:
        try:
            markdown = Path(file_path).read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            raise AppError(f"无法读取文本文件：{exc}") from exc
        if not markdown.strip():
            raise AppError("文件内容为空")
        return ConversionResult(markdown=markdown, page_count=None)


class MarkItDownConverter(FileConverter):
    """PPTX / XLSX / HTML / CSV / JSON / XML etc. via Microsoft MarkItDown."""

    def convert(self, file_path: str) -> ConversionResult:
        try:
            from markitdown import MarkItDown
        except ImportError as exc:  # pragma: no cover
            raise AppError("服务端缺少 markitdown 依赖，无法转换该文件格式") from exc
        try:
            converter = MarkItDown()
            result = converter.convert(file_path)
        except AppError:
            raise
        except Exception as exc:
            raise AppError(f"文件转 Markdown 失败（{Path(file_path).suffix.lower()}）：{exc}") from exc
        markdown = (result.text_content or "").strip()
        if not markdown:
            raise AppError("未能从文件中提取任何内容")
        return ConversionResult(markdown=markdown, page_count=None)


SUPPORTED_EXTENSIONS = {
    ".pdf": PDFMarkdownConverter,
    ".docx": DocxMarkdownConverter,
    ".md": TextMarkdownConverter,
    ".markdown": TextMarkdownConverter,
    ".txt": TextMarkdownConverter,
    ".pptx": MarkItDownConverter,
    ".xlsx": MarkItDownConverter,
    ".html": MarkItDownConverter,
    ".htm": MarkItDownConverter,
    ".csv": MarkItDownConverter,
    ".json": MarkItDownConverter,
}

# Image uploads are routed to MinerU OCR rather than plain-text converters, so
# they intentionally live outside SUPPORTED_EXTENSIONS.
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg"})


def converter_for(filename: str) -> FileConverter:
    suffix = Path(filename).suffix.lower()
    factory = SUPPORTED_EXTENSIONS.get(suffix)
    if factory is None:
        supported = "、".join(sorted(SUPPORTED_EXTENSIONS))
        raise AppError(f"暂不支持 {suffix or '无扩展名'} 格式；当前支持：{supported}（其他格式请先转为 Markdown）")
    return factory()
