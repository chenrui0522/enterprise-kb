from app.ingestion.chunker import ChunkContext, chunk_structure, detect_doc_type
from app.ingestion.structure import structure_from_markdown


def _context() -> ChunkContext:
    return ChunkContext(doc_id="d1", version_id="v1", tenant_id="t1", title="手册")


def test_router_falls_back_to_generic_and_numbers_chunks() -> None:
    structure = structure_from_markdown("# 标题\n\n这是一段普通说明文字，用于验证回退路径。")
    drafts = chunk_structure(structure, _context(), doc_type=None)
    assert drafts
    assert all(draft.chunker_version == "structure-v1:generic" for draft in drafts)
    assert [draft.chunk_index for draft in drafts] == list(range(len(drafts)))


def test_detect_and_split_faq_pairs() -> None:
    markdown = "Q: 如何报销？\nA: 在系统中提交申请。\n\nQ: 报销时限？\nA: 费用发生后三十天内。\n"
    structure = structure_from_markdown(markdown)
    assert detect_doc_type(structure) == "faq"
    drafts = chunk_structure(structure, _context())
    assert len(drafts) == 2
    assert all(draft.chunk_type == "faq" for draft in drafts)
    assert drafts[0].faq_id != drafts[1].faq_id
    assert "如何报销" in drafts[0].text
    assert "报销时限" in drafts[1].text


def test_faq_long_answer_keeps_one_faq_id() -> None:
    answer = "步骤内容详细说明。" * 40
    structure = structure_from_markdown(f"Q: 流程是什么？\nA: {answer}")
    drafts = chunk_structure(structure, _context(), doc_type="faq", chunk_size=200)
    assert len(drafts) > 1
    assert len({draft.faq_id for draft in drafts}) == 1
    assert all(draft.chunk_type == "faq" for draft in drafts)


def test_policy_clause_chunks_capture_numbers_and_heading_path() -> None:
    markdown = "## 差旅制度\n\n第一条 员工出差需提前审批。\n\n第二条 住宿标准按照职级执行。\n"
    drafts = chunk_structure(structure_from_markdown(markdown), _context(), doc_type="policy")
    assert [draft.clause_no for draft in drafts] == ["第一条", "第二条"]
    assert all(draft.chunk_type == "policy_clause" for draft in drafts)
    assert all("差旅制度" in draft.heading_path for draft in drafts)


def test_policy_type_detection_from_content() -> None:
    markdown = "第一条 员工出差需提前审批。\n\n第二条 住宿标准按照职级执行。\n"
    assert detect_doc_type(structure_from_markdown(markdown)) == "policy"


def test_sop_steps_keep_prerequisites_with_first_step() -> None:
    markdown = "# 采购流程\n\n前置条件：预算已批准。\n\n步骤 1 提交申请\n\n步骤 2 主管审批\n"
    drafts = chunk_structure(structure_from_markdown(markdown), _context(), doc_type="sop")
    assert [draft.step_no for draft in drafts] == ["1", "2"]
    assert all(draft.chunk_type == "sop_step" for draft in drafts)
    assert "前置条件" in drafts[0].text
    assert drafts[0].text.index("前置条件") < drafts[0].text.index("1. 提交申请")


def test_table_chunks_repeat_header_and_track_row_ranges() -> None:
    rows = "\n".join(f"| 项目{i} | {i} |" for i in range(1, 21))
    markdown = f"| 名称 | 数值 |\n|---|---|\n{rows}\n"
    drafts = chunk_structure(structure_from_markdown(markdown), _context(), doc_type="table", chunk_size=120)
    assert len(drafts) > 1
    assert len({draft.table_id for draft in drafts}) == 1
    assert all("| 名称 | 数值 |" in draft.text for draft in drafts)
    assert drafts[0].row_start == 1
    assert drafts[-1].row_end == 20
    assert drafts[0].row_end + 1 == drafts[1].row_start


def test_invalid_doc_type_detects_instead_of_failing() -> None:
    markdown = "# 标题\n\n普通段落内容，没有结构信号。\n"
    drafts = chunk_structure(structure_from_markdown(markdown), _context(), doc_type="unknown-type")
    assert drafts
    assert drafts[0].chunker_version == "structure-v1:generic"

def test_chunk_metadata_serializes_into_chunk_record() -> None:
    from app.ingestion.models import ChunkDraft
    from app.retrieval.chunk import ChunkRecord

    draft = ChunkDraft(
        text="第一条 员工出差需提前审批。",
        page=2,
        section="差旅制度",
        chunk_index=3,
        chunk_type="policy_clause",
        heading_path="差旅制度 > 审批",
        clause_no="第一条",
        parent_id="v1-clause-第一条",
        chunker_version="structure-v1:policy",
    )
    payload = draft.model_dump()
    assert payload["clause_no"] == "第一条"
    assert payload["chunker_version"] == "structure-v1:policy"

    record = ChunkRecord(
        id="v1-3",
        text=draft.text,
        doc_id="d1",
        version_id="v1",
        chunk_index=draft.chunk_index,
        page=draft.page,
        section=draft.section,
        tenant_id="t1",
        chunk_type=draft.chunk_type,
        heading_path=draft.heading_path,
        clause_no=draft.clause_no,
        parent_id=draft.parent_id,
        chunker_version=draft.chunker_version,
    )
    assert record.heading_path == "差旅制度 > 审批"
    assert record.model_dump()["clause_no"] == "第一条"