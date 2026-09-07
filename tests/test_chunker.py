from app.ingestion.chunker import ChunkContext, chunk_pages
from app.ingestion.models import ParsedPage


def test_chunker_keeps_metadata_and_page_number() -> None:
    pages = [ParsedPage(page_number=3, text="第一章 保修政策\n\n打印机保修期为十二个月。\n\n编号 ZB-100 享受延保。")]
    context = ChunkContext(doc_id="doc1", version_id="v1", tenant_id="t1", title="产品手册")
    drafts = chunk_pages(pages, context, chunk_size=200, overlap=20)
    assert drafts
    for draft in drafts:
        assert draft.page == 3
        assert draft.section in {"第一章 保修政策", "前言"}
        assert "doc1" not in draft.text


def test_chunker_splits_long_page_with_overlap() -> None:
    long_text = "维修步骤：" + ("步骤内容详细说明。" * 300)
    pages = [ParsedPage(page_number=1, text=long_text)]
    context = ChunkContext(doc_id="doc1", version_id="v1", tenant_id="t1", title="手册")
    drafts = chunk_pages(pages, context, chunk_size=300, overlap=50)
    assert len(drafts) > 1
    assert all(len(item.text) <= 310 for item in drafts)


def test_chunker_merges_tiny_paragraphs_on_same_page() -> None:
    pages = [ParsedPage(page_number=1, text="第一点。\n\n第二点。\n\n第三点。")]
    context = ChunkContext(doc_id="doc1", version_id="v1", tenant_id="t1", title="制度文档")
    drafts = chunk_pages(pages, context, chunk_size=500, overlap=20)
    assert len(drafts) == 1
    assert "第一点。" in drafts[0].text and "第三点。" in drafts[0].text
