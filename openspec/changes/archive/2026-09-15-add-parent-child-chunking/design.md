## Context

见 proposal.md。现状：`ChunkDraft`/`ChunkRecord` 已有 `parent_id`、`heading_path`、`table_id`、`image_id`、`row_start/row_end`（部分未使用）；Milvus 已实现 dense + BM25 两路 RRF 融合与 rerank；`document_images` 已独立存储图片；表格目前以整张 Markdown 进切片。

## Goals / Non-Goals

**Goals:** 小块检索、大块生成；标题层级成为切分边界；表格行级可检索、整表可取回；统一 chunk schema；两路融合 + 元数据过滤。
**Non-Goals:** 第三路排名检索、VLM 图片语义、检索排序算法替换、跨文档聚合。

## Decisions

### D1 父子分块只作用于非表格内容

父块 = 标题子树；子树超上限时切二级父块（继承同一 `heading_path`）。子块在父块内递归打包语义块（段落/列表/条款/步骤），表格与图片作为原子块不跨块拆分。

### D2 表格：行级 + 表级摘要（不做父子）

行级 chunk：每个数据行生成"字段=值"语义文本，携带 `table_id`、`row_index`、表头字段名与章节；表级摘要 chunk：表名、列名、行数、单位与要点（第一版**确定性生成**，后续再评估模型摘要）。整表 JSON 存对象存储，可按 `table_id` 取回。

### D3 存储职责划分

| 位置 | 内容 |
|---|---|
| Milvus | child chunks、表格行级/摘要 chunks、图片描述 chunks |
| PostgreSQL | parent chunks（全文，按 id 取回）、表格资产元数据 |
| 对象存储（本地/MinIO） | `images/` 原图、`tables/` 整表 JSON |

### D4 统一 chunk schema

所有进 Milvus 的 chunk 共用字段：`id, text, title, doc_id, version_id, chunk_index, page, section, tenant_id, chunk_kind, chunk_type, doc_type, heading_path, parent_id, table_id, row_index, image_id, chunker_version, dense, sparse`。`chunk_kind ∈ {child, table_row, table_summary, image}`。

`doc_type` 与 `chunk_kind` 同为标量列，供 `expr` 元数据过滤使用（D5）。

### D5 检索：两路 RRF + 元数据过滤

dense 与 BM25 两路 `AnnSearchRequest` + `RRFRanker`，再经 reranker 精排；元数据（`doc_type`、部门、生效时间、`heading_path` 前缀、`table_id`、`image_id` 等）以 `expr` 过滤加在两路上。**不把元数据当作第三路排名**：过滤不产生相关性排名，混入 RRF 会把"符合条件"误当"相关"。

### D6 按文档类型参数化

参数表（代码默认 + `.env`/DB 可覆写）：parent 上限、child 上限、child 重叠、是否启用父子、表格行组大小、是否重复表头。默认：policy/sop 用条款/步骤为子块；faq 用问答对为子块；table/xlsx 不启用父子、走行级+摘要；generic 走标题子树 + 递归切分。

### D7 生成阶段父块展开

检索命中子块 → 按 `parent_id` 取父块文本（Postgres）→ 同一父块去重 → 按 token 预算截断 → 送 LLM。表格摘要与行级 chunk 不展开父块；图片 chunk 使用其描述文本。

### D8 引用保持子块精度

引用指向子块位置（页码/条款号/步骤号/表格行号），并携带可展示资产（图片/表格）；父块只用于生成。

## Risks / Trade-offs

- [父块过大] → token 上限 + 截断 + 同父块去重。
- [标题层级不可信] → 依赖转换细化先行，否则父块切歪。
- [表格行级 chunk 数量爆炸] → 行组切分 + 上限 + 只对数据行生成；跳过空行/汇总行可配置。
- [Milvus 与 Postgres 一致性] → 重导前清理旧父块/表格资产，写完再切换版本状态。

## Migration Plan

1. 建表与迁移；切片器升级 `structure-v2`；Milvus 统一 schema（必要时新集合版本）。
2. 重导：清理旧父块与表格资产 → 全量重导（复用解析缓存）。
3. 灰度：先对新上传文档生效，再重导历史语料。
4. 回滚：切片器回退 `structure-v1` 并使用旧集合。

## Open Questions

- 表级摘要是否需要模型生成（第一版确定性）。
- 表格行级 chunk 是否需要跳过小计/合计等非数据行。
