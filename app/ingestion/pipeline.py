from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.ingestion.cache import ParseCache
from app.ingestion.chunker import (
    ChunkContext,
    DEFAULT_CHUNKER_VERSION,
    chunk_structure,
    detect_doc_type,
)
from app.ingestion.docling import docling_available
from app.ingestion.images import dedupe_assets, extract_images_local, filter_decorative
from app.ingestion.structure import BLOCK_IMAGE, Block, structure_from_markdown
from app.ingestion.conversion import convert_safely
from app.ingestion.converters import (
    ConversionResult,
    FileConverter,
    NoExtractableContentError,
)
from app.ingestion.models import ChunkDraft
from app.ingestion.parent_child import (
    PARENT_CHILD_VERSION,
    ChunkPlan,
    build_chunk_plan,
    params_for,
)
from app.ingestion.storage import FileDocumentStorage
from app.ingestion.triage import TriageResult, plan_candidates, triage_file
from app.models.entity import ChunkParent, Document, DocumentImage, DocumentTable, DocumentVersion
from app.providers.base import Embedder
from app.retrieval.chunk import ChunkRecord
from app.retrieval.milvus_store import MilvusStore

logger = get_logger("ingestion.pipeline")


def _is_recoverable(exc: AppError) -> bool:
    """Whether the next candidate converter should be tried.

    Handing over makes sense when the *converter* could not do the job (service
    down, nothing extractable, upstream failure). It does not make sense when
    the file itself is unusable - a corrupt or encrypted file will be rejected
    by every other converter too, and retrying it through a slow OCR service
    only delays the error.
    """
    return isinstance(exc, NoExtractableContentError) or exc.status_code >= 500


class IngestionPipeline:
    def __init__(
        self,
        store: MilvusStore,
        embedder: Embedder,
        storage: FileDocumentStorage,
        converter: FileConverter | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._storage = storage
        self._converter = converter
        self._settings = settings
        self._last_conversion_meta: dict = {}
        self._last_triage: dict = {}
        self._last_plan: list[str] = []
        self._last_failures: list[dict] = []

    async def process_job(
        self,
        session: AsyncSession,
        job: dict,
        chunk_size: int,
        overlap: int,
        doc_type: str | None = None,
        chunker_version: str | None = None,
    ) -> None:
        doc_type = doc_type or job.get("doc_type")
        chunker_version = chunker_version or job.get("chunker_version")
        doc_id = job["doc_id"]
        version_id = job["version_id"]
        document = await session.get(Document, doc_id)
        version = await session.get(DocumentVersion, version_id)
        if document is None or version is None:
            logger.error("Ingestion job refers to missing rows: %s", job)
            return

        try:
            await self._run(session, document, version, job, chunk_size, overlap, doc_type, chunker_version)
        except Exception as exc:
            logger.exception("Document ingestion failed doc=%s version=%s", doc_id, version_id)
            document.status = "failed"
            document.stage = "failed"
            document.error_message = str(exc)[:1000]
            version.status = "failed"
            version.stage = "failed"
            version.error_message = str(exc)[:1000]
            await session.commit()

    async def _run(
        self,
        session: AsyncSession,
        document: Document,
        version: DocumentVersion,
        job: dict,
        chunk_size: int,
        overlap: int,
        doc_type: str | None = None,
        chunker_version: str | None = None,
    ) -> None:
        settings = self._settings or get_settings()
        file_path = self._storage.resolve(job["storage_key"])
        if job.get("reindex"):
            self._store.delete_by_version(version.id)
            self._storage.delete_version_assets(document.id, version.id)
            await self._delete_version_rows(session, version.id)

        await self._set_stage(session, document, version, "parsing")
        started = time.perf_counter()
        converted = await self._convert_to_markdown(document, version, file_path)
        conversion_meta = dict(getattr(self, "_last_conversion_meta", {}) or {})
        conversion_meta["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        conversion_meta.update(self._conversion_evidence(converted))
        markdown = converted.markdown

        image_blocks: list[Block] = []
        image_warning: str | None = None
        try:
            assets = list(getattr(converted, "images", None) or [])
            if not assets:
                assets = extract_images_local(str(file_path), document.filename)
            assets = dedupe_assets(filter_decorative(assets))
            for asset in assets:
                storage_key = self._storage.store_image(
                    document.id, version.id, asset.sha256, asset.suffix, asset.data
                )
                record = DocumentImage(
                    tenant_id=document.tenant_id,
                    doc_id=document.id,
                    version_id=version.id,
                    page=asset.page,
                    bbox=",".join(str(value) for value in asset.bbox) if asset.bbox else None,
                    storage_key=storage_key,
                    sha256=asset.sha256,
                    mime=asset.mime,
                    width=asset.width,
                    height=asset.height,
                    caption=asset.caption or None,
                    source=asset.source,
                    heading_path=asset.heading_path,
                )
                session.add(record)
                await session.flush()
                image_blocks.append(
                    Block(
                        type=BLOCK_IMAGE,
                        text=asset.caption or "",
                        image_id=record.id,
                        page=asset.page,
                    )
                )
            if assets:
                logger.info("Extracted %d image(s) for version=%s", len(assets), version.id)
        except Exception as exc:
            logger.warning("Image extraction failed for %s", document.filename, exc_info=True)
            image_warning = f"warning: 图片抽取失败：{str(exc)[:200]}"

        await self._set_stage(session, document, version, "chunking")
        conversion_meta.update(
            {
                "markdown_chars": len(markdown or ""),
                "structure_blocks": len(
                    (converted.structure.blocks if converted.structure else []) or []
                ),
                "degraded": bool(getattr(converted.structure, "degraded", False)),
            }
        )

        context = ChunkContext(
            doc_id=document.id,
            version_id=version.id,
            tenant_id=document.tenant_id,
            title=document.title,
        )
        resolved_doc_type = (doc_type or getattr(version, "doc_type", "") or "").strip().lower()
        if resolved_doc_type in {"", "auto"}:
            resolved_doc_type = None
        structure = (
            converted.structure
            if converted.structure and converted.structure.blocks
            else structure_from_markdown(markdown, page_count=converted.page_count)
        )
        structure.blocks = [block for block in structure.blocks if block.type != BLOCK_IMAGE]
        if image_blocks:
            structure.blocks.extend(image_blocks)
        resolved_version = chunker_version or DEFAULT_CHUNKER_VERSION
        plan: ChunkPlan | None = None
        if self._uses_parent_child(resolved_version):
            # v2 chunks by document type, so an "auto" upload is classified here
            # (and persisted) instead of inside the legacy chunker.
            resolved_doc_type = resolved_doc_type or detect_doc_type(structure)
            plan = build_chunk_plan(
                structure,
                context,
                doc_type=resolved_doc_type,
                params=params_for(resolved_doc_type, settings),
                tables=list(converted.tables or []),
                chunker_version=PARENT_CHILD_VERSION,
            )
            drafts = plan.children
        else:
            drafts = chunk_structure(
                structure,
                context,
                doc_type=resolved_doc_type,
                chunk_size=chunk_size,
                overlap=overlap,
                chunker_version=resolved_version,
            )
        if not drafts:
            raise ValueError("切分后没有生成任何片段")
        version.chunker_version = drafts[0].chunker_version if drafts else ""

        await self._set_stage(session, document, version, "embedding")
        chunks = await self._embed_drafts(drafts, context)

        await self._set_stage(session, document, version, "indexing")
        inserted = self._store.insert(chunks)
        old_version_id = document.current_version_id

        conversion_meta["images"] = len(image_blocks)
        if plan is not None:
            await self._store_parents(session, document, version, plan)
            conversion_meta["table_files"] = await self._store_tables(
                session, document, version, plan
            )
            conversion_meta["parents"] = len(plan.parents)
            conversion_meta["tables"] = len(plan.tables)
            conversion_meta["table_sheets"] = [table.name for table in plan.tables][:20]
            version.parent_count = len(plan.parents)
            version.table_count = len(plan.tables)
        else:
            conversion_meta["table_files"] = self._store_converted_tables(document, version, converted)
        version.conversion_report = conversion_meta
        if resolved_doc_type:
            version.doc_type = resolved_doc_type
        version.status = "ready"
        version.stage = "ready"
        version.chunk_count = inserted
        version.error_message = image_warning
        document.status = "ready"
        document.stage = "ready"
        document.page_count = converted.page_count
        document.current_version_id = version.id
        document.error_message = image_warning
        await session.commit()
        logger.info(
            "Indexed doc=%s version=%s chunks=%s (replacing %s)",
            document.id,
            version.id,
            inserted,
            old_version_id,
        )

        if old_version_id and old_version_id != version.id:
            await asyncio.to_thread(self._store.delete_by_version, old_version_id)
            self._storage.delete_version_assets(document.id, old_version_id)
            await self._delete_version_rows(session, old_version_id)
            await session.commit()

    async def _convert_to_markdown(
        self, document: Document, version: DocumentVersion, file_path: Path
    ) -> ConversionResult:
        settings = self._settings or get_settings()
        self._last_triage = {}
        self._last_plan = []
        self._last_failures = []
        if self._converter is not None:
            candidates: list[tuple[str, FileConverter]] = [("injected", self._converter)]
        else:
            parse_mode = (version.parse_mode or "auto").lower()
            triage = self._triage(file_path, document.filename, parse_mode, settings)
            docling_candidate = False
            if settings.docling_enabled:
                docling_candidate = await docling_available(settings)
            candidates = self._plan_converters(
                document.filename, parse_mode, settings, triage, docling_candidate
            )
        self._last_plan = [label for label, _ in candidates]

        cache = self._parse_cache(settings)
        digest = ""
        if cache.enabled:
            try:
                digest = cache.file_digest(file_path)
            except OSError:
                logger.warning("Could not hash %s for the parse cache", file_path, exc_info=True)

        errors: list[tuple[str, AppError]] = []
        for index, (label, converter) in enumerate(candidates):
            key = cache.key_for(digest, converter) if digest else ""
            if key:
                cached = cache.load(key)
                if cached is not None:
                    logger.info("Parse cache hit for %s (%s)", document.filename, label)
                    self._last_conversion_meta = self._conversion_meta(
                        converter, label, index, cache_hit=True
                    )
                    return cached
            try:
                result = await convert_safely(converter, str(file_path), label=label)
            except AppError as exc:
                errors.append((label, exc))
                self._last_failures.append({"label": label, "error": str(exc)[:200]})
                if index + 1 < len(candidates) and _is_recoverable(exc):
                    logger.info(
                        "Converter %s failed on %s (%s), falling back to the next candidate",
                        label,
                        document.filename,
                        str(exc)[:200],
                    )
                    continue
                break
            if key:
                cache.save(key, result, source=document.filename)
            self._last_conversion_meta = self._conversion_meta(
                converter, label, index, cache_hit=False
            )
            return result

        if errors:
            _label, exc = errors[-1]
            if (
                isinstance(exc, NoExtractableContentError)
                and not settings.mineru_enabled
                and Path(document.filename).suffix.lower() == ".pdf"
            ):
                raise AppError(
                    "未能从 PDF 中提取任何内容（可能是扫描件）：配置 KB_MINERU_URL 并启动 "
                    "MinerU OCR 服务后会自动走 OCR 解析"
                ) from exc
            raise exc
        raise AppError(f"没有可用的转换器处理文件：{document.filename}")

    def _triage(
        self,
        file_path: Path,
        filename: str,
        parse_mode: str,
        settings: Settings,
    ) -> TriageResult | None:
        if not settings.conversion_triage_enabled:
            return None
        try:
            result = triage_file(file_path, filename, parse_mode=parse_mode)
        except Exception:
            logger.warning("Conversion triage failed for %s", filename, exc_info=True)
            return None
        self._last_triage = result.as_report()
        return result

    @staticmethod
    def _parse_cache(settings: Settings) -> ParseCache:
        root = settings.document_storage_dir or ""
        return ParseCache(
            str(Path(root) / "_parse_cache") if root else "",
            enabled=bool(root) and settings.parse_cache_enabled,
        )

    @staticmethod
    def _conversion_meta(
        converter: FileConverter, label: str, index: int, *, cache_hit: bool
    ) -> dict:
        return {
            "converter": getattr(converter, "name", "") or type(converter).__name__,
            "converter_class": type(converter).__name__,
            "converter_version": getattr(converter, "version", ""),
            "label": label,
            "attempts": index + 1,
            "fallback_used": index > 0,
            "cache_hit": cache_hit,
        }

    def _conversion_evidence(self, converted: ConversionResult) -> dict:
        tables = list(getattr(converted, "tables", None) or [])
        return {
            "triage": dict(getattr(self, "_last_triage", {}) or {}),
            "plan": list(getattr(self, "_last_plan", []) or []),
            "failed": list(getattr(self, "_last_failures", []) or []),
            "page_count": converted.page_count,
            "tables": len(tables),
            "table_sheets": [table.sheet for table in tables][:20],
            "ocr_pages": list(getattr(converted, "ocr_pages", None) or []),
        }

    @staticmethod
    def _uses_parent_child(chunker_version: str) -> bool:
        return str(chunker_version or "").startswith(PARENT_CHILD_VERSION)

    async def _store_parents(
        self,
        session: AsyncSession,
        document: Document,
        version: DocumentVersion,
        plan: ChunkPlan,
    ) -> None:
        """Persist parent chunks (generation context) in PostgreSQL."""
        for parent in plan.parents:
            session.add(
                ChunkParent(
                    **parent.as_row(
                        tenant_id=document.tenant_id,
                        doc_id=document.id,
                        version_id=version.id,
                    )
                )
            )
        if plan.parents:
            await session.flush()
            logger.info("Stored %d parent chunk(s) for version=%s", len(plan.parents), version.id)

    async def _store_tables(
        self,
        session: AsyncSession,
        document: Document,
        version: DocumentVersion,
        plan: ChunkPlan,
    ) -> list[str]:
        """Write each table grid to storage and register it in `document_tables`."""
        keys: list[str] = []
        for index, table in enumerate(plan.tables):
            name = f"{index:03d}-{table.name or 'table'}"
            payload = json.dumps(
                {
                    "id": table.id,
                    "name": table.name,
                    "header": table.header,
                    "rows": table.rows,
                    "summary": table.summary,
                    "source": table.source,
                    "page": table.page,
                    "section": table.section,
                    "heading_path": table.heading_path,
                },
                ensure_ascii=False,
            )
            storage_key = ""
            try:
                storage_key = self._storage.store_table(document.id, version.id, name, payload)
                keys.append(storage_key)
            except Exception:
                logger.warning("Could not store table %s", name, exc_info=True)
            row = table.as_row(
                tenant_id=document.tenant_id,
                doc_id=document.id,
                version_id=version.id,
                chunker_version=version.chunker_version or "",
            )
            row["storage_key"] = storage_key
            session.add(DocumentTable(**row))
        if plan.tables:
            await session.flush()
            logger.info("Stored %d table asset(s) for version=%s", len(plan.tables), version.id)
        return keys

    def _store_converted_tables(
        self, document: Document, version: DocumentVersion, converted: ConversionResult
    ) -> list[str]:
        """Legacy (`structure-v1`) path: cache converter table grids as files only."""
        keys: list[str] = []
        for index, table in enumerate(getattr(converted, "tables", None) or []):
            name = f"{index:03d}-{table.sheet or 'sheet'}"
            try:
                payload = table.model_dump_json()
            except Exception:
                logger.warning("Could not serialize table %s", name, exc_info=True)
                continue
            try:
                keys.append(self._storage.store_table(document.id, version.id, name, payload))
            except Exception:
                logger.warning("Could not store table %s", name, exc_info=True)
        return keys

    @staticmethod
    async def _delete_version_rows(session: AsyncSession, version_id: str) -> None:
        """Drop every derived row of one version (images, parents, tables)."""
        await session.execute(delete(DocumentImage).where(DocumentImage.version_id == version_id))
        await session.execute(delete(ChunkParent).where(ChunkParent.version_id == version_id))
        await session.execute(delete(DocumentTable).where(DocumentTable.version_id == version_id))

    @staticmethod
    def _plan_converters(
        filename: str,
        parse_mode: str,
        settings: Settings,
        triage: TriageResult | None = None,
        docling_candidate: bool = False,
    ) -> list[tuple[str, FileConverter]]:
        return plan_candidates(
            filename,
            parse_mode,
            settings,
            triage,
            docling_candidate=docling_candidate,
        )
    async def _embed_drafts(self, drafts: list[ChunkDraft], context: ChunkContext) -> list[ChunkRecord]:
        settings = self._settings or get_settings()
        batch_size = max(settings.embed_batch_size, 1)
        chunks: list[ChunkRecord] = []
        total = len(drafts)
        for start in range(0, total, batch_size):
            batch = drafts[start : start + batch_size]
            vectors = await self._embedder.embed([item.text for item in batch])
            for draft, vector in zip(batch, vectors, strict=False):
                chunks.append(
                    ChunkRecord(
                        id=f"{context.version_id}-{draft.chunk_index}",
                        text=draft.text,
                        title=context.title,
                        doc_id=context.doc_id,
                        version_id=context.version_id,
                        chunk_index=draft.chunk_index,
                        page=draft.page,
                        section=draft.section,
                        tenant_id=context.tenant_id,
                        vector=vector,
                        chunk_type=draft.chunk_type,
                        heading_path=draft.heading_path,
                        clause_no=draft.clause_no,
                        step_no=draft.step_no,
                        faq_id=draft.faq_id,
                        table_id=draft.table_id,
                        row_start=draft.row_start,
                        row_end=draft.row_end,
                        row_index=draft.row_index,
                        parent_id=draft.parent_id,
                        chunker_version=draft.chunker_version,
                        image_id=draft.image_id,
                        chunk_kind=draft.chunk_kind,
                        doc_type=draft.doc_type,
                    )
                )
            done = min(start + batch_size, total)
            if (start // batch_size) % 5 == 0 or done >= total:
                logger.info(
                    "Embedded %d/%d chunks (version=%s, batch_size=%d)",
                    done,
                    total,
                    context.version_id,
                    batch_size,
                )
        return chunks

    async def _set_stage(
        self, session: AsyncSession, document: Document, version: DocumentVersion, stage: str
    ) -> None:
        document.stage = stage
        version.stage = stage
        await session.commit()
