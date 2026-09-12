import pytest

from app.ingestion.doc_types import normalize_doc_type


def test_normalize_doc_type_accepts_known_values() -> None:
    assert normalize_doc_type(None) == "auto"
    assert normalize_doc_type("") == "auto"
    assert normalize_doc_type("auto") == "auto"
    assert normalize_doc_type("Policy") == "policy"
    assert normalize_doc_type(" table ") == "table"


def test_normalize_doc_type_rejects_unknown_values() -> None:
    with pytest.raises(ValueError):
        normalize_doc_type("white-paper")