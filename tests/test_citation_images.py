import types

import pytest

from app.api.routers.chat import _load_citation_images


class _ScalarResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self._items


class _FakeSession:
    async def execute(self, statement):  # noqa: ARG002
        return _ScalarResult([types.SimpleNamespace(id="img1", doc_id="d1", caption="架构图", page=2)])


@pytest.mark.asyncio
async def test_load_citation_images_builds_display_payload() -> None:
    mapping = await _load_citation_images(_FakeSession(), "t1", ["img1", None, ""])
    assert "img1" in mapping
    assert mapping["img1"][0]["url"] == "/api/v1/documents/d1/images/img1"
    assert mapping["img1"][0]["caption"] == "架构图"


@pytest.mark.asyncio
async def test_load_citation_images_without_ids() -> None:
    assert await _load_citation_images(_FakeSession(), "t1", [None, ""]) == {}