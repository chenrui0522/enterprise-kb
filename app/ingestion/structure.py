"""Normalized document structure shared by converters and chunkers.

Converters no longer hand a flat Markdown blob to the chunker: they produce a
`DocumentStructure` made of typed blocks (heading / paragraph / list / table /
code) carrying the page and, for PDFs, the source position used to keep tables
in reading order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

BLOCK_HEADING = "heading"
BLOCK_PARAGRAPH = "paragraph"
BLOCK_LIST = "list"
BLOCK_TABLE = "table"
BLOCK_CODE = "code"

TABLE_SEPARATOR = re.compile(r"^\|[\s:\-|]+\|$")
PAGE_MARKER = re.compile(r"<!--\s*PAGE:\s*(\d+)\s*-->")
HEADING_LINE = re.compile(r"^(#{1,6})\s+(.+)$")
LIST_LINE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.+)$")


class Block(BaseModel):
    """One structural unit of a document."""

    type: str
    text: str = ""
    level: int = 0
    page: int = 0
    rows: list[list[str]] = Field(default_factory=list)
    header: list[str] = Field(default_factory=list)
    items: list[str] = Field(default_factory=list)
    # Source position for formats that expose layout (PDF); 0 when unknown.
    y0: float = 0.0
    x0: float = 0.0


class DocumentStructure(BaseModel):
    blocks: list[Block] = Field(default_factory=list)
    page_count: int | None = None
    degraded: bool = False


@dataclass
class _PendingParagraph:
    lines: list[str]
    page: int


def structure_from_markdown(markdown: str, *, page_count: int | None = None) -> DocumentStructure:
    """Parse Markdown into typed blocks, honoring `<!-- PAGE:N -->` markers."""
    blocks: list[Block] = []
    page = 0
    lines = markdown.splitlines()
    index = 0
    pending: list[str] = []
    pending_page = 0

    def flush_paragraph() -> None:
        nonlocal pending, pending_page
        if pending:
            text = "\n".join(pending).strip()
            if text:
                blocks.append(Block(type=BLOCK_PARAGRAPH, text=text, page=pending_page))
        pending = []
        pending_page = 0

    while index < len(lines):
        stripped = lines[index].strip()

        marker = PAGE_MARKER.match(stripped)
        if marker:
            flush_paragraph()
            page = int(marker.group(1))
            index += 1
            continue

        heading = HEADING_LINE.match(stripped)
        if heading:
            flush_paragraph()
            blocks.append(
                Block(
                    type=BLOCK_HEADING,
                    text=heading.group(2).strip(),
                    level=min(len(heading.group(1)), 6),
                    page=page,
                )
            )
            index += 1
            continue

        if stripped.startswith("```"):
            flush_paragraph()
            code: list[str] = [lines[index]]
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code.append(lines[index])
                index += 1
            if index < len(lines):
                code.append(lines[index])
                index += 1
            blocks.append(Block(type=BLOCK_CODE, text="\n".join(code), page=page))
            continue

        if stripped.startswith("|") and "|" in stripped[1:]:
            flush_paragraph()
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                row = _parse_table_row(lines[index].strip())
                if row is not None and not TABLE_SEPARATOR.match(lines[index].strip()):
                    rows.append(row)
                index += 1
            if rows:
                blocks.append(
                    Block(
                        type=BLOCK_TABLE,
                        header=rows[0],
                        rows=rows[1:],
                        text=markdown_table(rows[0], rows[1:]),
                        page=page,
                    )
                )
            continue

        list_item = LIST_LINE.match(lines[index])
        if list_item:
            flush_paragraph()
            items: list[str] = []
            while index < len(lines):
                current = LIST_LINE.match(lines[index])
                if not current:
                    break
                items.append(current.group(1).strip())
                index += 1
            blocks.append(Block(type=BLOCK_LIST, items=items, text="\n".join(items), page=page))
            continue

        if not stripped:
            flush_paragraph()
            index += 1
            continue

        if not pending:
            pending_page = page
        pending.append(stripped)
        index += 1

    flush_paragraph()
    return DocumentStructure(blocks=blocks, page_count=page_count)


def structure_to_markdown(structure: DocumentStructure) -> str:
    """Serialize a structure back to Markdown, keeping page markers."""
    parts: list[str] = []
    current_page = 0
    for block in structure.blocks:
        if block.page and block.page != current_page:
            if parts:
                parts.append("")
            parts.append(f"<!-- PAGE:{block.page} -->")
            parts.append("")
            current_page = block.page
        if block.type == BLOCK_HEADING:
            level = max(block.level or 1, 1)
            parts.append(f"{'#' * min(level, 6)} {block.text}".strip())
        elif block.type == BLOCK_TABLE:
            parts.append(markdown_table(block.header, block.rows, fallback_text=block.text))
        elif block.type == BLOCK_CODE:
            parts.append(block.text)
        elif block.type == BLOCK_LIST:
            parts.extend(f"- {item}" for item in block.items)
        else:
            parts.append(block.text)
        parts.append("")
    return "\n".join(parts).strip() + "\n" if parts else ""


def degrade_to_paragraphs(structure: DocumentStructure) -> DocumentStructure:
    """Fallback used when fine-grained structure cannot be trusted."""
    blocks: list[Block] = []
    for block in structure.blocks:
        text = block.text or "\n".join(block.items) or markdown_table(block.header, block.rows)
        if not text.strip():
            continue
        blocks.append(Block(type=BLOCK_PARAGRAPH, text=text.strip(), page=block.page))
    return DocumentStructure(blocks=blocks, page_count=structure.page_count, degraded=True)


def markdown_table(header: list[str], rows: list[list[str]], *, fallback_text: str = "") -> str:
    if not header:
        return fallback_text
    lines = ["| " + " | ".join(_clean_cell(cell) for cell in header) + " |"]
    lines.append("|" + "---|" * len(header))
    for row in rows:
        padded = list(row) + [""] * (len(header) - len(row))
        lines.append("| " + " | ".join(_clean_cell(cell) for cell in padded[: len(header)]) + " |")
    return "\n".join(lines)


def _parse_table_row(line: str) -> list[str] | None:
    if not (line.startswith("|") and line.endswith("|")):
        return None
    cells = line[1:-1].split("|")
    return [cell.strip() for cell in cells]


def _clean_cell(cell: str) -> str:
    return str(cell).replace("\n", " ").strip()


def paragraphs_to_structure(paragraphs: list[tuple[int, str]]) -> DocumentStructure:
    """Build a paragraph-only structure from (page, text) pairs."""
    blocks = [
        Block(type=BLOCK_PARAGRAPH, text=text.strip(), page=page)
        for page, text in paragraphs
        if text.strip()
    ]
    return DocumentStructure(blocks=blocks)
