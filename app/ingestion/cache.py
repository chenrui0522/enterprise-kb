"""Content-addressed parse cache for converted documents.

The cache key is derived from the file bytes plus the converter identity
(name, version and output-affecting parameters), so re-ingesting an unchanged
file with an unchanged converter reuses the previous parse result instead of
paying for MinerU/Docling/PyMuPDF again - and any converter upgrade or
parameter change automatically misses the cache.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from app.core.logging import get_logger
from app.ingestion.converters import ConversionResult, FileConverter
from app.ingestion.images import ImageAsset
from app.ingestion.structure import DocumentStructure, TableArtifact

logger = get_logger("ingestion.cache")

#: Bump when the on-disk payload layout changes so old entries are ignored.
CACHE_FORMAT_VERSION = "1"
#: Entries larger than this are skipped (image-heavy OCR results).
MAX_CACHE_BYTES = 64 * 1024 * 1024


class ParseCache:
    """JSON files under one directory, addressed by content digest."""

    def __init__(self, root: str | Path, *, enabled: bool = True) -> None:
        self._root = Path(root) if root else Path()
        self._enabled = bool(enabled) and bool(str(root))

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def root(self) -> Path:
        return self._root

    # ------------------------------------------------------------------
    # Keys
    # ------------------------------------------------------------------
    @staticmethod
    def file_digest(file_path: str | Path) -> str:
        digest = hashlib.sha256()
        with open(file_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def signature_key(digest: str, signature: dict) -> str:
        payload = json.dumps(
            {"digest": digest, "signature": signature},
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def key_for(self, digest: str, converter: FileConverter) -> str:
        try:
            signature = converter.cache_signature()
        except Exception:  # pragma: no cover - defensive: unknown converter
            signature = {"converter": type(converter).__name__}
        return self.signature_key(digest, signature)

    def path_for(self, key: str) -> Path:
        return self._root / f"{key}.json"

    # ------------------------------------------------------------------
    # Read / write
    # ------------------------------------------------------------------
    def load(self, key: str) -> ConversionResult | None:
        if not self.enabled:
            return None
        path = self.path_for(key)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("format") != CACHE_FORMAT_VERSION:
                return None
            return _decode_result(payload)
        except Exception:
            logger.warning("Ignoring unreadable parse cache entry %s", path, exc_info=True)
            return None

    def save(self, key: str, result: ConversionResult, *, source: str = "") -> bool:
        if not self.enabled:
            return False
        try:
            payload = _encode_result(result, source=source)
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        except Exception:
            logger.warning("Could not serialize parse result for caching", exc_info=True)
            return False
        if len(encoded) > MAX_CACHE_BYTES:
            logger.info("Parse cache entry too large (%d bytes), skipping", len(encoded))
            return False
        path = self.path_for(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(f".{datetime.now(UTC).timestamp()}.tmp")
            temp.write_bytes(encoded)
            temp.replace(path)
        except Exception:
            logger.warning("Could not write parse cache entry %s", path, exc_info=True)
            return False
        return True

    def clear(self) -> int:
        if not self._root.is_dir():
            return 0
        removed = 0
        for entry in self._root.glob("*.json"):
            try:
                entry.unlink()
                removed += 1
            except OSError:
                logger.debug("Could not remove cache entry %s", entry, exc_info=True)
        return removed


def _encode_result(result: ConversionResult, *, source: str = "") -> dict:
    return {
        "format": CACHE_FORMAT_VERSION,
        "cached_at": datetime.now(UTC).isoformat(),
        "source": source,
        "markdown": result.markdown or "",
        "page_count": result.page_count,
        "ocr_pages": list(result.ocr_pages or []),
        "triage": dict(result.triage or {}),
        "structure": result.structure.model_dump() if result.structure is not None else None,
        "images": [_encode_image(asset) for asset in result.images or []],
        "tables": [
            table.model_dump() if hasattr(table, "model_dump") else dict(table)
            for table in result.tables or []
        ],
    }


def _decode_result(payload: dict) -> ConversionResult:
    raw_structure = payload.get("structure")
    structure = DocumentStructure.model_validate(raw_structure) if raw_structure is not None else None
    images = [_decode_image(item) for item in payload.get("images") or []]
    tables = [TableArtifact.model_validate(item) for item in payload.get("tables") or []]
    return ConversionResult(
        markdown=payload.get("markdown") or "",
        page_count=payload.get("page_count"),
        structure=structure,
        images=images,
        tables=tables,
        triage=dict(payload.get("triage") or {}),
        ocr_pages=[int(page) for page in payload.get("ocr_pages") or []],
    )


def _encode_image(asset: ImageAsset) -> dict:
    return {
        "data": base64.b64encode(asset.data).decode("ascii"),
        "mime": asset.mime,
        "page": asset.page,
        "bbox": list(asset.bbox) if asset.bbox else None,
        "caption": asset.caption,
        "source": asset.source,
        "width": asset.width,
        "height": asset.height,
        "heading_path": asset.heading_path,
    }


def _decode_image(payload: dict) -> ImageAsset:
    bbox = payload.get("bbox")
    return ImageAsset(
        data=base64.b64decode(payload.get("data") or ""),
        mime=payload.get("mime") or "image/png",
        page=int(payload.get("page") or 0),
        bbox=tuple(float(value) for value in bbox) if bbox else None,
        caption=payload.get("caption") or "",
        source=payload.get("source") or "cache",
        width=int(payload.get("width") or 0),
        height=int(payload.get("height") or 0),
        heading_path=payload.get("heading_path") or "",
    )