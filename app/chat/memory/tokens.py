"""Approximate token counting for CJK-heavy chat (aligned with parent_token_budget)."""

from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Heuristic: ~2 characters per token for Chinese-heavy corpora."""
    if not text:
        return 0
    return max(1, len(text) // 2)


def truncate_to_token_cap(text: str, token_cap: int) -> tuple[str, bool]:
    """Truncate text so estimate_tokens(result) <= token_cap. Returns (text, capped)."""
    if token_cap <= 0:
        return "", True
    if estimate_tokens(text) <= token_cap:
        return text, False
    # chars ≈ tokens * 2
    limit = max(1, token_cap * 2)
    clipped = text[:limit].rstrip()
    if len(clipped) < len(text):
        clipped = clipped + "…"
    return clipped, True
