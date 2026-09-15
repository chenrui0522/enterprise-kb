"""Minimal HTTP wrapper around Docling, mirroring the mineru-api contract.

The knowledge base never imports Docling itself: the worker posts a file to
`POST /convert` and receives markdown plus optional typed blocks, so the
parsing models and their (large) weights stay out of the app image.

Contract
--------
GET  /health   -> {"status": "ok"}
POST /convert  -> multipart `files` + form options
                  {"markdown": str, "page_count": int, "blocks": [Block]}

All fields except `files` are optional; the service always returns markdown
and falls back to an empty block list, which the client turns back into a
structure with `structure_from_markdown`.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

logger = logging.getLogger("docling-api")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(title="docling-api", version="1.0")
_converter = None
_supported = {".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm", ".md", ".txt", ".png", ".jpg", ".jpeg"}


def _get_converter():
    """Build the Docling converter lazily (model weights load on first use)."""
    global _converter
    if _converter is None:
        from docling.document_converter import DocumentConverter

        _converter = DocumentConverter()
        logger.info("Docling converter initialised")
    return _converter


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/convert")
async def convert(
    files: list[UploadFile] = File(...),
    to_formats: str = Form("md"),
    do_ocr: bool = Form(True),
    table_mode: str = Form("accurate"),
    return_blocks: bool = Form(True),
) -> JSONResponse:
    if not files:
        raise HTTPException(status_code=400, detail="缺少待解析文件")
    upload = files[0]
    suffix = Path(upload.filename or "input.pdf").suffix.lower()
    if suffix not in _supported:
        raise HTTPException(status_code=415, detail=f"docling-api 不支持该格式：{suffix}")

    data = await upload.read()
    if not data:
        raise HTTPException(status_code=400, detail="上传文件为空")

    with tempfile.TemporaryDirectory(prefix="docling-") as directory:
        target = Path(directory) / f"input{suffix}"
        target.write_bytes(data)
        try:
            result = _get_converter().convert(str(target))
        except Exception as exc:  # pragma: no cover - depends on docling models
            logger.exception("Docling conversion failed for %s", upload.filename)
            raise HTTPException(status_code=502, detail=f"Docling 解析失败：{exc}") from exc

    document = result.document
    payload: dict = {
        "markdown": document.export_to_markdown() if to_formats == "md" else "",
        "page_count": _page_count(document),
    }
    if return_blocks:
        payload["blocks"] = _blocks(document)
    return JSONResponse(payload)


def _page_count(document) -> int:
    try:
        return int(getattr(document, "num_pages", lambda: 0)())
    except Exception:
        try:
            return len(getattr(document, "pages", {}) or {})
        except Exception:
            return 0


def _blocks(document) -> list[dict]:
    """Best-effort typed blocks; the client can always fall back to markdown."""
    blocks: list[dict] = []
    try:
        items = list(document.iterate_items())
    except Exception:
        return blocks
    for item, _level in _iter_items(items):
        label = str(getattr(item, "label", "") or "").lower()
        text = (getattr(item, "text", "") or "").strip()
        page = _item_page(item)
        if not text:
            continue
        if label in {"section_header", "title"}:
            blocks.append({"type": "heading", "text": text, "level": 1, "page": page})
        elif label in {"list_item"}:
            blocks.append({"type": "list", "items": [text], "text": text, "page": page})
        elif label in {"table"}:
            blocks.append(_table_block(item, page))
        elif label in {"code"}:
            blocks.append({"type": "code", "text": text, "page": page})
        else:
            blocks.append({"type": "paragraph", "text": text, "page": page})
    return [block for block in blocks if block]


def _iter_items(items) -> list[tuple]:
    normalized = []
    for entry in items:
        if isinstance(entry, tuple) and len(entry) == 2:
            normalized.append(entry)
        else:
            normalized.append((entry, 0))
    return normalized


def _item_page(item) -> int:
    try:
        provenance = getattr(item, "prov", None) or []
        if provenance:
            return int(getattr(provenance[0], "page_no", 0) or 0)
    except Exception:
        return 0
    return 0


def _table_block(item, page: int) -> dict:
    block: dict = {"type": "table", "page": page, "text": ""}
    try:
        frame = item.export_to_dataframe()
        header = [str(column) for column in frame.columns]
        rows = [[str(value) for value in row] for row in frame.itertuples(index=False, name=None)]
        block["header"] = header
        block["rows"] = rows
    except Exception:
        block["text"] = (getattr(item, "text", "") or "").strip()
    return block