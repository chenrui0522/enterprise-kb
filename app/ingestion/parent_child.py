"""Parent-child chunk planning: small chunks retrieve, large chunks generate.

The plan produced here is split by storage responsibility (design D3):

* parents  -> PostgreSQL (`chunk_parents`), used only as generation context
* children -> Milvus (retrieval), each pointing at its `parent_id`
* tables   -> row-level chunks + a deterministic summary chunk in Milvus,
              with the full grid kept as an asset (`document_tables` + JSON)
* images   -> their own chunk, never expanded into a parent

Tables deliberately do **not** participate in parent-child chunking: a table
row is already a self-contained record, and expanding it into the surrounding
prose would only add noise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from app.ingestion.chunker import (
    _CLAUSE,
    _NUMBERED,
    _QUESTION,
    _STEP,
    _STEP_CN,
    _split_sentences,
)
from app.ingestion.models import ChunkDraft
from app.ingestion.structure import (
    BLOCK_HEADING,
    BLOCK_IMAGE,
    BLOCK_LIST,
    BLOCK_TABLE,
    Block,
    DocumentStructure,
    TableArtifact,
)

PARENT_CHILD_VERSION = "structure-v2"

CHUNK_KIND_CHILD = "child"
CHUNK_KIND_TABLE_ROW = "table_row"
CHUNK_KIND_TABLE_SUMMARY = "table_summary"
CHUNK_KIND_IMAGE = "image"

TABLE_NAME_FALLBACK = "表格"
_STEP_LINE = re.compile(r"^\s*(?:步骤\s*|Step\s*|[0-9]+\s*[\.、:：)）])", re.IGNORECASE)


@dataclass(frozen=True)
class ChunkParams:
    """Per-document-type chunk geometry."""

    parent_child: bool = True
    parent_size: int = 2400
    child_size: int = 800
    child_overlap: int = 80
    table_row_group: int = 1
    repeat_table_header: bool = True
    table_summary_sample_rows: int = 3

    def normalized(self) -> "ChunkParams":
        child_size = max(int(self.child_size), 80)
        overlap = min(max(int(self.child_overlap), 0), max(child_size // 2, 1))
        return replace(
            self,
            child_size=child_size,
            child_overlap=overlap,
            parent_size=max(int(self.parent_size), child_size),
            table_row_group=max(int(self.table_row_group), 1),
            table_summary_sample_rows=max(int(self.table_summary_sample_rows), 0),
        )


#: Shape per document type; `KB_CHUNK_SIZE` / `KB_CHUNK_OVERLAP` scale these so
#: one env knob still tunes the whole corpus (design D6).
BASE_PARAMS: dict[str, ChunkParams] = {
    "generic": ChunkParams(parent_size=2400, child_size=800, child_overlap=80),
    "policy": ChunkParams(parent_size=2000, child_size=600, child_overlap=60),
    "sop": ChunkParams(parent_size=2000, child_size=600, child_overlap=60),
    "faq": ChunkParams(parent_size=3000, child_size=1000, child_overlap=0),
    # Spreadsheets are records, not prose: no parents, one row per chunk.
    "table": ChunkParams(parent_child=False, parent_size=2400, child_size=800, child_overlap=0),
}


def params_for(doc_type: str, settings=None) -> ChunkParams:
    """Resolve chunk geometry for one document type (settings scale the shape)."""
    base = BASE_PARAMS.get((doc_type or "").strip().lower(), BASE_PARAMS["generic"])
    if settings is None:
        return base.normalized()
    scale = max(int(getattr(settings, "chunk_size", 800) or 800), 100) / 800
    parent_child = base.parent_child and bool(getattr(settings, "parent_child_enabled", True))
    return replace(
        base,
        parent_child=parent_child,
        parent_size=max(int(base.parent_size * scale), 200),
        child_size=max(int(base.child_size * scale), 80),
        child_overlap=int(base.child_overlap * scale) if parent_child else 0,
        table_row_group=int(getattr(settings, "table_row_group", base.table_row_group) or 1),
        repeat_table_header=bool(
            getattr(settings, "table_repeat_header", base.repeat_table_header)
        ),
    ).normalized()


@dataclass
class ParentChunk:
    """One generation-side context block (heading subtree / clause group)."""

    id: str
    text: str
    heading_path: str = ""
    section: str = ""
    page: int = 0
    doc_type: str = ""
    chunk_index: int = 0
    char_count: int = 0
    child_count: int = 0
    chunker_version: str = ""

    def as_row(self, *, tenant_id: str, doc_id: str, version_id: str) -> dict:
        return {
            "id": self.id,
            "tenant_id": tenant_id,
            "doc_id": doc_id,
            "version_id": version_id,
            "chunk_index": self.chunk_index,
            "heading_path": self.heading_path,
            "section": self.section,
            "page": self.page,
            "doc_type": self.doc_type,
            "text": self.text,
            "char_count": self.char_count,
            "child_count": self.child_count,
            "chunker_version": self.chunker_version,
        }


@dataclass
class TableAsset:
    """One table of a document: row/summary chunks in Milvus, grid in storage."""

    id: str
    name: str
    header: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    page: int = 0
    section: str = ""
    heading_path: str = ""
    source: str = "structure"
    summary: str = ""
    #: True when each row is already a ready-made semantic line (spreadsheets).
    preformatted: bool = False

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def as_row(self, *, tenant_id: str, doc_id: str, version_id: str, chunker_version: str) -> dict:
        return {
            "id": self.id,
            "tenant_id": tenant_id,
            "doc_id": doc_id,
            "version_id": version_id,
            "name": self.name,
            "page": self.page,
            "section": self.section,
            "heading_path": self.heading_path,
            "header": list(self.header),
            "row_count": self.row_count,
            "storage_key": "",
            "source": self.source,
            "summary": self.summary,
            "chunker_version": chunker_version,
        }


@dataclass
class ChunkPlan:
    parents: list[ParentChunk] = field(default_factory=list)
    children: list[ChunkDraft] = field(default_factory=list)
    tables: list[TableAsset] = field(default_factory=list)


@dataclass
class _Section:
    heading_path: str
    section: str
    page: int = 0
    blocks: list[Block] = field(default_factory=list)


def build_chunk_plan(
    structure: DocumentStructure,
    context,
    *,
    doc_type: str,
    params: ChunkParams,
    tables: list[TableArtifact] | None = None,
    chunker_version: str = PARENT_CHILD_VERSION,
) -> ChunkPlan:
    """Split a structure into parents (Postgres) and children (Milvus)."""
    params = params.normalized()
    resolved_type = (doc_type or "generic").strip().lower() or "generic"
    version_label = f"{chunker_version}:{resolved_type}"
    plan = ChunkPlan()

    sections = _split_sections(structure)
    table_assets = _collect_tables(sections, tables or [], context)
    for table in table_assets:
        table.summary = table.summary or _table_summary(table)

    parents: list[ParentChunk] = []
    children: list[ChunkDraft] = []
    if params.parent_child:
        for section in sections:
            text_blocks = [block for block in section.blocks if _is_prose(block)]
            if not text_blocks:
                continue
            for text in _pack_parent_texts(text_blocks, params):
                parent = ParentChunk(
                    id=f"{context.version_id}-p{len(parents):04d}",
                    text=text,
                    heading_path=section.heading_path or section.section,
                    section=section.section or context.title,
                    page=_first_page(text_blocks),
                    doc_type=resolved_type,
                    chunk_index=len(parents),
                    char_count=len(text),
                    chunker_version=version_label,
                )
                parents.append(parent)
                children.extend(
                    _children_for_parent(parent, resolved_type, params, version_label)
                )
    else:
        children.extend(_flat_children(sections, context, resolved_type, params, version_label))

    for table in table_assets:
        children.extend(_table_children(table, context, resolved_type, params, version_label))

    children.extend(_image_chunks(sections, context, resolved_type, version_label))

    for index, draft in enumerate(children):
        draft.chunk_index = index
        draft.chunker_version = version_label
        draft.doc_type = resolved_type
        draft.chunk_kind = draft.chunk_kind or CHUNK_KIND_CHILD
        if not draft.section:
            draft.section = context.title

    counts: dict[str, int] = {}
    for draft in children:
        if draft.parent_id:
            counts[draft.parent_id] = counts.get(draft.parent_id, 0) + 1
    for parent in parents:
        parent.child_count = counts.get(parent.id, 0)

    plan.parents = parents
    plan.children = children
    plan.tables = table_assets
    return plan


# ----------------------------------------------------------------------
# sections and parents
# ----------------------------------------------------------------------
def _is_prose(block: Block) -> bool:
    """Prose blocks compose parents; tables/images/row blocks never do."""
    if block.type in (BLOCK_TABLE, BLOCK_IMAGE, BLOCK_HEADING):
        return False
    return not block.table_id


def _split_sections(structure: DocumentStructure) -> list[_Section]:
    sections: list[_Section] = []
    stack: list[tuple[int, str]] = []
    current = _Section(heading_path="", section="", blocks=[])

    for block in structure.blocks:
        if block.type == BLOCK_HEADING:
            if current.blocks:
                sections.append(current)
            level = max(block.level or 1, 1)
            stack[:] = [item for item in stack if item[0] < level]
            stack.append((level, block.text))
            current = _Section(
                heading_path=" > ".join(text for _, text in stack),
                section=block.text,
                page=block.page,
                blocks=[block],
            )
            continue
        if not current.section and not current.blocks:
            current.page = current.page or block.page
        current.blocks.append(block)

    if current.blocks:
        sections.append(current)
    return sections


def _pack_parent_texts(blocks: list[Block], params: ChunkParams) -> list[str]:
    """Pack section blocks into parent-sized texts, never splitting a block."""
    texts: list[str] = []
    buffer: list[str] = []
    size = 0
    for block in blocks:
        text = _block_text(block)
        if not text:
            continue
        if len(text) > params.parent_size:
            if buffer:
                texts.append("\n\n".join(buffer))
                buffer, size = [], 0
            texts.extend(_split_windows(text, params.parent_size, 0))
            continue
        if buffer and size + len(text) + 2 > params.parent_size:
            texts.append("\n\n".join(buffer))
            buffer, size = [], 0
        buffer.append(text)
        size += len(text) + 2
    if buffer:
        texts.append("\n\n".join(buffer))
    return texts


def _children_for_parent(
    parent: ParentChunk,
    doc_type: str,
    params: ChunkParams,
    version_label: str,
) -> list[ChunkDraft]:
    if doc_type == "policy":
        pieces = _clause_pieces(parent.text)
    elif doc_type == "sop":
        pieces = _step_pieces(parent.text)
    elif doc_type == "faq":
        pieces = _faq_pieces(parent.text)
    else:
        pieces = [parent.text]

    drafts: list[ChunkDraft] = []
    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        metadata = _piece_metadata(piece, doc_type)
        for window in _split_windows(piece, params.child_size, params.child_overlap):
            drafts.append(
                ChunkDraft(
                    text=window,
                    page=parent.page,
                    section=parent.section,
                    chunk_index=0,
                    chunk_type=metadata["chunk_type"],
                    chunk_kind=CHUNK_KIND_CHILD,
                    doc_type=doc_type,
                    heading_path=parent.heading_path,
                    clause_no=metadata.get("clause_no", ""),
                    step_no=metadata.get("step_no", ""),
                    faq_id=metadata.get("faq_id", ""),
                    parent_id=parent.id,
                    chunker_version=version_label,
                )
            )
    if drafts:
        return drafts
    return [
        ChunkDraft(
            text=window,
            page=parent.page,
            section=parent.section,
            chunk_index=0,
            chunk_type="text",
            chunk_kind=CHUNK_KIND_CHILD,
            doc_type=doc_type,
            heading_path=parent.heading_path,
            parent_id=parent.id,
            chunker_version=version_label,
        )
        for window in _split_windows(parent.text, params.child_size, params.child_overlap)
    ]


def _flat_children(
    sections: list[_Section],
    context,
    doc_type: str,
    params: ChunkParams,
    version_label: str,
) -> list[ChunkDraft]:
    """Child-only documents (e.g. spreadsheets): no parent rows are created."""
    drafts: list[ChunkDraft] = []
    for section in sections:
        for block in section.blocks:
            if not _is_prose(block):
                continue
            text = _block_text(block)
            if not text:
                continue
            for window in _split_windows(text, params.child_size, params.child_overlap):
                drafts.append(
                    ChunkDraft(
                        text=window,
                        page=block.page or section.page,
                        section=section.section or context.title,
                        chunk_index=0,
                        chunk_type="text",
                        chunk_kind=CHUNK_KIND_CHILD,
                        doc_type=doc_type,
                        heading_path=section.heading_path or section.section,
                        chunker_version=version_label,
                    )
                )
    return drafts


# ----------------------------------------------------------------------
# tables
# ----------------------------------------------------------------------
def _collect_tables(
    sections: list[_Section],
    artifacts: list[TableArtifact],
    context,
) -> list[TableAsset]:
    assets: list[TableAsset] = []
    seen: set[str] = set()
    sequence = 0

    # 1) Row-level semantic blocks produced by the spreadsheet converter.
    grouped: dict[str, list[tuple[Block, _Section]]] = {}
    for section in sections:
        for block in section.blocks:
            if block.table_id:
                grouped.setdefault(block.table_id, []).append((block, section))

    for name, entries in grouped.items():
        identifier = _identity(context, f"sheet-{name}")
        if identifier in seen:
            continue
        seen.add(identifier)
        header: list[str] = []
        rows: list[list[str]] = []
        page = 0
        section_name = ""
        heading_path = ""
        for block, section in sorted(entries, key=lambda item: item[0].row_start):
            header = header or list(block.header or [])
            page = page or block.page or section.page
            section_name = section_name or section.section
            heading_path = heading_path or section.heading_path
            rows.extend([item] for item in block.items if str(item).strip())
        if not rows and not header:
            continue
        assets.append(
            TableAsset(
                id=identifier,
                name=name or TABLE_NAME_FALLBACK,
                header=header,
                rows=rows,
                page=page,
                section=section_name,
                heading_path=heading_path,
                source="semantic",
                preformatted=True,
            )
        )

    # 2) Structured grids emitted by converters (spreadsheets). A sheet that
    # already produced row-level semantic blocks is not indexed twice.
    covered = {name for name in grouped}
    for artifact in artifacts:
        if (artifact.sheet or "") in covered:
            continue
        identifier = _identity(context, f"grid-{artifact.sheet or sequence}")
        if identifier in seen:
            continue
        seen.add(identifier)
        sequence += 1
        assets.append(
            TableAsset(
                id=identifier,
                name=artifact.sheet or f"{TABLE_NAME_FALLBACK} {sequence}",
                header=list(artifact.header or []),
                rows=[list(row) for row in artifact.rows or []],
                source=artifact.source or "artifact",
            )
        )

    # 3) Table blocks inside the document (PDF / Word).
    for section in sections:
        for block in section.blocks:
            if block.type != BLOCK_TABLE or block.table_id:
                continue
            sequence += 1
            identifier = _identity(context, f"block-{sequence}")
            if identifier in seen:
                continue
            seen.add(identifier)
            assets.append(
                TableAsset(
                    id=identifier,
                    name=_table_name(block, sequence),
                    header=list(block.header or []),
                    rows=[list(row) for row in block.rows or []],
                    page=block.page,
                    section=section.section,
                    heading_path=section.heading_path,
                    source="structure",
                )
            )
    return [asset for asset in assets if asset.rows or asset.header]


def _table_name(block: Block, sequence: int) -> str:
    first_line = (block.text or "").splitlines()[0].strip() if block.text else ""
    if first_line.startswith("|"):
        first_line = ""
    return first_line[:120] or f"{TABLE_NAME_FALLBACK} {sequence}"


def _identity(context, suffix: str) -> str:
    safe = re.sub(r"[^\w\-\u4e00-\u9fff]", "_", str(suffix))[:40]
    return f"{context.version_id}-t-{safe}"


def _table_summary(table: TableAsset) -> str:
    columns = "、".join(name for name in table.header if name) or "（无表头）"
    parts = [f"表：{table.name}"]
    if table.row_count:
        parts.append(f"共 {table.row_count} 行数据")
    parts.append(f"列：{columns}")
    if table.section:
        parts.append(f"所属章节：{table.section}")
    if table.page:
        parts.append(f"页码：第 {table.page} 页")
    return "；".join(parts)


def _summary_text(table: TableAsset, params: ChunkParams) -> str:
    summary = table.summary or _table_summary(table)
    sample_lines: list[str] = []
    for position, row in enumerate(table.rows[: params.table_summary_sample_rows], start=1):
        pairs = _row_pairs(table, row)
        if pairs:
            sample_lines.append(f"第 {position} 行：{pairs}")
    if sample_lines:
        summary = f"{summary}；示例：" + "；".join(sample_lines)
    return summary


def _table_children(
    table: TableAsset,
    context,
    doc_type: str,
    params: ChunkParams,
    version_label: str,
) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = [
        ChunkDraft(
            text=_summary_text(table, params),
            page=table.page,
            section=table.section or context.title,
            chunk_index=0,
            chunk_type=CHUNK_KIND_TABLE_SUMMARY,
            chunk_kind=CHUNK_KIND_TABLE_SUMMARY,
            doc_type=doc_type,
            heading_path=table.heading_path or table.section,
            table_id=table.id,
            chunker_version=version_label,
        )
    ]

    for position, row in enumerate(table.rows, start=1):
        text = _row_text(table, row, position)
        if not text:
            continue
        for window in _split_windows(text, params.child_size, params.child_overlap):
            drafts.append(
                ChunkDraft(
                    text=window,
                    page=table.page,
                    section=table.section or context.title,
                    chunk_index=0,
                    chunk_type=CHUNK_KIND_TABLE_ROW,
                    chunk_kind=CHUNK_KIND_TABLE_ROW,
                    doc_type=doc_type,
                    heading_path=table.heading_path or table.section,
                    table_id=table.id,
                    row_index=position,
                    row_start=position,
                    row_end=position,
                    chunker_version=version_label,
                )
            )
    return drafts


def _row_text(table: TableAsset, row: list[str], position: int) -> str:
    pairs = _row_pairs(table, row)
    if not pairs:
        return ""
    if table.preformatted:
        return f"【{table.name}】{_strip_row_prefix(pairs, position)}"
    return f"【{table.name}】第 {position} 行：{pairs}"


def _strip_row_prefix(text: str, position: int) -> str:
    """Drop the spreadsheet converter's own '第 N 行：' prefix to avoid doubling it."""
    match = re.match(r"^第\s*\d+\s*行\s*[:：]\s*", text)
    return text[match.end() :] if match else text


def _row_pairs(table: TableAsset, row: list[str]) -> str:
    if table.preformatted and len(row) == 1:
        return str(row[0]).strip()
    pairs: list[str] = []
    for index, value in enumerate(row):
        value = str(value or "").strip()
        if not value:
            continue
        name = (
            table.header[index].strip()
            if index < len(table.header) and table.header[index].strip()
            else f"列{index + 1}"
        )
        pairs.append(f"{name}={value}")
    return "；".join(pairs)


# ----------------------------------------------------------------------
# images
# ----------------------------------------------------------------------
def _image_chunks(
    sections: list[_Section],
    context,
    doc_type: str,
    version_label: str,
) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    for section in sections:
        for block in section.blocks:
            if block.type != BLOCK_IMAGE:
                continue
            text = (block.text or "").strip()
            image_id = (
                block.image_id if re.fullmatch(r"[0-9a-f]{32}", block.image_id or "") else ""
            )
            if not text and not image_id:
                continue
            if not text:
                text = f"图片（第{block.page}页）" if block.page else "图片"
            drafts.append(
                ChunkDraft(
                    text=text[:1000],
                    page=block.page,
                    section=section.section or context.title,
                    chunk_index=0,
                    chunk_type="image",
                    chunk_kind=CHUNK_KIND_IMAGE,
                    doc_type=doc_type,
                    heading_path=section.heading_path or section.section,
                    image_id=image_id,
                    chunker_version=version_label,
                )
            )
    return drafts


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _block_text(block: Block) -> str:
    if block.type == BLOCK_LIST and block.items:
        return "\n".join(f"- {item.strip()}" for item in block.items if item.strip())
    return (block.text or "").strip()


def _first_page(blocks: list[Block]) -> int:
    for block in blocks:
        if block.page:
            return block.page
    return 0


def _split_windows(text: str, size: int, overlap: int) -> list[str]:
    """Sentence-aware windows with an optional overlap of trailing sentences."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    pieces = _split_sentences(text, size)
    windows: list[str] = []
    current: list[str] = []
    length = 0
    for piece in pieces:
        if current and length + len(piece) > size:
            windows.append("".join(current).strip())
            keep: list[str] = []
            kept = 0
            for item in reversed(current):
                if kept + len(item) > overlap:
                    break
                keep.insert(0, item)
                kept += len(item)
            current = keep
            length = kept
        current.append(piece)
        length += len(piece)
    if current:
        windows.append("".join(current).strip())
    return [window for window in windows if window]


def _clause_pieces(text: str) -> list[str]:
    return _split_on(text, lambda line: bool(_CLAUSE.match(line) or _NUMBERED.match(line)))


def _step_pieces(text: str) -> list[str]:
    return _split_on(text, lambda line: bool(_STEP_CN.match(line) or _STEP_LINE.match(line)))


def _faq_pieces(text: str) -> list[str]:
    return _split_on(
        text, lambda line: bool(_QUESTION.match(line) or line.strip().endswith(("？", "?")))
    )


def _split_on(text: str, is_boundary) -> list[str]:
    pieces: list[str] = []
    buffer: list[str] = []
    for line in text.splitlines():
        if is_boundary(line) and buffer:
            pieces.append("\n".join(buffer))
            buffer = []
        buffer.append(line)
    if buffer:
        pieces.append("\n".join(buffer))
    return pieces


def _piece_metadata(piece: str, doc_type: str) -> dict:
    first = piece.strip().splitlines()[0] if piece.strip() else ""
    if doc_type == "policy":
        matched = _CLAUSE.match(first) or _NUMBERED.match(first)
        if matched:
            return {"chunk_type": "policy_clause", "clause_no": matched.group(1).strip()}
        return {"chunk_type": "policy_intro"}
    if doc_type == "sop":
        matched = _STEP_CN.match(first) or _STEP.match(first)
        if matched:
            return {"chunk_type": "sop_step", "step_no": matched.group(1).strip()}
        return {"chunk_type": "sop_step"}
    if doc_type == "faq":
        if _QUESTION.match(first) or first.endswith(("？", "?")):
            return {"chunk_type": "faq", "faq_id": _faq_id(first)}
        return {"chunk_type": "faq"}
    return {"chunk_type": "text"}


def _faq_id(question: str) -> str:
    return re.sub(r"\s+", " ", question.strip())[:60]