## 1. 引用与图片关联

- [x] 1.1 引用对象携带 `version_id` 与 `heading_path`，验证检索结果可传递版本与章节
- [x] 1.2 同页挂图（上限 3 张、版本限定），验证单测通过
- [x] 1.3 `document_images.heading_path` 字段与迁移 0006，验证 `uv run alembic upgrade head` 成功
- [x] 1.4 MinerU content_list 章节跟踪，验证图片获得所属章节
- [x] 1.5 含内嵌媒体的 Office 文档优先经 MinerU 解析，验证 Word/PPT 图片可获章节归属
- [x] 1.6 按章节回退挂图，验证无分页格式的引用能返回章节图片
- [x] 1.7 全量测试 `uv run pytest -q` 通过（73 passed）
- [x] 1.8 真实检索验证：第 11 页文字引用关联到 3 张同页图片
