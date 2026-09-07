import pytest

from app.core.errors import AppError
from app.ingestion.storage import FileDocumentStorage


def test_storage_roundtrip(tmp_path) -> None:
    storage = FileDocumentStorage(str(tmp_path))
    key = storage.store("doc1", "v1", "产品手册.pdf", b"%PDF-...")
    assert storage.resolve(key).exists()


def test_storage_rejects_path_traversal(tmp_path) -> None:
    storage = FileDocumentStorage(str(tmp_path))
    with pytest.raises(AppError):
        storage.resolve("../../outside.pdf")
