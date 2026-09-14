import io
import os
import zipfile
from pathlib import Path

import fitz
from PIL import Image

from app.ingestion.chunker import ChunkContext, chunk_structure
from app.ingestion.images import (
    ImageAsset,
    dedupe_assets,
    extract_images_local,
    filter_decorative,
    parse_mineru_zip,
)
from app.ingestion.structure import structure_from_markdown


def _png(size: tuple[int, int], color: str | None = None) -> bytes:
    buffer = io.BytesIO()
    if color:
        image = Image.new("RGB", size, color)
    else:
        image = Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3))
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_filter_decorative_drops_small_and_keeps_large() -> None:
    small = ImageAsset(data=_png((16, 16), "white"))
    large = ImageAsset(data=_png((200, 200)))
    kept = filter_decorative([small, large])
    assert large in kept
    assert small not in kept


def test_dedupe_assets_by_content_hash() -> None:
    data = _png((120, 120))
    first = ImageAsset(data=data, page=1)
    second = ImageAsset(data=data, page=3)
    unique = dedupe_assets([first, second])
    assert len(unique) == 1


def test_extract_images_local_from_pdf(tmp_path) -> None:
    image_path = tmp_path / "figure.png"
    image_path.write_bytes(_png((180, 180)))
    pdf_path = tmp_path / "with_image.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "架构说明", fontsize=12)
    page.insert_image(fitz.Rect(72, 100, 372, 400), filename=str(image_path))
    document.save(str(pdf_path))
    document.close()

    assets = extract_images_local(str(pdf_path), "with_image.pdf")
    assert assets
    assert all(asset.page == 1 for asset in assets)


def test_parse_mineru_zip_extracts_images_and_caption() -> None:
    image_bytes = _png((160, 160))
    content_list = [
        {
            "type": "image",
            "img_path": "images/abc.jpg",
            "image_caption": ["系统架构图"],
            "image_footnote": [],
            "bbox": [1, 2, 3, 4],
            "page_idx": 2,
        }
    ]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("doc/auto/doc.md", "# 标题\n\n![](images/abc.jpg)\n")
        archive.writestr("doc/auto/images/abc.jpg", image_bytes)
        archive.writestr("doc/auto/doc_content_list.json", __import__("json").dumps(content_list))

    markdown, assets, items = parse_mineru_zip(buffer.getvalue())
    assert "# 标题" in markdown
    assert len(assets) == 1
    assert assets[0].caption == "系统架构图"
    assert assets[0].page == 3
    assert items and items[0]["type"] == "image"


def test_structure_and_chunker_emit_image_chunk() -> None:
    structure = structure_from_markdown("![架构图](images/a.jpg)\n\n正文内容")
    assert any(block.type == "image" for block in structure.blocks)
    drafts = chunk_structure(
        structure,
        ChunkContext(doc_id="d1", version_id="v1", tenant_id="t1", title="手册"),
    )
    image_drafts = [draft for draft in drafts if draft.chunk_type == "image"]
    assert len(image_drafts) == 1
    assert image_drafts[0].image_id == ""
    assert image_drafts[0].text == "架构图"

def test_storage_delete_version_images(tmp_path) -> None:
    from app.ingestion.storage import FileDocumentStorage

    storage = FileDocumentStorage(str(tmp_path))
    key = storage.store_image("d1", "v1", "a" * 64, ".png", b"image-bytes")
    assert (tmp_path / key).exists()
    storage.delete_version_images("d1", "v1")
    assert not (tmp_path / "d1" / "v1" / "images").exists()


def test_chunk_record_carries_image_id() -> None:
    from app.retrieval.chunk import ChunkRecord

    record = ChunkRecord(
        id="c1", text="图片（第1页）", doc_id="d", version_id="v", chunk_index=0, page=1,
        tenant_id="t1", image_id="img-1",
    )
    assert record.image_id == "img-1"

def test_parse_mineru_zip_tracks_heading_for_images() -> None:
    import json

    content_list = [
        {"type": "text", "text": "第三章 考勤管理", "text_level": 2, "page_idx": 0},
        {"type": "image", "img_path": "images/head.jpg", "image_caption": [], "page_idx": 0},
    ]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("doc/auto/doc.md", "# 标题\n")
        archive.writestr("doc/auto/images/head.jpg", _png((160, 160)))
        archive.writestr("doc/auto/doc_content_list.json", json.dumps(content_list))

    _, assets, _ = parse_mineru_zip(buffer.getvalue())
    assert assets and assets[0].heading_path == "第三章 考勤管理"