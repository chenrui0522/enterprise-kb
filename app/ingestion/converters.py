from __future__ import annotations

import asyncio
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import fitz
import pdfplumber

from app.core.errors import AppError
from app.ingestion.structure import (
    BLOCK_HEADING,
    BLOCK_LIST,
    BLOCK_PARAGRAPH,
    BLOCK_TABLE,
    Block,
    DocumentStructure,
    degrade_to_paragraphs,
    markdown_table,
    paragraphs_to_structure,
    structure_from_markdown,
    structure_to_markdown,
)


class NoExtractableContentError(AppError):
    """Raised when a file contains no extractable text (e.g. a scanned PDF)."""


@dataclass
class ConversionResult:
    """Normalized output for any supported source file."""

    markdown: str
    page_count: int | None = None
    structure: DocumentStructure | None = None


class FileConverter(ABC):
    """Converts a source file into a normalized structure before chunking.

    PDFs keep explicit `<!-- PAGE:N -->` markers so citations can still point
    at the original page; pageless formats (Word/Markdown/TXT) use sections.
    """

    @abstractmethod
    def convert(self, file_path: str) -> ConversionResult: ...

    async def convert_async(self, file_path: str) -> ConversionResult:
        """Default async path: run the blocking converter in a worker thread."""
        return await asyncio.to_thread(self.convert, file_path)


class PDFMarkdownConverter(FileConverter):
    """Text/table PDF -> document structure with page markers."""

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
        try:
            try:
                structure = self._build_structure(document, file_path)
            except Exception:
                structure = self._fallback_structure(document)
            if not structure.blocks:
                raise NoExtractableContentError(
                    "未能从 PDF 中提取任何文本或表格内容（可能是扫描件）"
                )
            return ConversionResult(
                markdown=structure_to_markdown(structure),
                page_count=document.page_count,
                structure=structure,
            )
        finally:
            document.close()

    def _build_structure(self, document, file_path: str) -> DocumentStructure:
        tables = self._extract_tables_with_bbox(file_path) if self._extract_tables else {}
        blocks: list[Block] = []
        for page_number, page in enumerate(document, start=1):
            page_tables = tables.get(page_number, [])
            table_boxes = [bbox for _, _, bbox in page_tables]
            page_dict = page.get_text("dict")
            body_size = _dominant_font_size(page_dict)
            for raw in page_dict.get("blocks", []):
                if raw.get("type") != 0:
                    continue
                bbox = tuple(raw.get("bbox") or (0.0, 0.0, 0.0, 0.0))
                if _bbox_center_inside(bbox, table_boxes):
                    continue
                spans = [
                    span
                    for line in raw.get("lines", [])
                    for span in line.get("spans", [])
                ]
                text = " ".join(span.get("text", "") for span in spans).strip()
                if not text:
                    continue
                sizes = [float(span.get("size") or 0.0) for span in spans]
                block_type, level = _classify_pdf_block(text, max(sizes or [0.0]), body_size)
                blocks.append(
                    Block(
                        type=block_type,
                        text=text,
                        level=level,
                        page=page_number,
                        y0=float(bbox[1]),
                        x0=float(bbox[0]),
                    )
                )
            for header, rows, bbox in page_tables:
                blocks.append(
                    Block(
                        type=BLOCK_TABLE,
                        header=header,
                        rows=rows,
                        text=markdown_table(header, rows),
                        page=page_number,
                        y0=float(bbox[1]),
                        x0=float(bbox[0]),
                    )
                )
        blocks.sort(key=lambda item: (item.page, item.y0, item.x0))
        return DocumentStructure(blocks=blocks, page_count=document.page_count)

    def _fallback_structure(self, document) -> DocumentStructure:
        paragraphs: list[tuple[int, str]] = []
        for page_number, page in enumerate(document, start=1):
            text = page.get_text("text").strip()
            if text:
                paragraphs.append((page_number, text))
        structure = degrade_to_paragraphs(paragraphs_to_structure(paragraphs))
        structure.page_count = document.page_count
        return structure

    @staticmethod
    def _extract_tables_with_bbox(file_path: str) -> dict[int, list[tuple[list[str], list[list[str]], tuple]]]:
        output: dict[int, list[tuple[list[str], list[list[str]], tuple]]] = {}
        try:
            with pdfplumber.open(file_path) as pdf:
                for page_number, page in enumerate(pdf.pages, start=1):
                    items: list[tuple[list[str], list[list[str]], tuple]] = []
                    try:
                        found = page.find_tables()
                    except Exception:
                        found = []
                    for table in found:
                        raw_rows = table.extract()
                        if not raw_rows:
                            continue
                        rows = [[_clean_cell(cell) for cell in row] for row in raw_rows]
                        header = rows[0]
                        if not any(header):
                            continue
                        items.append((header, rows[1:], tuple(table.bbox)))
                    if items:
                        output[page_number] = items
        except Exception:
            # Table extraction is best-effort; never fail the whole conversion on it.
            return {}
        return output


class DocxMarkdownConverter(FileConverter):
    """Word (.docx) -> structure preserving heading levels and table order."""

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

        try:
            structure = self._build_structure(doc, Paragraph, Table)
        except AppError:
            raise
        except Exception:
            structure = self._fallback_structure(doc)

        markdown = structure_to_markdown(structure)
        if not markdown.strip():
            raise AppError("未能从 Word 文档中提取任何内容")
        return ConversionResult(markdown=markdown, page_count=None, structure=structure)

    def _build_structure(self, doc, paragraph_cls, table_cls) -> DocumentStructure:
        blocks: list[Block] = []
        pending_list: list[str] = []

        def flush_list() -> None:
            if pending_list:
                blocks.append(
                    Block(
                        type=BLOCK_LIST,
                        items=list(pending_list),
                        text="\n".join(pending_list),
                    )
                )
                pending_list.clear()

        for child in doc.element.body.iterchildren():
            tag = child.tag.split("}")[-1]
            if tag == "p":
                paragraph = paragraph_cls(child, doc)
                text = paragraph.text.strip()
                if not text:
                    continue
                style = paragraph.style
                style_name = (style.name if style is not None else "") or ""
                style_id = (getattr(style, "style_id", "") or "") if style is not None else ""
                level = _docx_heading_level(style_name, style_id)
                if level:
                    flush_list()
                    blocks.append(Block(type=BLOCK_HEADING, text=text, level=level))
                elif _is_list_style(style_name):
                    pending_list.append(text)
                else:
                    flush_list()
                    blocks.append(Block(type=BLOCK_PARAGRAPH, text=text))
            elif tag == "tbl":
                flush_list()
                rows = _docx_table_rows(table_cls(child, doc))
                if rows:
                    blocks.append(
                        Block(
                            type=BLOCK_TABLE,
                            header=rows[0],
                            rows=rows[1:],
                            text=markdown_table(rows[0], rows[1:]),
                        )
                    )
        flush_list()
        if not blocks:
            raise AppError("未能从 Word 文档中提取任何内容")
        return DocumentStructure(blocks=blocks)

    @staticmethod
    def _fallback_structure(doc) -> DocumentStructure:
        paragraphs = [
            (0, paragraph.text.strip())
            for paragraph in doc.paragraphs
            if paragraph.text.strip()
        ]
        return degrade_to_paragraphs(paragraphs_to_structure(paragraphs))


class TextMarkdownConverter(FileConverter):
    """Markdown / plain-text passthrough."""

    def convert(self, file_path: str) -> ConversionResult:
        try:
            markdown = Path(file_path).read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            raise AppError(f"无法读取文本文件：{exc}") from exc
        if not markdown.strip():
            raise AppError("文件内容为空")
        structure = _structure_or_degrade(markdown)
        return ConversionResult(markdown=markdown, page_count=None, structure=structure)


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
        structure = _structure_or_degrade(markdown)
        return ConversionResult(markdown=markdown, page_count=None, structure=structure)


def _structure_or_degrade(markdown: str) -> DocumentStructure:
    structure = structure_from_markdown(markdown)
    if not structure.blocks:
        structure = degrade_to_paragraphs(paragraphs_to_structure([(0, markdown)]))
    return structure


def _docx_heading_level(style_name: str, style_id: str) -> int:
    pattern = re.compile(r"(?:heading|标题)\s*([1-6])", re.IGNORECASE)
    for value in (style_name, style_id):
        match = pattern.search(value or "")
        if match:
            return int(match.group(1))
    if (style_name or "").strip().lower() in {"title", "标题"}:
        return 1
    return 0


def _is_list_style(style_name: str) -> bool:
    name = (style_name or "").strip().lower()
    return name.startswith("list") or "列表" in name


def _docx_table_rows(table) -> list[list[str]]:
    rows: list[list[str]] = []
    previous_row_cells: dict[int, object] = {}
    for row in table.rows:
        cells: list[str] = []
        seen_cells: list[object] = []
        for column, cell in enumerate(row.cells):
            marker = cell._tc
            text = cell.text.replace("\n", " ").strip()
            duplicated = any(marker is seen for seen in seen_cells) or previous_row_cells.get(column) is marker
            if duplicated:
                text = ""
            else:
                seen_cells.append(marker)
            previous_row_cells[column] = marker
            cells.append(text)
        rows.append(cells)
    return rows

def _dominant_font_size(page_dict: dict) -> float:
    counts: dict[float, int] = {}
    for raw in page_dict.get("blocks", []):
        if raw.get("type") != 0:
            continue
        for line in raw.get("lines", []):
            for span in line.get("spans", []):
                size = round(float(span.get("size") or 0.0), 1)
                text = span.get("text") or ""
                counts[size] = counts.get(size, 0) + len(text)
    if not counts:
        return 0.0
    return max(counts, key=counts.get)


def _classify_pdf_block(text: str, size: float, body_size: float) -> tuple[str, int]:
    if body_size and size and len(text) <= 80 and size >= body_size * 1.12:
        ratio = size / body_size
        if ratio >= 1.6:
            return BLOCK_HEADING, 1
        if ratio >= 1.35:
            return BLOCK_HEADING, 2
        return BLOCK_HEADING, 3
    return BLOCK_PARAGRAPH, 0


def _bbox_center_inside(bbox: tuple, boxes: list[tuple]) -> bool:
    center_x = (float(bbox[0]) + float(bbox[2])) / 2
    center_y = (float(bbox[1]) + float(bbox[3])) / 2
    for box in boxes:
        if (
            float(box[0]) - 1 <= center_x <= float(box[2]) + 1
            and float(box[1]) - 1 <= center_y <= float(box[3]) + 1
        ):
            return True
    return False


def _clean_cell(cell) -> str:
    if cell is None:
        return ""
    return str(cell).replace("\n", " ").strip()


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
        raise AppError(
            f"暂不支持 {suffix or '无扩展名'} 格式；当前支持：{supported}（其他格式请先转为 Markdown）"
        )
    return factory()