"""Docling client: structured PDF/Office conversion through an HTTP service.

Docling runs as its own container (see `docker/docling`) and is reached over
HTTP, mirroring the MinerU integration: the worker never imports a heavy
inference stack. When the service is not configured or not healthy the
candidate is skipped and the pipeline falls back to the local converters.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import AppError, UpstreamError
from app.core.logging import get_logger
from app.ingestion.converters import ConversionResult, FileConverter
from app.ingestion.structure import (
    BLOCK_CODE,
    BLOCK_HEADING,
    BLOCK_LIST,
    BLOCK_PARAGRAPH,
    BLOCK_TABLE,
    Block,
    DocumentStructure,
    structure_from_markdown,
    structure_to_markdown,
)

logger = get_logger("ingestion.docling")

ALLOWED_BLOCK_TYPES = {
    BLOCK_HEADING,
    BLOCK_PARAGRAPH,
    BLOCK_LIST,
    BLOCK_TABLE,
    BLOCK_CODE,
}
#: Health probes are cached for a few seconds so a burst of uploads does not
#: hammer the service with readiness checks.
AVAILABILITY_TTL_SECONDS = 30.0
_availability_cache: dict[str, tuple[float, bool]] = {}


class DoclingConverter(FileConverter):
    """Converts a file through the Docling HTTP service."""

    name = "docling"
    version = "1"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    # ------------------------------------------------------------------
    # FileConverter interface
    # ------------------------------------------------------------------
    def convert(self, file_path: str) -> ConversionResult:
        import asyncio

        return asyncio.run(self.convert_async(file_path))

    async def convert_async(self, file_path: str) -> ConversionResult:
        settings = self._settings
        if not settings.docling_enabled:
            raise AppError(
                "Docling 转换服务未启用：请在 .env 中配置 KB_DOCLING_URL 并启动 docling-api",
                status_code=503,
            )
        base_url = settings.docling_url.rstrip("/")
        timeout = httpx.Timeout(settings.docling_timeout_seconds, connect=10.0)
        async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
            await self._check_health(client, base_url)
            payload = await self._post_convert(client, file_path)
        result = map_docling_payload(payload)
        if not (result.markdown or "").strip():
            raise UpstreamError("Docling 解析完成但未返回任何内容")
        logger.info("Docling conversion finished for %s", file_path)
        return result

    def cache_signature(self) -> dict:
        settings = self._settings
        return {
            **super().cache_signature(),
            "params": {
                "ocr": bool(settings.docling_ocr_enabled),
                "tables": bool(settings.docling_table_mode),
                "table_mode": settings.docling_table_mode,
                "to_formats": "md",
            },
        }

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------
    async def _check_health(self, client: httpx.AsyncClient, base_url: str) -> None:
        try:
            response = await client.get("/health", timeout=10.0)
        except httpx.HTTPError as exc:
            raise AppError(
                f"无法连接 Docling 解析服务（{base_url}）：{exc}",
                status_code=503,
            ) from exc
        if response.status_code >= 400:
            raise AppError(
                f"Docling 解析服务不可用（HTTP {response.status_code}）：{response.text[:200]}",
                status_code=503,
            )

    async def _post_convert(self, client: httpx.AsyncClient, file_path: str) -> dict:
        name = Path(file_path).name
        with open(file_path, "rb") as handle:
            data = handle.read()
        settings = self._settings
        form = {
            "to_formats": "md",
            "do_ocr": str(bool(settings.docling_ocr_enabled)).lower(),
            "table_mode": settings.docling_table_mode,
            "return_blocks": "true",
        }
        files = {"files": (name, data, _guess_mime(name))}
        try:
            response = await client.post("/convert", data=form, files=files)
        except httpx.HTTPError as exc:
            raise UpstreamError(f"调用 Docling 解析服务失败：{exc}") from exc
        if response.status_code >= 400:
            raise UpstreamError(
                f"Docling 解析失败（HTTP {response.status_code}）：{response.text[:300]}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise UpstreamError("Docling 返回了无法解析的响应") from exc
        if not isinstance(payload, dict):
            raise UpstreamError("Docling 返回了意外的响应结构")
        return payload


async def docling_available(settings: Settings | None = None, *, force: bool = False) -> bool:
    """True when a Docling service is configured and currently healthy."""
    settings = settings or get_settings()
    if not settings.docling_enabled:
        return False
    base_url = settings.docling_url.rstrip("/")
    now = time.monotonic()
    cached = _availability_cache.get(base_url)
    if cached and not force and now - cached[0] < AVAILABILITY_TTL_SECONDS:
        return cached[1]
    healthy = False
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(5.0, connect=3.0)) as client:
            response = await client.get("/health")
            healthy = response.status_code < 400
    except Exception:
        logger.info("Docling service not reachable at %s; skipping candidate", base_url)
    _availability_cache[base_url] = (now, healthy)
    return healthy


def reset_availability_cache() -> None:
    _availability_cache.clear()


def map_docling_payload(payload: dict[str, Any]) -> ConversionResult:
    """Map a Docling service response onto our normalized structure.

    The service returns markdown plus optional typed blocks; anything the
    service does not describe is recovered from the markdown itself so the
    chunker always receives a usable structure.
    """
    markdown = _first_str(payload, ("markdown", "md", "text"))
    page_count = _first_int(payload, ("page_count", "pages"))
    blocks = _map_blocks(payload.get("blocks"))
    if blocks:
        structure = DocumentStructure(blocks=blocks, page_count=page_count)
        if not markdown.strip():
            markdown = structure_to_markdown(structure)
    else:
        structure = structure_from_markdown(markdown, page_count=page_count)
    return ConversionResult(
        markdown=markdown or "",
        page_count=page_count,
        structure=structure,
        triage={"converter_service": "docling", "pages_reported": page_count or 0},
    )


def _map_blocks(raw_blocks: Any) -> list[Block]:
    if not isinstance(raw_blocks, list):
        return []
    blocks: list[Block] = []
    for item in raw_blocks:
        if not isinstance(item, dict):
            continue
        block_type = str(item.get("type") or "").strip().lower()
        if block_type not in ALLOWED_BLOCK_TYPES:
            block_type = BLOCK_PARAGRAPH
        header = _string_list(item.get("header"))
        rows = _row_list(item.get("rows"))
        items = _string_list(item.get("items"))
        text = str(item.get("text") or "").strip()
        if block_type == BLOCK_TABLE and not text and header:
            text = ""
        if not (text or header or rows or items):
            continue
        blocks.append(
            Block(
                type=block_type,
                text=text,
                level=int(item.get("level") or 0),
                page=int(item.get("page") or 0),
                header=header,
                rows=rows,
                items=items,
                y0=float(item.get("y0") or 0.0),
                x0=float(item.get("x0") or 0.0),
            )
        )
    return blocks


def _first_str(payload: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _first_int(payload: dict, keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
    return None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return ["" if item is None else str(item) for item in value]


def _row_list(value: Any) -> list[list[str]]:
    if not isinstance(value, list):
        return []
    rows: list[list[str]] = []
    for row in value:
        if isinstance(row, list):
            rows.append(["" if cell is None else str(cell) for cell in row])
    return rows


def _guess_mime(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".html": "text/html",
        ".htm": "text/html",
        ".md": "text/markdown",
        ".txt": "text/plain",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }.get(suffix, "application/octet-stream")