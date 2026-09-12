from __future__ import annotations

ALLOWED_DOC_TYPES = frozenset({"faq", "policy", "sop", "table", "generic"})


def normalize_doc_type(value: str | None) -> str:
    """Normalize an upload doc_type value; raises ValueError for unsupported values."""
    if value is None:
        return "auto"
    normalized = value.strip().lower()
    if not normalized:
        return "auto"
    if normalized == "auto":
        return "auto"
    if normalized not in ALLOWED_DOC_TYPES:
        allowed = " / ".join(sorted(ALLOWED_DOC_TYPES))
        raise ValueError(f"不支持的文档类型：{value}；可选值：auto / {allowed}")
    return normalized