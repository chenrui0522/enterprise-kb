from __future__ import annotations

import os
import shutil
import re
from pathlib import Path

from app.core.errors import AppError


class FileDocumentStorage:
    """Local-filesystem document storage behind a simple interface (S3 later)."""

    def __init__(self, root: str) -> None:
        self._root = Path(root)

    def store(self, doc_id: str, version_id: str, filename: str, data: bytes) -> str:
        safe_name = re.sub(r"[^\w.\-\u4e00-\u9fff]", "_", os.path.basename(filename))
        directory = self._root / doc_id / version_id
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / safe_name
        target.write_bytes(data)
        return str(target.relative_to(self._root))

    def store_image(self, doc_id: str, version_id: str, sha256: str, suffix: str, data: bytes) -> str:
        """Store one image content-addressed under the document version; returns its relative key."""
        relative = f"{doc_id}/{version_id}/images/{sha256}{suffix}"
        target = self._root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(data)
        return relative

    def delete_version_images(self, doc_id: str, version_id: str) -> None:
        directory = self._root / doc_id / version_id / "images"
        if directory.exists():
            shutil.rmtree(directory, ignore_errors=True)

    def resolve(self, storage_key: str) -> Path:
        path = (self._root / storage_key).resolve()
        if not str(path).startswith(str(self._root.resolve())):
            raise AppError("非法的存储路径")
        return path
