from __future__ import annotations

import re
from dataclasses import dataclass

from app.ingestion.models import ChunkDraft, ParsedPage


@dataclass
class ChunkContext:
    doc_id: str
    version_id: str
    tenant_id: str
    title: str


_SENTENCE_END = re.compile(r"[。！？!?；;]$")
_PAGE_MARKER = re.compile(r"<!--\s*PAGE:\s*(\d+)\s*-->")
_HEADING = re.compile(r"^(#{1,6})\s+(.+)$")


def chunk_pages(
    pages: list[ParsedPage],
    context: ChunkContext,
    *,
    chunk_size: int = 800,
    overlap: int = 80,
) -> list[ChunkDraft]:
    """Split parsed pages into context-bearing chunks with overlapping windows."""
    if chunk_size <= overlap:
        overlap = max(chunk_size // 5, 1)
    drafts: list[ChunkDraft] = []
    index = 0
    current_section = "前言"

    for page in pages:
        paragraphs = _to_paragraphs(page.text)
        for paragraph in paragraphs:
            stripped = paragraph.strip()
            if not stripped:
                continue
            if _looks_like_heading(stripped):
                current_section = stripped[:200]

            while len(stripped) > chunk_size:
                window = stripped[:chunk_size]
                drafts.append(_make_draft(window, page.page_number, current_section, index))
                index += 1
                stripped = stripped[chunk_size - overlap :]
            if stripped:
                drafts.append(_make_draft(stripped, page.page_number, current_section, index))
                index += 1
    return _merge_tiny_chunks(drafts, chunk_size)


def _to_paragraphs(text: str) -> list[str]:
    return [paragraph.replace("\r", "").strip() for paragraph in re.split(r"\n\s*\n", text)]


def _looks_like_heading(line: str) -> bool:
    if len(line) > 60 or not line or line.isdigit():
        return False
    if _SENTENCE_END.search(line):
        return False
    if re.search(r"[a-zA-Z]{4,}", line):
        return len(line.split()) <= 12
    return True


def _make_draft(text: str, page: int, section: str, index: int) -> ChunkDraft:
    return ChunkDraft(text=text.strip(), page=page, section=section, chunk_index=index)


def _merge_tiny_chunks(drafts: list[ChunkDraft], chunk_size: int) -> list[ChunkDraft]:
    """Merge very small consecutive same-page chunks (short paragraphs) up to chunk_size."""
    merged: list[ChunkDraft] = []
    buffer: list[ChunkDraft] = []
    buffer_len = 0
    for draft in drafts:
        if buffer and (draft.page != buffer[-1].page or buffer_len + len(draft.text) > chunk_size):
            merged.extend(_flush_buffer(buffer))
            buffer = []
            buffer_len = 0
        buffer.append(draft)
        buffer_len += len(draft.text) + 1
    if buffer:
        merged.extend(_flush_buffer(buffer))
    return merged


def _flush_buffer(buffer: list[ChunkDraft]) -> list[ChunkDraft]:
    if len(buffer) == 1:
        return buffer
    first = buffer[0]
    text = "\n\n".join(item.text for item in buffer)
    return [
        ChunkDraft(
            text=text,
            page=first.page,
            section=first.section,
            chunk_index=first.chunk_index,
        )
    ]


def chunk_markdown(
    markdown: str,
    context: ChunkContext,
    *,
    chunk_size: int = 800,
    overlap: int = 80,
) -> list[ChunkDraft]:
    """Chunk normalized Markdown while honoring `<!-- PAGE:N -->` markers.

    Headings start new logical sections; long code/table/paragraph blocks are
    split into windows; every chunk keeps page + section metadata for citations.
    """
    blocks = _markdown_blocks(markdown)
    drafts: list[ChunkDraft] = []
    index = 0

    buffer: list[str] = []
    buffer_len = 0
    buffer_page = 0
    section = context.title

    def flush() -> None:
        nonlocal buffer, buffer_len, index
        if not buffer:
            return
        drafts.append(
            ChunkDraft(
                text="\n".join(buffer).strip(),
                page=buffer_page,
                section=section,
                chunk_index=index,
            )
        )
        index += 1
        buffer = []
        buffer_len = 0

    for page, block_type, text in blocks:
        if block_type == "heading":
            flush()
            section = text.lstrip("#").strip()
            buffer_page = page or buffer_page
            buffer = [text]
            buffer_len = len(text) + 1
            continue

        if len(text) > chunk_size:
            flush()
            for window in _split_long_block(text, chunk_size, overlap):
                drafts.append(
                    ChunkDraft(
                        text=window,
                        page=page or buffer_page,
                        section=section,
                        chunk_index=index,
                    )
                )
                index += 1
            continue

        if page:
            buffer_page = page
        if buffer and buffer_len + len(text) > chunk_size:
            flush()
            buffer_page = page or buffer_page
        buffer.append(text)
        buffer_len += len(text) + 1

    flush()

    if not drafts:
        raise ValueError("Markdown 切分后没有生成任何片段")
    return drafts


def _markdown_blocks(markdown: str) -> list[tuple[int, str, str]]:
    blocks: list[tuple[int, str, str]] = []
    page = 0
    lines = markdown.splitlines()
    paragraph: list[str] = []
    paragraph_page = 0
    index = 0

    def flush_paragraph() -> None:
        nonlocal paragraph, paragraph_page
        if paragraph:
            blocks.append((paragraph_page, "text", "\n".join(paragraph).strip()))
        paragraph = []
        paragraph_page = 0

    while index < len(lines):
        line = lines[index]
        page_match = _PAGE_MARKER.match(line.strip())
        if page_match:
            flush_paragraph()
            page = int(page_match.group(1))
            index += 1
            continue
        if _HEADING.match(line.strip()):
            flush_paragraph()
            blocks.append((page, "heading", line.strip()))
            index += 1
            continue
        if line.strip().startswith("```"):
            flush_paragraph()
            code: list[str] = [line]
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code.append(lines[index])
                index += 1
            if index < len(lines):
                code.append(lines[index])
                index += 1
            blocks.append((page, "text", "\n".join(code)))
            continue
        if line.strip().startswith("|") and "|" in line.strip()[1:]:
            flush_paragraph()
            table: list[str] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                table.append(lines[index].strip())
                index += 1
            blocks.append((page, "text", "\n".join(table)))
            continue
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            index += 1
            continue
        if not paragraph:
            paragraph_page = page
        paragraph.append(stripped)
        index += 1
    flush_paragraph()
    return blocks


def _split_long_block(text: str, chunk_size: int, overlap: int) -> list[str]:
    lines = text.splitlines()
    windows: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        if current and current_len + len(line) + 1 > chunk_size:
            windows.append("\n".join(current))
            keep = _overlap_lines(current, overlap)
            current = list(keep)
            current_len = sum(len(item) + 1 for item in keep)
        current.append(line)
        current_len += len(line) + 1
    if current:
        windows.append("\n".join(current))
    return windows


def _overlap_lines(lines: list[str], overlap: int) -> list[str]:
    kept: list[str] = []
    size = 0
    for line in reversed(lines):
        if size + len(line) > overlap and kept:
            break
        kept.append(line)
        size += len(line) + 1
    return list(reversed(kept))
