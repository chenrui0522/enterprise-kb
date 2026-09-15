"""Conversion triage: cheap probing that decides which converter to use.

The probe is deliberately shallow - it never parses the whole document. For
PDFs it walks a bounded number of pages and records, per page, whether a text
layer exists, how many images sit on the page and whether a ruled table is
present. The result drives converter routing (`plan_candidates`) and is
persisted in the conversion report so a routing decision stays explainable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.ingestion.converters import (
    IMAGE_EXTENSIONS,
    DocxMarkdownConverter,
    FileConverter,
    HybridPdfConverter,
    MarkItDownConverter,
    PDFMarkdownConverter,
    TextMarkdownConverter,
)

logger = get_logger("ingestion.triage")

#: A page with fewer extractable characters is treated as "no text layer"
#: (stray spaces from a scanned image are not a text layer).
MIN_PAGE_TEXT_CHARS = 5
#: Table probing is much slower than text probing, so it is bounded.
TABLE_PROBE_PAGE_LIMIT = 20
#: Notebook pages include a lot of text that is *not* A4; sampling keeps the
#: triage cost flat for very long documents.
TEXT_PROBE_PAGE_LIMIT = 200

#: Characters that only show up in mathematical typesetting.
MATH_SYMBOLS = "∑∫√±×÷≤≥≠≈∈∀∃∂∇∞αβγθλμπσφωΩΔΣ"
#: LaTeX-ish markers that survive text extraction of formula-heavy pages.
FORMULA_TOKENS = ("\\frac", "\\sqrt", "\\sum", "^{", "_{")

DOC_KIND_PDF_TEXT = "pdf_text"
DOC_KIND_PDF_SCANNED = "pdf_scanned"
DOC_KIND_PDF_MIXED = "pdf_mixed"
DOC_KIND_PDF_COMPLEX = "pdf_complex"
DOC_KIND_IMAGE = "image"
DOC_KIND_DOCX = "docx"
DOC_KIND_XLSX = "xlsx"
DOC_KIND_OFFICE = "office"
DOC_KIND_TEXT = "text"


@dataclass(frozen=True)
class PageProfile:
    """What one page looks like to the cheap probe."""

    page: int
    text_chars: int = 0
    image_count: int = 0
    table_count: int = 0
    has_formula: bool = False

    @property
    def has_text_layer(self) -> bool:
        return self.text_chars >= MIN_PAGE_TEXT_CHARS

    def as_dict(self) -> dict:
        return {
            "page": self.page,
            "text_chars": self.text_chars,
            "images": self.image_count,
            "tables": self.table_count,
            "formula": self.has_formula,
        }


@dataclass
class TriageResult:
    """Routing evidence for one file; serialized into the conversion report."""

    kind: str
    suffix: str
    page_count: int = 0
    pages: list[PageProfile] = field(default_factory=list)
    truncated: bool = False
    reason: str = ""

    @property
    def probed_pages(self) -> int:
        return len(self.pages)

    @property
    def scanned_pages(self) -> list[int]:
        return [page.page for page in self.pages if not page.has_text_layer]

    @property
    def text_pages(self) -> list[int]:
        return [page.page for page in self.pages if page.has_text_layer]

    @property
    def table_pages(self) -> list[int]:
        return [page.page for page in self.pages if page.table_count > 0]

    @property
    def image_pages(self) -> list[int]:
        return [page.page for page in self.pages if page.image_count > 0]

    @property
    def has_text_layer(self) -> bool:
        return any(page.has_text_layer for page in self.pages)

    @property
    def has_tables(self) -> bool:
        return any(page.table_count > 0 for page in self.pages)

    @property
    def has_formulas(self) -> bool:
        return any(page.has_formula for page in self.pages)

    @property
    def has_images(self) -> bool:
        return any(page.image_count > 0 for page in self.pages)

    @property
    def is_mixed_scan(self) -> bool:
        """Some pages are scanned while others carry a text layer."""
        return bool(self.scanned_pages) and bool(self.text_pages)

    def as_report(self) -> dict:
        return {
            "kind": self.kind,
            "suffix": self.suffix,
            "page_count": self.page_count,
            "probed_pages": self.probed_pages,
            "truncated": self.truncated,
            "text_pages": len(self.text_pages),
            "scanned_pages": self.scanned_pages,
            "table_pages": self.table_pages,
            "image_pages": len(self.image_pages),
            "has_tables": self.has_tables,
            "has_formulas": self.has_formulas,
            "reason": self.reason,
        }


def triage_file(file_path: str | Path, filename: str | None = None, *, parse_mode: str = "auto") -> TriageResult:
    """Probe one file cheaply and return the routing evidence.

    Probing never raises for unreadable input: a broken file keeps its
    format-based route so the converter chain can produce the real error.
    """
    name = str(filename or file_path)
    suffix = Path(name).suffix.lower()
    if suffix == ".pdf" and parse_mode != "ocr":
        return _triage_pdf(str(file_path), suffix)
    if suffix in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}:
        return TriageResult(kind=DOC_KIND_IMAGE, suffix=suffix, reason="图片文件统一走 OCR 解析")
    if suffix in {".docx", ".docm"}:
        return TriageResult(kind=DOC_KIND_DOCX, suffix=suffix, reason="Word 文档按段落与标题顺序解析")
    if suffix in {".xlsx", ".xlsm"}:
        return TriageResult(kind=DOC_KIND_XLSX, suffix=suffix, reason="表格文档按工作表语义化")
    if suffix in {".pptx", ".pptm"}:
        return TriageResult(kind=DOC_KIND_OFFICE, suffix=suffix, reason="演示文稿走 MarkItDown 转换")
    return TriageResult(kind=DOC_KIND_TEXT, suffix=suffix, reason="纯文本类格式直接读取")


def _triage_pdf(file_path: str, suffix: str) -> TriageResult:
    try:
        import fitz
    except ImportError:  # pragma: no cover - PyMuPDF is a hard dependency
        return TriageResult(kind=DOC_KIND_PDF_TEXT, suffix=suffix, reason="缺少 PyMuPDF，跳过分诊探测")

    try:
        document = fitz.open(file_path)
    except Exception as exc:
        logger.info("PDF triage probe failed for %s: %s", file_path, exc)
        return TriageResult(
            kind=DOC_KIND_PDF_TEXT,
            suffix=suffix,
            reason=f"分诊探测失败（{exc}），按文字 PDF 处理",
        )

    try:
        if document.needs_pass:
            return TriageResult(kind=DOC_KIND_PDF_TEXT, suffix=suffix, reason="加密 PDF 无法探测")
        page_count = document.page_count
        limit = min(page_count, TEXT_PROBE_PAGE_LIMIT)
        pages: list[PageProfile] = []
        for page_number in range(1, limit + 1):
            try:
                page = document.load_page(page_number - 1)
                text = page.get_text("text") or ""
                image_count = len(page.get_image_info())
            except Exception as exc:
                logger.info("Page probe failed page=%s file=%s: %s", page_number, file_path, exc)
                continue
            pages.append(
                PageProfile(
                    page=page_number,
                    text_chars=len(text.strip()),
                    image_count=image_count,
                    has_formula=_looks_like_formula(text),
                )
            )
        table_pages = _probe_tables(file_path, [page.page for page in pages])
        if table_pages:
            pages = [
                PageProfile(
                    page=page.page,
                    text_chars=page.text_chars,
                    image_count=page.image_count,
                    table_count=table_pages.get(page.page, 0),
                    has_formula=page.has_formula,
                )
                for page in pages
            ]
        result = TriageResult(
            kind=DOC_KIND_PDF_TEXT,
            suffix=suffix,
            page_count=page_count,
            pages=pages,
            truncated=page_count > limit,
        )
        result.kind, result.reason = _classify_pdf(result)
        return result
    finally:
        document.close()


def _classify_pdf(result: TriageResult) -> tuple[str, str]:
    scanned = result.scanned_pages
    if not result.pages:
        return DOC_KIND_PDF_TEXT, "未能获取页面信息，按文字 PDF 处理"
    if len(scanned) == len(result.pages):
        return DOC_KIND_PDF_SCANNED, "所有探测页面都没有文字层，按扫描件处理"
    if scanned:
        return (
            DOC_KIND_PDF_MIXED,
            f"第 {_short_pages(scanned)} 页没有文字层，需要逐页 OCR 回退",
        )
    if result.has_tables:
        return DOC_KIND_PDF_COMPLEX, f"第 {_short_pages(result.table_pages)} 页检测到表格"
    if result.has_formulas:
        return DOC_KIND_PDF_COMPLEX, "检测到公式特征，优先使用公式能力更强的解析器"
    return DOC_KIND_PDF_TEXT, "所有页面都有文字层且未检测到表格/公式"


def _probe_tables(file_path: str, page_numbers: list[int]) -> dict[int, int]:
    """Count ruled tables on a bounded set of pages; best effort only."""
    targets = page_numbers[:TABLE_PROBE_PAGE_LIMIT]
    if not targets:
        return {}
    counts: dict[int, int] = {}
    try:
        import pdfplumber

        with pdfplumber.open(file_path) as pdf:
            for page_number in targets:
                if page_number > len(pdf.pages):
                    continue
                try:
                    found = pdf.pages[page_number - 1].find_tables()
                except Exception:
                    continue
                if found:
                    counts[page_number] = len(found)
    except Exception:
        logger.debug("Table probe failed for %s", file_path, exc_info=True)
        return {}
    return counts


def _looks_like_formula(text: str) -> bool:
    if not text:
        return False
    hits = sum(1 for char in text if char in MATH_SYMBOLS)
    hits += sum(text.count(token) for token in FORMULA_TOKENS)
    if hits >= 3:
        return True
    return bool(re.search(r"[A-Za-z]\s*=\s*[-+0-9A-Za-z]", text)) and hits >= 1


def _short_pages(pages: list[int], limit: int = 6) -> str:
    head = "、".join(str(page) for page in pages[:limit])
    return head if len(pages) <= limit else f"{head} 等 {len(pages)} 页"


def plan_candidates(
    filename: str,
    parse_mode: str,
    settings: Settings,
    triage: TriageResult | None = None,
    *,
    docling_candidate: bool = False,
) -> list[tuple[str, FileConverter]]:
    """Build the ordered converter chain for one upload.

    The first entry is the primary route chosen by triage; the remaining
    entries are fallbacks used when a converter is unavailable or fails.
    """
    from app.ingestion.mineru import MinerUConverter

    parse_mode = (parse_mode or "auto").lower()
    suffix = Path(filename).suffix.lower()
    kind = triage.kind if triage is not None else ""

    if suffix in IMAGE_EXTENSIONS:
        _require_mineru(settings, "图片解析需要 MinerU OCR")
        return [("ocr", MinerUConverter(settings))]

    if parse_mode == "ocr":
        if suffix != ".pdf" and suffix not in IMAGE_EXTENSIONS:
            raise AppError("强制 OCR（parse_mode=ocr）仅支持 PDF 与图片文件")
        _require_mineru(settings, "OCR 解析需要 MinerU 服务")
        return [("ocr", MinerUConverter(settings))]

    if suffix == ".pdf":
        return _pdf_candidates(settings, triage, kind, docling_candidate)

    if suffix in {".docx", ".docm"}:
        candidates: list[tuple[str, FileConverter]] = [("text", DocxMarkdownConverter())]
        if settings.mineru_enabled:
            candidates.append(("ocr", MinerUConverter(settings)))
        return candidates

    if suffix in {".xlsx", ".xlsm"}:
        from app.ingestion.tabular import XlsxSemanticConverter

        candidates = [("xlsx", XlsxSemanticConverter())]
        candidates.append(("markitdown", MarkItDownConverter()))
        if settings.mineru_enabled:
            candidates.append(("ocr", MinerUConverter(settings)))
        return candidates

    if suffix in {".md", ".markdown", ".txt"}:
        return [("text", TextMarkdownConverter())]

    return [("markitdown", MarkItDownConverter())]


def _pdf_candidates(
    settings: Settings,
    triage: TriageResult | None,
    kind: str,
    docling_candidate: bool,
) -> list[tuple[str, FileConverter]]:
    from app.ingestion.mineru import MinerUConverter

    local = ("text", PDFMarkdownConverter())
    ocr = ("ocr", MinerUConverter(settings)) if settings.mineru_enabled else None
    docling = None
    if docling_candidate:
        from app.ingestion.docling import DoclingConverter

        docling = ("docling", DoclingConverter(settings))

    def ordered(primary: list[tuple[str, FileConverter]]) -> list[tuple[str, FileConverter]]:
        return [*primary, local]

    if triage is None:
        # No probe information (e.g. a synthetic call): keep the historical
        # "local first, OCR as fallback" order.
        return [local, *([ocr] if ocr else [])]

    if kind == DOC_KIND_PDF_SCANNED:
        return [*([ocr] if ocr else []), local]

    if kind == DOC_KIND_PDF_MIXED and ocr is not None:
        # Only the pages without a text layer go to OCR; the rest stay local.
        hybrid = HybridPdfConverter(ocr[1], triage.scanned_pages)
        return ordered([("hybrid", hybrid), ocr])

    if kind == DOC_KIND_PDF_COMPLEX:
        # Tables/formulas: the layout-aware parser wins, local parsing stays
        # as the last resort. KB_MINERU_PREFER_COMPLEX=false flips this back to
        # local-first (much cheaper on CPU-only MinerU hosts).
        if settings.mineru_prefer_complex:
            return ordered([item for item in (ocr, docling) if item is not None])
        return ordered([item for item in (docling,) if item is not None])

    # Plain text PDF: Docling first when it is available, then the local
    # parser. OCR is only a last resort so a normal text PDF never pays for
    # OCR just because the service is configured.
    if docling is not None:
        return [docling, local, *([ocr] if ocr else [])]
    return [local, *([ocr] if ocr else [])]


def _require_mineru(settings: Settings, message: str) -> None:
    if not settings.mineru_enabled:
        raise AppError(
            f"{message}：请配置 KB_MINERU_URL 并启动 mineru-api 服务",
            status_code=503,
        )


__all__ = [
    "DOC_KIND_DOCX",
    "DOC_KIND_IMAGE",
    "DOC_KIND_OFFICE",
    "DOC_KIND_PDF_COMPLEX",
    "DOC_KIND_PDF_MIXED",
    "DOC_KIND_PDF_SCANNED",
    "DOC_KIND_PDF_TEXT",
    "DOC_KIND_TEXT",
    "DOC_KIND_XLSX",
    "PageProfile",
    "TriageResult",
    "plan_candidates",
    "triage_file",
]