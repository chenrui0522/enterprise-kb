from __future__ import annotations

import asyncio
import io
import time
import zipfile
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import AppError, UpstreamError
from app.core.logging import get_logger
from app.ingestion.converters import ConversionResult, FileConverter

logger = get_logger("ingestion.mineru")


class MinerUConverter(FileConverter):
    """Parses scanned PDFs / images / complex layout files through a remote
    mineru-api service (opendatalab MinerU 3.x async task API).

    The markdown returned by MinerU flows into the same "Markdown -> chunking ->
    embedding" pipeline, so OCR documents keep citations by heading section
    (page markers are not guaranteed by MinerU and therefore not fabricated).
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    # ------------------------------------------------------------------
    # FileConverter interface
    # ------------------------------------------------------------------
    def convert(self, file_path: str) -> ConversionResult:
        # Called by the ingestion worker inside a worker thread, so it is safe
        # to drive the async HTTP flow through a short-lived event loop here.
        return asyncio.run(self.convert_async(file_path))

    async def convert_async(self, file_path: str) -> ConversionResult:
        settings = self._settings
        if not settings.mineru_enabled:
            raise AppError(
                "MinerU OCR 服务未启用：请在 .env 中配置 KB_MINERU_URL 并启动 mineru-api",
                status_code=503,
            )
        base_url = settings.mineru_url.rstrip("/")
        timeout = httpx.Timeout(settings.mineru_timeout_seconds, connect=10.0)
        headers = {}
        if settings.mineru_api_key:
            headers["Authorization"] = f"Bearer {settings.mineru_api_key}"

        async with httpx.AsyncClient(base_url=base_url, timeout=timeout, headers=headers) as client:
            await self._check_health(client, base_url)
            task_id = await self._submit(client, file_path)
            payload = await self._wait_terminal(client, base_url, task_id)
            markdown = await self._fetch_markdown(client, base_url, task_id, payload)

        if not markdown.strip():
            raise UpstreamError("MinerU 解析完成但未返回任何 Markdown 内容")
        logger.info("MinerU OCR finished for %s (task=%s)", file_path, task_id)
        return ConversionResult(markdown=markdown, page_count=None)

    # ------------------------------------------------------------------
    # mineru-api client
    # ------------------------------------------------------------------
    async def _check_health(self, client: httpx.AsyncClient, base_url: str) -> None:
        try:
            response = await client.get("/health")
        except httpx.HTTPError as exc:
            raise AppError(
                f"无法连接 MinerU OCR 服务（{base_url}）：{exc}",
                status_code=503,
            ) from exc
        if response.status_code >= 400:
            raise AppError(
                f"MinerU OCR 服务不可用（HTTP {response.status_code}）：{response.text[:200]}",
                status_code=503,
            )

    async def _submit(self, client: httpx.AsyncClient, file_path: str) -> str:
        name = file_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        with open(file_path, "rb") as handle:
            data = handle.read()
        settings = self._settings
        form = {
            "return_md": "true",
            "response_format_zip": "false",
            "backend": settings.mineru_backend,
            "lang_list": settings.mineru_lang,
            "table_enable": str(settings.mineru_table_enable).lower(),
            "formula_enable": str(settings.mineru_formula_enable).lower(),
        }
        files = [("files", (name, data, _guess_mime(name)))]
        try:
            response = await client.post("/tasks", data=form, files=files)
        except httpx.HTTPError as exc:
            raise UpstreamError(f"提交 MinerU 解析任务失败：{exc}") from exc
        if response.status_code >= 400:
            raise UpstreamError(
                f"MinerU 拒绝解析任务（HTTP {response.status_code}）：{response.text[:300]}"
            )
        payload = response.json()
        task_id = _find_task_id(payload)
        if not task_id:
            raise UpstreamError(f"MinerU 提交响应缺少 task_id：{str(payload)[:300]}")
        return task_id

    async def _wait_terminal(
        self, client: httpx.AsyncClient, base_url: str, task_id: str
    ) -> dict[str, Any]:
        settings = self._settings
        deadline = time.monotonic() + settings.mineru_timeout_seconds
        last_logged: str | None = None
        while time.monotonic() < deadline:
            try:
                response = await client.get(f"/tasks/{task_id}")
            except httpx.HTTPError as exc:
                raise UpstreamError(f"查询 MinerU 任务状态失败：{exc}") from exc
            if response.status_code == 404:
                raise UpstreamError("MinerU 任务不存在（任务可能已被服务端清理）")
            if response.status_code >= 400:
                raise UpstreamError(
                    f"MinerU 状态查询异常（HTTP {response.status_code}）：{response.text[:300]}"
                )
            payload = response.json()
            status = _find_status(payload)
            if not status:
                raise UpstreamError(f"MinerU 状态响应缺少 status：{str(payload)[:300]}")
            normalized = status.lower()
            if normalized in _TERMINAL_BAD:
                error = _find_error(payload) or status
                raise UpstreamError(f"MinerU 解析失败：{error}")
            if normalized in _TERMINAL_OK:
                return payload
            if normalized != last_logged:
                logger.info("MinerU task %s status=%s", task_id, normalized)
                last_logged = normalized
            await asyncio.sleep(settings.mineru_poll_interval)
        raise AppError(
            f"MinerU 解析超时（>{settings.mineru_timeout_seconds}s），task_id={task_id}",
            status_code=504,
        )

    async def _fetch_markdown(
        self, client: httpx.AsyncClient, base_url: str, task_id: str, status_payload: dict[str, Any]
    ) -> str:
        try:
            response = await client.get(f"/tasks/{task_id}/result")
        except httpx.HTTPError as exc:
            raise UpstreamError(f"获取 MinerU 解析结果失败：{exc}") from exc
        if response.status_code >= 400:
            raise UpstreamError(
                f"MinerU 结果获取异常（HTTP {response.status_code}）：{response.text[:300]}"
            )

        content_type = response.headers.get("content-type", "")
        body = response.content
        if "zip" in content_type or body[:2] == b"PK":
            markdown = _read_markdown_from_zip(body)
            if markdown:
                return markdown
        try:
            payload = response.json()
        except ValueError as exc:
            raise UpstreamError("MinerU 返回了无法解析的结果数据") from exc
        filename = _primary_filename(status_payload) or ""
        markdown = _extract_markdown(payload, filename)
        if markdown:
            return markdown
        raise UpstreamError(f"MinerU 结果中未找到 Markdown：{str(payload)[:300]}")


_TERMINAL_OK = {"completed", "done", "success"}
_TERMINAL_BAD = {"failed", "error", "cancelled"}


def _guess_mime(filename: str) -> str:
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        "pdf": "application/pdf",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
    }.get(suffix, "application/octet-stream")


def _find_task_id(payload: Any) -> str | None:
    if isinstance(payload, dict):
        if isinstance(payload.get("task_id"), str) and payload["task_id"]:
            return payload["task_id"]
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("task_id"), str) and data["task_id"]:
            return data["task_id"]
    return None


def _find_status(payload: Any) -> str | None:
    if isinstance(payload, dict):
        if isinstance(payload.get("status"), str) and payload["status"]:
            return payload["status"]
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("status"), str) and data["status"]:
            return data["status"]
    return None


def _find_error(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("error"), str) and payload["error"]:
        return payload["error"]
    if isinstance(payload.get("message"), str) and payload["message"]:
        return payload["message"]
    return None


def _primary_filename(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    file_names = payload.get("file_names")
    if isinstance(file_names, list) and file_names:
        return str(file_names[0])
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("file_names"), list) and data["file_names"]:
        return str(data["file_names"][0])
    return None


def _extract_markdown(payload: Any, filename: str = "") -> str:
    if not isinstance(payload, dict):
        return ""
    results = payload.get("results")
    if isinstance(results, dict):
        best = ""
        best_score = -1
        for name, entry in results.items():
            if not isinstance(entry, dict):
                continue
            content = entry.get("md_content")
            if not isinstance(content, str) or not content.strip():
                continue
            score = 1 if filename and (name == filename or name.endswith(filename)) else 0
            if score > best_score:
                best, best_score = content, score
        if best:
            return best
    data = payload.get("data")
    if isinstance(data, dict):
        batch = data.get("batch_result_list")
        if isinstance(batch, list) and batch:
            first = batch[0]
            if isinstance(first, dict) and isinstance(first.get("md_content"), str):
                return first["md_content"]
        if isinstance(data.get("md_content"), str):
            return data["md_content"]
    return ""


def _read_markdown_from_zip(content: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            md_entries = [name for name in archive.namelist() if name.lower().endswith(".md")]
            if not md_entries:
                return ""
            # Prefer a top-level Markdown file over nested subdirectories.
            md_entries.sort(key=lambda name: (name.count("/"), len(name)))
            return archive.read(md_entries[0]).decode("utf-8", errors="replace")
    except zipfile.BadZipFile:
        return ""
