from __future__ import annotations

import asyncio
import re
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

import fitz
import pdfplumber

from app.core.errors import AppError
from app.core.logging import get_logger
from app.ingestion.images import ImageAsset
from app.ingestion.structure import (
    BLOCK_HEADING,
    BLOCK_LIST,
    BLOCK_PARAGRAPH,
    BLOCK_TABLE,
    Block,
    DocumentStructure,
    PAGE_MARKER,
    TableArtifact,
    degrade_to_paragraphs,
    markdown_table,
    paragraphs_to_structure,
    structure_from_markdown,
    structure_to_markdown,
)


logger = get_logger("ingestion.converters")


class NoExtractableContentError(AppError):
    """Raised when a file contains no extractable text (e.g. a scanned PDF)."""


@dataclass
class ConversionResult:
    """Normalized output for any supported source file."""

    markdown: str
    page_count: int | None = None
    structure: DocumentStructure | None = None
    images: list = field(default_factory=list)
    tables: list[TableArtifact] = field(default_factory=list)
    triage: dict = field(default_factory=dict)
    ocr_pages: list[int] = field(default_factory=list)


class FileConverter(ABC):
    """Converts a source file into a normalized structure before chunking.

    PDFs keep explicit `<!-- PAGE:N -->` markers so citations can still point
    at the original page; pageless formats (Word/Markdown/TXT) use sections.
    """

    #: Stable converter id used in conversion reports and parse-cache keys.
    #: Bump `version` whenever the produced markdown/structure changes meaning
    #: so cached parse results for older versions are never reused.
    name: str = "file"
    version: str = "1"

    @abstractmethod
    def convert(self, file_path: str) -> ConversionResult: ...

    async def convert_async(self, file_path: str) -> ConversionResult:
        """Default async path: run the blocking converter in a worker thread."""
        return await asyncio.to_thread(self.convert, file_path)

    def cache_signature(self) -> dict:
        """Identity of this converter for parse-cache lookups.

        Subclasses add every parameter that changes the produced output; any
        difference yields a different cache key, so stale results are never
        reused after a converter upgrade or a settings change.
        """
        return {"converter": self.name, "version": self.version}


class PDFMarkdownConverter(FileConverter):
    """Text/table PDF -> document structure with page markers."""

    name = "pdf-local"
    version = "1"

    def __init__(self, extract_tables: bool = True) -> None:
        self._extract_tables = extract_tables

    def cache_signature(self) -> dict:
        return {**super().cache_signature(), "extract_tables": self._extract_tables}

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


class HybridPdfConverter(FileConverter):
    """Mixed PDF: text pages locally, pages without a text layer via OCR.

    Only the pages that have no text layer are sent to OCR, so a 200 page
    manual with three scanned appendices keeps its page markers and does not
    lose (or re-parse) the 197 pages that PyMuPDF already reads correctly.
    """

    name = "pdf-hybrid"
    version = "1"

    def __init__(
        self,
        ocr_converter: FileConverter,
        scanned_pages: list[int],
        *,
        max_single_page_ocr: int = 8,
        concurrency: int = 2,
    ) -> None:
        self._ocr = ocr_converter
        self._scanned_pages = sorted({int(page) for page in scanned_pages if int(page) > 0})
        self._max_single_page_ocr = max(int(max_single_page_ocr), 1)
        self._concurrency = max(int(concurrency), 1)

    def cache_signature(self) -> dict:
        return {
            **super().cache_signature(),
            "scanned_pages": self._scanned_pages,
            "ocr": self._ocr.cache_signature(),
        }

    async def convert_async(self, file_path: str) -> ConversionResult:
        if not self._scanned_pages:
            return await PDFMarkdownConverter().convert_async(file_path)

        local = await PDFMarkdownConverter().convert_async(file_path)
        page_count = local.page_count
        groups = _ocr_groups(self._scanned_pages, self._max_single_page_ocr)
        semaphore = asyncio.Semaphore(self._concurrency)

        async def run_group(pages: list[int]) -> tuple[list[int], str, list]:
            async with semaphore:
                return await self._ocr_group(file_path, pages)

        outcomes = await asyncio.gather(*(run_group(pages) for pages in groups))
        ocr_text: dict[int, str] = {}
        ocr_pages: list[int] = []
        ocr_images: list = []
        for pages, markdown, images in outcomes:
            if not markdown.strip():
                continue
            ocr_text[pages[0]] = markdown
            ocr_pages.extend(pages)
            ocr_images.extend(images or [])

        merged = _merge_page_markdown(local.markdown, ocr_text, page_count)
        structure = structure_from_markdown(merged, page_count=page_count)
        if not structure.blocks:
            structure = local.structure or DocumentStructure()
        logger.info(
            "Hybrid PDF conversion OCR'd pages %s of %s",
            ocr_pages or "none",
            file_path,
        )
        return ConversionResult(
            markdown=merged,
            page_count=page_count,
            structure=structure,
            images=[*local.images, *ocr_images],
            tables=list(local.tables),
            ocr_pages=sorted(ocr_pages),
        )

    async def _ocr_group(self, file_path: str, pages: list[int]) -> tuple[list[int], str, list]:
        import tempfile

        directory = tempfile.mkdtemp(prefix="kb-ocr-pages-")
        subset = str(Path(directory) / "pages.pdf")
        try:
            _extract_pages(file_path, pages, subset)
        except Exception as exc:
            logger.warning("Could not extract pages %s for OCR: %s", pages, exc)
            return pages, "", []
        try:
            result = await self._ocr.convert_async(subset)
        except AppError as exc:
            logger.warning("Per-page OCR failed for pages %s: %s", pages, exc)
            return pages, "", []
        finally:
            shutil.rmtree(directory, ignore_errors=True)
        return pages, result.markdown or "", list(getattr(result, "images", None) or [])

    def convert(self, file_path: str) -> ConversionResult:
        return asyncio.run(self.convert_async(file_path))


def _ocr_groups(scanned_pages: list[int], max_single_page_ocr: int) -> list[list[int]]:
    """Split scanned pages into contiguous runs, one OCR call each."""
    runs: list[list[int]] = []
    for page in scanned_pages:
        if runs and page == runs[-1][-1] + 1:
            runs[-1].append(page)
        else:
            runs.append([page])
    if len(scanned_pages) <= max_single_page_ocr:
        return [[page] for page in scanned_pages]
    return runs


def _extract_pages(file_path: str, pages: list[int], target: str) -> None:
    """Copy the given 1-based pages of a PDF into a new single PDF."""
    import fitz

    source = fitz.open(file_path)
    try:
        subset = fitz.open()
        try:
            for page in pages:
                if 1 <= page <= source.page_count:
                    subset.insert_pdf(source, from_page=page - 1, to_page=page - 1)
            if subset.page_count == 0:
                raise AppError(f"无法抽取第 {pages} 页用于 OCR")
            subset.save(target)
        finally:
            subset.close()
    finally:
        source.close()


def _split_page_markdown(markdown: str) -> tuple[str, dict[int, str]]:
    """Split markdown by `<!-- PAGE:N -->` markers into (front matter, pages)."""
    lines = (markdown or "").splitlines()
    front: list[str] = []
    pages: dict[int, list[str]] = {}
    current = 0
    for line in lines:
        marker = PAGE_MARKER.match(line.strip())
        if marker:
            current = int(marker.group(1))
            pages.setdefault(current, [])
            continue
        if current == 0:
            front.append(line)
        else:
            pages[current].append(line)
    return "\n".join(front).strip(), {
        page: "\n".join(body).strip() for page, body in pages.items()
    }


def _merge_page_markdown(markdown: str, ocr_text: dict[int, str], page_count: int | None) -> str:
    """Replace the text of OCR'd pages while keeping every page in order."""
    front, pages = _split_page_markdown(markdown)
    for page, text in ocr_text.items():
        pages[page] = text.strip()
    highest = max([page_count or 0, *pages.keys()])
    parts: list[str] = []
    if front:
        parts.extend([front, ""])
    for page in range(1, highest + 1):
        body = pages.get(page)
        if not body:
            continue
        parts.append(f"<!-- PAGE:{page} -->")
        parts.append("")
        parts.append(body)
        parts.append("")
    return "\n".join(parts).strip() + "\n" if parts else markdown


class DocxMarkdownConverter(FileConverter):
    """Word (.docx) -> structure preserving heading levels and table order."""

    name = "docx"
    version = "2"

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
            structure, images = self._build_structure(doc, Paragraph, Table)
        except AppError:
            raise
        except Exception:
            structure, images = self._fallback_structure(doc), []

        markdown = structure_to_markdown(structure)
        if not markdown.strip() and not images:
            raise AppError("未能从 Word 文档中提取任何内容")
        return ConversionResult(
            markdown=markdown,
            page_count=None,
            structure=structure,
            images=images,
        )

    def _build_structure(
        self, doc, paragraph_cls, table_cls
    ) -> tuple[DocumentStructure, list[ImageAsset]]:
        """Walk the body in order, tracking headings for paragraph images.

        Images are pulled from the `w:drawing//a:blip` relationships in the
        order they appear and attached to the heading they sit under, so Word
        documents keep the same section-level image association that MinerU
        output provides.
        """
        blocks: list[Block] = []
        images: list[ImageAsset] = []
        pending_list: list[str] = []
        heading_stack: list[str] = []

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
                if text:
                    style = paragraph.style
                    style_name = (style.name if style is not None else "") or ""
                    style_id = (getattr(style, "style_id", "") or "") if style is not None else ""
                    level = _docx_heading_level(style_name, style_id)
                    if level:
                        flush_list()
                        del heading_stack[level - 1 :]
                        heading_stack.append(text)
                        blocks.append(Block(type=BLOCK_HEADING, text=text, level=level))
                    elif _is_list_style(style_name):
                        pending_list.append(text)
                    else:
                        flush_list()
                        blocks.append(Block(type=BLOCK_PARAGRAPH, text=text))
                images.extend(
                    _docx_paragraph_images(child, doc, heading_path=" > ".join(heading_stack))
                )
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
        if not blocks and not images:
            raise AppError("未能从 Word 文档中提取任何内容")
        return DocumentStructure(blocks=blocks), images

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

    name = "text"
    version = "1"

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
    """PPTX / HTML / CSV / JSON / XML etc. via Microsoft MarkItDown."""

    name = "markitdown"
    version = "1"

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


def _docx_paragraph_images(element, doc, *, heading_path: str = "") -> list[ImageAsset]:
    """Extract inline images of one `w:p` element, in document order."""
    from docx.oxml.ns import qn

    assets: list[ImageAsset] = []
    seen: set[str] = set()
    for blip in element.iter(qn("a:blip")):
        relationship_id = blip.get(qn("r:embed")) or blip.get(qn("r:link"))
        if not relationship_id or relationship_id in seen:
            continue
        seen.add(relationship_id)
        part = None
        related = getattr(getattr(doc, "part", None), "related_parts", None)
        if related is not None:
            try:
                part = related.get(relationship_id)
            except Exception:
                part = None
        data = getattr(part, "blob", None)
        if not data:
            continue
        mime = (getattr(part, "content_type", "") or "").split(";")[0].strip()
        if not mime.startswith("image/"):
            mime = "image/png"
        assets.append(
            ImageAsset(
                data=data,
                mime=mime,
                source="local",
                heading_path=heading_path,
            )
        )
    return assets


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