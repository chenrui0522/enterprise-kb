"""Image extraction, filtering and MinerU ZIP parsing for document ingestion."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

from app.core.logging import get_logger

logger = get_logger("ingestion.images")

MIN_IMAGE_EDGE = 64
MIN_IMAGE_BYTES = 4 * 1024
IMAGE_MEDIA_PREFIXES = ("word/media/", "ppt/media/", "xl/media/", "media/")

EXT_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".emf": "image/emf",
    ".wmf": "image/wmf",
}
MIME_EXT = {mime: ext for ext, mime in EXT_MIME.items()}


@dataclass
class ImageAsset:
    data: bytes
    mime: str = "image/png"
    page: int = 0
    bbox: tuple[float, float, float, float] | None = None
    caption: str = ""
    source: str = "local"
    width: int = 0
    height: int = 0

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    @property
    def suffix(self) -> str:
        return MIME_EXT.get(self.mime, ".bin")

    def measured(self) -> ImageAsset:
        if self.width and self.height:
            return self
        try:
            from PIL import Image

            with Image.open(io.BytesIO(self.data)) as image:
                self.width, self.height = image.size
        except Exception:
            logger.debug("Could not measure image size", exc_info=True)
        return self

    def is_decorative(self) -> bool:
        if len(self.data) < MIN_IMAGE_BYTES:
            return True
        self.measured()
        if self.width and self.height and min(self.width, self.height) < MIN_IMAGE_EDGE:
            return True
        return False


def filter_decorative(assets: list[ImageAsset]) -> list[ImageAsset]:
    """Drop icons, bullets and page decorations before storage."""
    return [asset for asset in assets if not asset.is_decorative()]


def dedupe_assets(assets: list[ImageAsset]) -> list[ImageAsset]:
    seen: set[str] = set()
    unique: list[ImageAsset] = []
    for asset in assets:
        digest = asset.sha256
        if digest in seen:
            continue
        seen.add(digest)
        unique.append(asset)
    return unique


def extract_images_local(file_path: str, filename: str | None = None) -> list[ImageAsset]:
    """Fallback extraction for text PDFs and Office documents."""
    suffix = Path(filename or file_path).suffix.lower()
    try:
        if suffix == ".pdf":
            return _extract_pdf(file_path)
        if suffix in {".docx", ".docm", ".pptx", ".xlsx", ".xlsm"}:
            return _extract_office_media(file_path)
    except Exception:
        logger.warning("Local image extraction failed for %s", file_path, exc_info=True)
        return []
    return []


def _extract_pdf(file_path: str) -> list[ImageAsset]:
    import fitz

    assets: list[ImageAsset] = []
    document = fitz.open(file_path)
    try:
        for page_number, page in enumerate(document, start=1):
            for info in page.get_image_info(xrefs=True):
                xref = int(info.get("xref") or 0)
                if xref <= 0:
                    continue
                try:
                    base = document.extract_image(xref)
                except Exception:
                    continue
                data = base.get("image")
                if not data:
                    continue
                ext = f".{str(base.get('ext') or 'png').lower()}"
                bbox_values = info.get("bbox") or None
                assets.append(
                    ImageAsset(
                        data=data,
                        mime=EXT_MIME.get(ext, "image/png"),
                        page=page_number,
                        bbox=tuple(bbox_values) if bbox_values else None,
                        source="local",
                    )
                )
    finally:
        document.close()
    return assets


def _extract_office_media(file_path: str) -> list[ImageAsset]:
    assets: list[ImageAsset] = []
    with zipfile.ZipFile(file_path) as archive:
        for name in archive.namelist():
            if not name.startswith(IMAGE_MEDIA_PREFIXES):
                continue
            suffix = Path(name).suffix.lower()
            mime = EXT_MIME.get(suffix)
            if mime is None:
                continue
            assets.append(ImageAsset(data=archive.read(name), mime=mime, source="local"))
    return assets


def parse_mineru_zip(content: bytes) -> tuple[str, list[ImageAsset], list[dict]]:
    """Parse MinerU ZIP output into markdown, image assets and content_list items."""
    markdown = ""
    assets: list[ImageAsset] = []
    content_items: list[dict] = []
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = archive.namelist()
        markdown_names = sorted(
            (name for name in names if name.lower().endswith(".md")),
            key=lambda name: (name.count("/"), len(name)),
        )
        if markdown_names:
            markdown = archive.read(markdown_names[0]).decode("utf-8", errors="replace")
        content_names = [name for name in names if name.lower().endswith("content_list.json")]
        if content_names:
            try:
                parsed = json.loads(archive.read(content_names[0]).decode("utf-8", errors="replace"))
                if isinstance(parsed, list):
                    content_items = [item for item in parsed if isinstance(item, dict)]
            except Exception:
                logger.warning("Could not parse MinerU content_list.json", exc_info=True)
        metadata: dict[str, dict] = {}
        for item in content_items:
            image_path = item.get("img_path")
            if not image_path:
                continue
            caption = " ".join(str(part) for part in item.get("image_caption") or [])
            footnote = " ".join(str(part) for part in item.get("image_footnote") or [])
            metadata[Path(str(image_path)).name] = {
                "page": int(item.get("page_idx") or 0) + 1,
                "caption": (caption or footnote).strip(),
                "bbox": item.get("bbox"),
            }
        for name in names:
            if "/images/" not in name and not name.startswith("images/"):
                continue
            suffix = Path(name).suffix.lower()
            mime = EXT_MIME.get(suffix)
            if mime is None:
                continue
            info = metadata.get(Path(name).name, {})
            bbox_values = info.get("bbox")
            assets.append(
                ImageAsset(
                    data=archive.read(name),
                    mime=mime,
                    page=int(info.get("page") or 0),
                    caption=str(info.get("caption") or ""),
                    bbox=tuple(bbox_values) if bbox_values else None,
                    source="mineru",
                )
            )
    return markdown, assets, content_items