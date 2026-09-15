## Why

当前切片只有"小块"：检索命中后直接把子块文本送进生成，缺少上下文；长文本仍按字符硬切，标题层级没有被用作切分边界；表格以整张 Markdown 进切片，检索与引用粒度都粗。用户需要"小块检索、大块生成"的父子策略，并要求表格单独按"行级语义化 + 表级摘要"处理、检索保持两路融合。

## What Changes

- **父子分块（非表格内容）**：父块按 Markdown 标题层级切分（标题子树），子树超过上限时在子树内切二级父块；子块在父块内递归切分，用于检索。
- **表格不参与父子**：表格改为两级——**行级语义化 chunk**（字段=值，带表名/表头/行号）与**表级摘要 chunk**（表名、列、行数、单位、要点）。
- **图片**：沿用现方案（原图 + caption/OCR 文本进切片），后续升级为 VLM 描述。
- **存储职责**：Milvus 只存 child chunks、表格行级/摘要 chunks、图片描述 chunks；父块存 PostgreSQL（按 id 取回）；原图与整表 JSON 存对象存储（本地/MinIO，`images/`、`tables/`）。
- **统一 chunk schema**：所有进 Milvus 的 chunk 使用同一字段集（含 `chunk_kind`、`parent_id`、`table_id`、`row_index`、`image_id`、`heading_path` 等）。
- **检索**：保持**两路召回（向量 + BM25）→ RRF 融合 → Rerank 重排**；元数据（doc_type/部门/时间/章节前缀等）作为过滤约束加在两路上，不作为第三路排名。
- **按文档类型参数化**：parent 上限、child 上限、是否启用父子、表格行组大小等参数按 `doc_type` 配置。
- 非目标：第三路排名检索、VLM 图片描述（后续 change）、检索排序算法替换。

## Capabilities

### New Capabilities
- 无。

### Modified Capabilities
- `document-ingestion`: 切片改为父子两层（表格除外），表格按行级 + 表级摘要处理，并支持按文档类型配置切块参数。
- `knowledge-qa`: 生成阶段使用父块上下文；检索保持两路 RRF 融合并把元数据作为过滤约束；引用保持子块精度。

## Impact

- 数据：新增 `chunk_parents`、`document_tables` 表与迁移；`document_versions` 记录切片器版本与统计。
- 存储：父块与表格元数据入 Postgres；原图与整表 JSON 入对象存储；Milvus 只存可检索的三类 chunk。
- 切片：`app/ingestion/chunker.py`（父子两级、表格行级/摘要）、`app/ingestion/structure.py`（表格资产）。
- 检索与生成：`app/retrieval/milvus_store.py`（统一 schema、元数据过滤）、`app/retrieval/service.py`、`app/chat/graph.py`（父块展开）。
- 运维：切片器版本升级 `structure-v2` 并全量重导。
- 测试：父子切分、表格行级/摘要、父块展开、过滤与引用精度。
