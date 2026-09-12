from app.ingestion.structure import (
    BLOCK_CODE,
    BLOCK_HEADING,
    BLOCK_LIST,
    BLOCK_PARAGRAPH,
    BLOCK_TABLE,
    degrade_to_paragraphs,
    markdown_table,
    structure_from_markdown,
    structure_to_markdown,
)


def test_structure_parses_headings_and_page_markers() -> None:
    markdown = "<!-- PAGE:1 -->\n\n# 保修政策\n\n正文内容。\n\n<!-- PAGE:2 -->\n\n## 退换货\n\n七天无理由。\n"
    structure = structure_from_markdown(markdown)
    headings = [block for block in structure.blocks if block.type == BLOCK_HEADING]
    assert [block.level for block in headings] == [1, 2]
    assert [block.text for block in headings] == ["保修政策", "退换货"]
    assert headings[1].page == 2


def test_structure_parses_tables_lists_and_code() -> None:
    markdown = (
        "# 制度\n\n"
        "| 指标 | 权重 |\n|---|---|\n| 完成率 | 40% |\n\n"
        "- 第一条\n- 第二条\n\n"
        "```python\nprint('x')\n```\n"
    )
    structure = structure_from_markdown(markdown)
    table = next(block for block in structure.blocks if block.type == BLOCK_TABLE)
    assert table.header == ["指标", "权重"]
    assert table.rows == [["完成率", "40%"]]
    assert any(block.type == BLOCK_LIST and block.items == ["第一条", "第二条"] for block in structure.blocks)
    assert any(block.type == BLOCK_CODE for block in structure.blocks)


def test_structure_round_trip_keeps_page_markers_and_table() -> None:
    markdown = "<!-- PAGE:3 -->\n\n# 标题\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"
    structure = structure_from_markdown(markdown)
    rendered = structure_to_markdown(structure)
    assert "<!-- PAGE:3 -->" in rendered
    assert "# 标题" in rendered
    assert "| A | B |" in rendered


def test_degrade_to_paragraphs_marks_degraded() -> None:
    structure = structure_from_markdown("# 标题\n\n| A | B |\n|---|---|\n| 1 | 2 |\n")
    degraded = degrade_to_paragraphs(structure)
    assert degraded.degraded is True
    assert all(block.type == BLOCK_PARAGRAPH for block in degraded.blocks)
    assert any("| A | B |" in block.text for block in degraded.blocks)


def test_markdown_table_pads_short_rows() -> None:
    rendered = markdown_table(["A", "B", "C"], [["1", "2"]])
    assert rendered.splitlines()[-1] == "| 1 | 2 |  |"
