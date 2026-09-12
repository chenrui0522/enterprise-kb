from __future__ import annotations

import re
from dataclasses import dataclass

from app.ingestion.models import ChunkDraft, ParsedPage
from app.ingestion.structure import (
    BLOCK_HEADING,
    BLOCK_LIST,
    BLOCK_PARAGRAPH,
    BLOCK_TABLE,
    Block,
    DocumentStructure,
    markdown_table,
    structure_to_markdown,
)


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


DOC_TYPES = frozenset({"faq", "policy", "sop", "table", "generic"})
DEFAULT_CHUNKER_VERSION = "structure-v1"

_CLAUSE = re.compile(r"^\s*(第[一二三四五六七八九十百千零〇0-9]+条)\s*(.*)$")
_NUMBERED = re.compile(r"^\s*(\d+(?:\.\d+)+)[\.\s、]?\s*(.*)$")
_STEP = re.compile(
    r"^\s*(?:步骤\s*|Step\s*)?([0-9]+(?:\.[0-9]+)*)\s*[\.、:：)）]?\s*(.*)$",
    re.IGNORECASE,
)
_STEP_CN = re.compile(r"^\s*第([一二三四五六七八九十百千零〇0-9]+)步\s*[：:\.、]?\s*(.*)$")
_QUESTION = re.compile(r"^\s*(?:Q\s*\d*|问(?:题)?)\s*[:：.、]?\s*(.*)$", re.IGNORECASE)
_ANSWER = re.compile(r"^\s*(?:A\s*\d*|答(?:案)?)\s*[:：.、]?\s*(.*)$", re.IGNORECASE)


def detect_doc_type(structure: DocumentStructure) -> str:
    """Best-effort document type detection used when no doc_type is supplied."""
    faq_hits = sop_hits = policy_hits = 0
    for block in structure.blocks:
        if block.type not in (BLOCK_PARAGRAPH, BLOCK_LIST):
            continue
        for line in _block_lines(block):
            if _QUESTION.match(line):
                faq_hits += 1
            if _STEP_CN.match(line) or re.match(r"^\s*步骤\s*[0-9]", line):
                sop_hits += 1
            if _CLAUSE.match(line):
                policy_hits += 1
    if faq_hits >= 2 and faq_hits >= sop_hits:
        return "faq"
    if sop_hits >= 2:
        return "sop"
    if policy_hits >= 2:
        return "policy"
    table_chars = sum(len(block.text) for block in structure.blocks if block.type == BLOCK_TABLE)
    total_chars = sum(len(block.text) for block in structure.blocks) or 1
    if table_chars / total_chars >= 0.4:
        return "table"
    return "generic"


def chunk_structure(
    structure: DocumentStructure,
    context: ChunkContext,
    *,
    doc_type: str | None = None,
    chunk_size: int = 800,
    overlap: int = 80,
    chunker_version: str = DEFAULT_CHUNKER_VERSION,
) -> list[ChunkDraft]:
    """Route a document structure to the chunker matching its document type."""
    resolved = (doc_type or "").strip().lower()
    if resolved not in DOC_TYPES or resolved == "auto":
        resolved = detect_doc_type(structure)

    if resolved == "faq":
        drafts = _chunk_faq(structure, context, chunk_size)
    elif resolved == "policy":
        drafts = _chunk_policy(structure, context, chunk_size)
    elif resolved == "sop":
        drafts = _chunk_sop(structure, context, chunk_size)
    elif resolved == "table":
        drafts = _chunk_table(structure, context, chunk_size)
    else:
        drafts = _chunk_generic(structure, context, chunk_size, overlap)

    if not drafts:
        drafts = _chunk_generic(structure, context, chunk_size, overlap)

    for index, draft in enumerate(drafts):
        draft.chunk_index = index
        draft.chunker_version = f"{chunker_version}:{resolved}"
        if not draft.section:
            draft.section = context.title
        if not draft.heading_path:
            draft.heading_path = draft.section or context.title
    return drafts


def _chunk_generic(
    structure: DocumentStructure,
    context: ChunkContext,
    chunk_size: int,
    overlap: int,
) -> list[ChunkDraft]:
    markdown = structure_to_markdown(structure)
    drafts = chunk_markdown(markdown, context, chunk_size=chunk_size, overlap=overlap)
    for draft in drafts:
        draft.chunk_type = draft.chunk_type or "text"
    return drafts


def _chunk_faq(structure: DocumentStructure, context: ChunkContext, chunk_size: int) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    stack: list[tuple[int, str]] = []
    section = context.title
    question = ""
    question_page = 0
    answer_lines: list[str] = []
    sequence = 0

    def flush() -> None:
        nonlocal question, answer_lines, sequence
        if not question:
            answer_lines = []
            return
        sequence += 1
        faq_id = f"{context.version_id}-faq-{sequence}"
        answer = "\n".join(answer_lines).strip()
        text = f"Q: {question}\nA: {answer}".strip()
        heading_path = _path(stack) or section
        if len(text) <= chunk_size:
            drafts.append(
                ChunkDraft(
                    text=text,
                    page=question_page,
                    section=section,
                    chunk_index=0,
                    chunk_type="faq",
                    heading_path=heading_path,
                    faq_id=faq_id,
                    parent_id=faq_id,
                )
            )
        else:
            budget = max(chunk_size - len(question) - 8, max(chunk_size // 2, 80))
            for part in _split_sentences(answer, budget):
                drafts.append(
                    ChunkDraft(
                        text=f"Q: {question}\nA: {part}",
                        page=question_page,
                        section=section,
                        chunk_index=0,
                        chunk_type="faq",
                        heading_path=heading_path,
                        faq_id=faq_id,
                        parent_id=faq_id,
                    )
                )
        question = ""
        answer_lines = []

    for block in structure.blocks:
        if block.type == BLOCK_HEADING:
            flush()
            _push_heading(stack, block)
            section = block.text
            continue
        if block.type == BLOCK_TABLE:
            flush()
            continue
        for line in _block_lines(block):
            matched_question = _QUESTION.match(line)
            matched_answer = _ANSWER.match(line)
            if matched_question:
                flush()
                question = matched_question.group(1).strip() or line.strip()
                question_page = block.page
                continue
            if matched_answer:
                if question:
                    answer_lines.append(matched_answer.group(1).strip())
                continue
            if not question:
                if line.strip().endswith(("？", "?")) and len(line.strip()) <= 160:
                    flush()
                    question = line.strip()
                    question_page = block.page
                continue
            answer_lines.append(line)
    flush()
    return drafts


def _chunk_policy(structure: DocumentStructure, context: ChunkContext, chunk_size: int) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    stack: list[tuple[int, str]] = []
    section = context.title
    clause_no = ""
    buffer: list[str] = []
    buffer_page = 0

    def flush() -> None:
        nonlocal clause_no, buffer, buffer_page
        if not buffer:
            return
        text = "\n".join(buffer).strip()
        buffer = []
        if not text:
            return
        heading_path = _path(stack) or section
        chunk_type = "policy_clause" if clause_no else "policy_intro"
        parent_id = f"{context.version_id}-clause-{clause_no}" if clause_no else ""
        if len(text) <= chunk_size:
            drafts.append(
                ChunkDraft(
                    text=text,
                    page=buffer_page,
                    section=section,
                    chunk_index=0,
                    chunk_type=chunk_type,
                    heading_path=heading_path,
                    clause_no=clause_no,
                    parent_id=parent_id,
                )
            )
        else:
            for part in _split_sentences(text, chunk_size):
                drafts.append(
                    ChunkDraft(
                        text=part,
                        page=buffer_page,
                        section=section,
                        chunk_index=0,
                        chunk_type=chunk_type,
                        heading_path=heading_path,
                        clause_no=clause_no,
                        parent_id=parent_id,
                    )
                )
        clause_no = ""

    for block in structure.blocks:
        if block.type == BLOCK_HEADING:
            flush()
            _push_heading(stack, block)
            section = block.text
            continue
        if block.type == BLOCK_TABLE:
            flush()
            drafts.extend(_table_drafts(block, context, chunk_size, stack, section))
            continue
        for line in _block_lines(block):
            matched = _CLAUSE.match(line) or _NUMBERED.match(line)
            if matched:
                flush()
                clause_no = matched.group(1).strip()
                buffer = [line.strip()]
                buffer_page = block.page
            else:
                if not buffer:
                    buffer_page = block.page
                buffer.append(line)
    flush()
    return drafts


def _chunk_sop(structure: DocumentStructure, context: ChunkContext, chunk_size: int) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    stack: list[tuple[int, str]] = []
    section = context.title
    step_no = ""
    buffer: list[str] = []
    buffer_page = 0
    prerequisites: list[str] = []

    def flush() -> None:
        nonlocal step_no, buffer, buffer_page
        if not buffer:
            return
        text = "\n".join(buffer).strip()
        buffer = []
        if not text:
            return
        heading_path = _path(stack) or section
        parent_id = f"{context.version_id}-step-{step_no}" if step_no else ""
        if len(text) <= chunk_size:
            drafts.append(
                ChunkDraft(
                    text=text,
                    page=buffer_page,
                    section=section,
                    chunk_index=0,
                    chunk_type="sop_step",
                    heading_path=heading_path,
                    step_no=step_no,
                    parent_id=parent_id,
                )
            )
        else:
            # Guard against the Milvus 4096-char field limit; only oversized steps split.
            for part in _split_sentences(text, chunk_size):
                drafts.append(
                    ChunkDraft(
                        text=part,
                        page=buffer_page,
                        section=section,
                        chunk_index=0,
                        chunk_type="sop_step",
                        heading_path=heading_path,
                        step_no=step_no,
                        parent_id=parent_id,
                    )
                )
        step_no = ""

    for block in structure.blocks:
        if block.type == BLOCK_HEADING:
            flush()
            _push_heading(stack, block)
            section = block.text
            continue
        if block.type == BLOCK_TABLE:
            flush()
            drafts.extend(_table_drafts(block, context, chunk_size, stack, section))
            continue
        for line in _block_lines(block):
            matched = _STEP_CN.match(line)
            body = ""
            new_step = ""
            if matched:
                new_step = matched.group(1).strip()
                body = matched.group(2).strip()
            else:
                candidate = _STEP.match(line)
                if candidate and (line.lstrip().lower().startswith("step") or re.match(r"^\s*步骤", line)):
                    new_step = candidate.group(1).strip()
                    body = candidate.group(2).strip()
                elif candidate and re.match(r"^\s*[0-9]+\s*[\.、)）]", line):
                    new_step = candidate.group(1).strip()
                    body = candidate.group(2).strip()
                else:
                    if not step_no:
                        prerequisites.append(line)
                    else:
                        buffer.append(line)
                    continue
            flush()
            step_no = new_step
            buffer_page = block.page
            buffer = list(prerequisites)
            prerequisites = []
            buffer.append(f"{step_no}. {body}".strip() if body else step_no)
    flush()
    return drafts


def _chunk_table(structure: DocumentStructure, context: ChunkContext, chunk_size: int) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    stack: list[tuple[int, str]] = []
    section = context.title
    sequence = 0
    for block in structure.blocks:
        if block.type == BLOCK_HEADING:
            _push_heading(stack, block)
            section = block.text
            continue
        if block.type != BLOCK_TABLE:
            continue
        sequence += 1
        drafts.extend(
            _table_drafts(block, context, chunk_size, stack, section, table_id=f"{context.version_id}-table-{sequence}")
        )
    return drafts


def _table_drafts(
    block: Block,
    context: ChunkContext,
    chunk_size: int,
    stack: list[tuple[int, str]],
    section: str,
    *,
    table_id: str | None = None,
) -> list[ChunkDraft]:
    header = list(block.header or [])
    rows = list(block.rows or [])
    if not header:
        return []
    identifier = table_id or f"{context.version_id}-table-1"
    header_block = markdown_table(header, [])
    groups: list[list[list[str]]] = []
    current: list[list[str]] = []
    current_len = len(header_block)
    for row in rows:
        line = markdown_table(header, [row]).splitlines()[-1]
        if current and current_len + len(line) + 1 > chunk_size:
            groups.append(current)
            current = []
            current_len = len(header_block)
        current.append(row)
        current_len += len(line) + 1
    groups.append(current)
    drafts: list[ChunkDraft] = []
    cursor = 0
    for group in groups:
        start = cursor + 1
        end = cursor + len(group)
        drafts.append(
            ChunkDraft(
                text=markdown_table(header, group),
                page=block.page,
                section=section,
                chunk_index=0,
                chunk_type="table",
                heading_path=_path(stack) or section,
                table_id=identifier,
                row_start=start,
                row_end=end,
                parent_id=identifier,
            )
        )
        cursor = end
    return drafts


def _block_lines(block: Block) -> list[str]:
    if block.type == BLOCK_LIST and block.items:
        return [item.strip() for item in block.items if item.strip()]
    return [line.strip() for line in (block.text or "").splitlines() if line.strip()]


def _push_heading(stack: list[tuple[int, str]], block: Block) -> None:
    level = max(block.level or 1, 1)
    stack[:] = [item for item in stack if item[0] < level]
    stack.append((level, block.text))


def _path(stack: list[tuple[int, str]]) -> str:
    return " > ".join(text for _, text in stack)


def _split_sentences(text: str, limit: int) -> list[str]:
    if limit <= 0:
        limit = 200
    pieces = re.split(r"(?<=[。！？!?;；])", text)
    parts: list[str] = []
    current = ""
    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        while len(piece) > limit:
            parts.append(piece[:limit])
            piece = piece[limit:]
        if current and len(current) + len(piece) > limit:
            parts.append(current)
            current = piece
        else:
            current += piece
    if current:
        parts.append(current)
    return parts or [text[:limit]]