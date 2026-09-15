## Why

当前切片只有"小块"：检索命中后直接把子块文本送进生成，缺少上下文；长文本仍按字符硬切，标题层级没有被用作切分边界；表格以 Markdown 文本进切片，整表无法取回。用户需要"小块检索、大块生成"的父子策略，并以 Markdown 标题层级作为天然边界。

## What Changes

- **父块**：按 Markdown 标题层级切分（标题子树）；子树超过 token 上限时在子树内切二级父块。父块用于生成，不参与向量检索。
- **子块**：在父块内部递归切分（段落/列表/条款/步骤/表格行组/图片等原子块），用于检索；子块携带 `parent_id`。
- **表格独立存储**：新增表格资产（完整表格 + 表头 + 行数 + 页码 + 章节）；子块中保留可检索代表（表头 + 前若干行）与引用标记，整表可按 id 取回。图片沿用已有的 `document_images`。
- **生成端父块展开**：检索命中子块后按 `parent_id` 取父块文本，去重后按 token 预算截断送给 LLM。
- **引用保持子块精度**：引用仍指向页码/条款号/表格行号，不因使用父块而粗化。
- 非目标：检索排序算法调整、VLM 图片语义描述、跨文档聚合。

## Capabilities

### New Capabilities
- 无。

### Modified Capabilities
- `document-ingestion`: 切片由单层小块改为父子两层结构，并新增表格独立存储。
- `knowledge-qa`: 生成阶段使用父块上下文，引用仍保持子块精度。

## Impact

- 数据：新增 `chunk_parents`、`document_tables` 表与迁移；`document_versions` 记录 `chunker_version=structure-v2` 与父子统计。
- 切片：`app/ingestion/chunker.py`（父/子两级切分）、`app/ingestion/structure.py`（表格资产提取）。
- 存储：父块与表格资产落 Postgres；子块继续落 Milvus（已有 `parent_id` 字段）。
- 检索与生成：`app/retrieval/service.py`、`app/chat/graph.py`（父块展开、去重、token 预算）。
- 运维：全量重导现有语料；重导前清理旧父块与表格资产。
- 测试：父子切分、表格资产、父块展开与引用精度的单测与回归。
