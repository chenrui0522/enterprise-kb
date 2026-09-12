## Why

当前入库链路把所有格式归一成 Markdown 后，用一套固定的 800 字符窗口切片，既无法表达
FAQ 的问答对、制度条款、SOP 步骤和表格行这些天然语义单元，转换阶段还会丢失标题层级、
表格位置等结构信息。公司知识库要入库大量制度、SOP、FAQ 与含表格文档，现有切片会造成
答案缺上下文、步骤被截断、表格串行和引用粒度粗糙；同时系统没有全量重导入口，切片策略
升级后无法安全重建索引。

## What Changes

- 在转换与切片之间引入统一文档结构表示（block：标题 / 段落 / 列表 / 表格 / 代码，带层级、
  页码、行号），由各转换器产出结构而不是直接产出扁平 Markdown。
- 新增按文档类型的切片策略路由：FAQ 问答对、制度条款、SOP 步骤、表格行组各自独立成块，
  无法识别类型时回退到现有通用切片器。
- Chunk 元数据扩展：`chunk_type`、`heading_path`、`clause_no`、`step_no`、`faq_id`、
  `table_id`、行号范围、`parent_id`、`chunker_version`；Milvus 集合 schema 同步扩展。
- 上传接口支持可选 `doc_type`（faq / policy / sop / table / generic），未提供时按内容
  启发式判断，保证向后兼容。
- **BREAKING**：切换到新集合 `kb_chunks_v2`（通过配置指定），旧集合 `kb_chunks` 保留用于
  回滚；已入库文档需要全量重导，重导后 `chunk_index` 与切片边界变化，历史引用可能失配。
- 新增全量重导能力：扫描 Postgres 中的文档版本与本机原文存储，按新策略重新入队、重新切片、
  写入新集合并记录 `chunker_version`。
- 非目标（后续变更）：PDF 图纸 / 视觉解析、parent-child 两级检索（本期仅预留 `parent_id`）、
  中文 BM25 analyzer 调优。

## Capabilities

### New Capabilities
- `corpus-reindexing`: 面向已入库语料的全量重导与集合切换能力，包括重导任务生成、执行、
  状态核对与回滚边界。

### Modified Capabilities
- `document-ingestion`: 从"定长窗口切片"变更为"结构抽取 + 按文档类型感知切片"，并让每个
  切片携带可定位到条款 / 步骤 / 问答对 / 表格行的元数据。

## Impact

- 转换层：`app/ingestion/converters.py`（Word 标题样式、PDF 标题与表格位置、表格保真）。
- 切片层：`app/ingestion/chunker.py`、`app/ingestion/models.py`、`app/ingestion/pipeline.py`。
- 检索层：`app/retrieval/chunk.py`、`app/retrieval/milvus_store.py`（新字段与新集合）。
- 接口层：`app/api/routers/documents.py` 新增可选 `doc_type` 参数；前端可选同步。
- 运维：新增全量重导脚本 / 任务入口；`.env` 与 `.env.example` 增加集合名与切片器版本配置。
- 数据：Milvus 新增 `kb_chunks_v2` 集合，Postgres 表结构需要新增 `chunker_version` 等字段。
- 测试：转换器结构抽取、各类型切片器、重导流程与 Milvus schema 的单元/集成测试。
