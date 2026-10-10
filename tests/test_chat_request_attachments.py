"""ChatRequest effective attachment id resolution."""

from __future__ import annotations

from app.schemas.chat import ChatRequest


def test_effective_ids_from_singular() -> None:
    req = ChatRequest(message="hi", attachment_id="abc123")
    assert req.effective_attachment_ids() == ["abc123"]


def test_effective_ids_prefer_list() -> None:
    req = ChatRequest(
        message="hi",
        attachment_id="old",
        attachment_ids=["a1", "a2", "a3"],
    )
    assert req.effective_attachment_ids() == ["a1", "a2", "a3"]


def test_effective_ids_cap_at_eight() -> None:
    ids = [f"id{i}" for i in range(12)]
    req = ChatRequest(message="hi", attachment_ids=ids[:8])
    assert len(req.effective_attachment_ids()) == 8


def test_effective_ids_empty() -> None:
    req = ChatRequest(message="hi")
    assert req.effective_attachment_ids() == []
