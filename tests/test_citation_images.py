import types

import pytest

from app.api.routers.chat import MAX_IMAGES_PER_CITATION, _attach_citation_images


class _Result:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self._items


class _PageSession:
    async def execute(self, statement):  # noqa: ARG002
        return _Result(
            [
                types.SimpleNamespace(id=f"img{i}", doc_id="d1", version_id="v1", caption="", page=3)
                for i in range(5)
            ]
        )


class _MixedSession:
    async def execute(self, statement):  # noqa: ARG002
        return _Result(
            [
                types.SimpleNamespace(id="imgA", doc_id="d1", version_id="v2", caption="", page=3),
                types.SimpleNamespace(id="imgB", doc_id="d1", version_id="v1", caption="", page=3),
            ]
        )


@pytest.mark.asyncio
async def test_attach_same_page_images_to_text_citation() -> None:
    citations = [
        {"chunk_id": "c1", "doc_id": "d1", "version_id": "v1", "page": 3, "image_id": None}
    ]
    await _attach_citation_images(_PageSession(), "t1", citations)
    assert len(citations[0]["images"]) == MAX_IMAGES_PER_CITATION
    assert citations[0]["images"][0]["url"] == "/api/v1/documents/d1/images/img0"


@pytest.mark.asyncio
async def test_same_page_images_are_limited_to_current_version() -> None:
    citations = [
        {"chunk_id": "c1", "doc_id": "d1", "version_id": "v1", "page": 3, "image_id": None}
    ]
    await _attach_citation_images(_MixedSession(), "t1", citations)
    assert [entry["image_id"] for entry in citations[0]["images"]] == ["imgB"]


import types

import pytest

from app.api.routers.chat import _attach_citation_images


class _HeadingSession:
    async def execute(self, statement):  # noqa: ARG002
        class _Result:
            def scalars(self):
                return [
                    types.SimpleNamespace(
                        id="imgH",
                        doc_id="d1",
                        version_id="v1",
                        caption="",
                        page=0,
                        heading_path="第三章 考勤管理",
                    )
                ]
        return _Result()


@pytest.mark.asyncio
async def test_attach_images_by_heading_for_pageless_formats() -> None:
    citations = [
        {
            "chunk_id": "c1",
            "doc_id": "d1",
            "version_id": "v1",
            "page": 0,
            "image_id": None,
            "heading_path": "第三章 考勤管理",
        }
    ]
    await _attach_citation_images(_HeadingSession(), "t1", citations)
    assert [entry["image_id"] for entry in citations[0]["images"]] == ["imgH"]