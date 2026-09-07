from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.ingestion.chunker import ChunkContext, chunk_markdown
from app.ingestion.converters import (
    ConversionResult,
    FileConverter,
    IMAGE_EXTENSIONS,
    NoExtractableContentError,
    PDFMarkdownConverter,
    converter_for,
)
from app.ingestion.mineru import MinerUConverter
from app.ingestion.models import ChunkDraft
from app.ingestion.storage import FileDocumentStorage
from app.models.entity import Document, DocumentVersion
from app.providers.base import Embedder
from app.retrieval.chunk import ChunkRecord
from app.retrieval.milvus_store import MilvusStore

logger = get_logger("ingestion.pipeline")


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

    async def process_job(self, session: AsyncSession, job: dict, chunk_size: int, overlap: int) -> None:
        doc_id = job["doc_id"]
        version_id = job["version_id"]
        document = await session.get(Document, doc_id)
        version = await session.get(DocumentVersion, version_id)
        if document is None or version is None:
            logger.error("Ingestion job refers to missing rows: %s", job)
            return

        try:
            await self._run(session, document, version, job, chunk_size, overlap)
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
    ) -> None:
        file_path = self._storage.resolve(job["storage_key"])

        await self._set_stage(session, document, version, "parsing")
        converted = await self._convert_to_markdown(document, version, file_path)
        markdown = converted.markdown

        await self._set_stage(session, document, version, "chunking")
        context = ChunkContext(
            doc_id=document.id,
            version_id=version.id,
            tenant_id=document.tenant_id,
            title=document.title,
        )
        drafts = chunk_markdown(markdown, context, chunk_size=chunk_size, overlap=overlap)
        if not drafts:
            raise ValueError("切分后没有生成任何片段")

        await self._set_stage(session, document, version, "embedding")
        chunks = await self._embed_drafts(drafts, context)

        await self._set_stage(session, document, version, "indexing")
        inserted = self._store.insert(chunks)
        old_version_id = document.current_version_id

        version.status = "ready"
        version.stage = "ready"
        version.chunk_count = inserted
        version.error_message = None
        document.status = "ready"
        document.stage = "ready"
        document.page_count = converted.page_count
        document.current_version_id = version.id
        document.error_message = None
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

    async def _convert_to_markdown(
        self, document: Document, version: DocumentVersion, file_path: Path
    ) -> ConversionResult:
        settings = self._settings or get_settings()
        if self._converter is not None:
            candidates = [("injected", self._converter)]
        else:
            parse_mode = (version.parse_mode or "auto").lower()
            candidates = self._plan_converters(document.filename, parse_mode, settings)

        last_error: BaseException | None = None
        for index, (label, converter) in enumerate(candidates):
            try:
                return await converter.convert_async(str(file_path))
            except NoExtractableContentError as exc:
                last_error = exc
                if index + 1 < len(candidates):
                    logger.info(
                        "No extractable text from %s, falling back to next converter (%s)",
                        document.filename,
                        label,
                    )
                    continue
                if not settings.mineru_enabled and document.filename.lower().endswith(".pdf"):
                    raise AppError(
                        "未能从 PDF 中提取任何内容（可能是扫描件）：配置 KB_MINERU_URL 并启动 "
                        "MinerU OCR 服务后会自动走 OCR 解析"
                    ) from exc
                raise
        if last_error is not None:
            raise last_error
        raise AppError(f"没有可用的转换器处理文件：{document.filename}")

    @staticmethod
    def _plan_converters(
        filename: str, parse_mode: str, settings: Settings
    ) -> list[tuple[str, FileConverter]]:
        suffix = Path(filename).suffix.lower()
        if suffix in IMAGE_EXTENSIONS:
            if not settings.mineru_enabled:
                raise AppError(
                    "图片解析需要 MinerU OCR：请配置 KB_MINERU_URL 并启动 mineru-api 服务",
                    status_code=503,
                )
            return [("ocr", MinerUConverter(settings))]
        if parse_mode == "ocr":
            if suffix not in {".pdf", *IMAGE_EXTENSIONS}:
                raise AppError("强制 OCR（parse_mode=ocr）仅支持 PDF 与图片文件")
            if not settings.mineru_enabled:
                raise AppError(
                    "OCR 解析需要 MinerU 服务：请配置 KB_MINERU_URL 并启动 mineru-api 服务",
                    status_code=503,
                )
            return [("ocr", MinerUConverter(settings))]
        if suffix == ".pdf":
            candidates: list[tuple[str, FileConverter]] = [("text", PDFMarkdownConverter())]
            if settings.mineru_enabled:
                candidates.append(("ocr", MinerUConverter(settings)))
            return candidates
        return [("text", converter_for(filename))]

    async def _embed_drafts(self, drafts: list[ChunkDraft], context: ChunkContext) -> list[ChunkRecord]:
        chunks: list[ChunkRecord] = []
        for start in range(0, len(drafts), 32):
            batch = drafts[start : start + 32]
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
                    )
                )
        return chunks

    async def _set_stage(
        self, session: AsyncSession, document: Document, version: DocumentVersion, stage: str
    ) -> None:
        document.stage = stage
        version.stage = stage
        await session.commit()
