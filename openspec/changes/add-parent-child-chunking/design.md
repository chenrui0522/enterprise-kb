## Context

见 proposal.md。现状：`ChunkDraft`/`ChunkRecord` 已有 `parent_id` 与 `heading_path` 字段（未使用）；表格以 Markdown 文本切片并带 `table_id`/行号；图片已独立存储于 `document_images`；切片器版本为 `structure-v1`。

## Goals / Non-Goals

**Goals:** 父块承载完整上下文用于生成；子块保持检索精度；标题层级成为切分边界；表格可整表取回。
**Non-Goals:** 检索排序/重排策略调整、图片语义描述、跨文档父块。

## Decisions

### D1 父块 = 标题子树，超限再切二级父块

按 Markdown 标题层级构建父块（H1/H2/H3 递进）；当子树字符/token 超过上限时，在子树内按语义块再切二级父块，二级父块继承同一 `heading_path` 并带序号。

### D2 子块在父块内递归切分

父块内部递归打包语义块（段落/列表/条款/步骤），单项超限时按句界切分；表格与图片作为**原子块**不被跨块拆分；子块记录 `parent_id`。

### D3 父块与表格资产存 Postgres

新增 `chunk_parents`（id、tenant、doc_id、version_id、heading_path、page、text、token_estimate、chunker_version）与 `document_tables`（id、doc_id、version_id、sheet/section、header、rows JSON、markdown、page、heading_path）。父块不写入 Milvus，避免无意义向量与检索噪声。

### D4 生成端父块展开

检索命中子块后按 `parent_id` 取父块文本；同一父块去重；按 token 预算截断（保留开头与命中子块附近内容）；生成使用父块上下文，答案解析仍基于检索片段。

### D5 引用保持子块精度

引用继续使用子块的页码/条款号/步骤号/表格行号，并携带可展示资产（图片/表格）；父块仅用于生成，不作为引用来源。

### D6 小单元类型复用现有策略

FAQ 问答对、制度条款、SOP 步骤本身就是合格子块；其父块为所属章节/流程，避免父子策略与既有语义策略冲突。

## Risks / Trade-offs

- [父块过大导致 prompt 溢出] → token 上限 + 截断规则 + 同一父块去重。
- [标题层级不可信导致父块切歪] → 依赖转换细化（标题结构）先行；否则父块质量下降。
- [重导成本高] → 全量重导一次，配合解析缓存降低耗时。
- [引用与生成来源不一致] → 明确"引用=子块、生成=父块"，并在评测中同时看召回与答案质量。

## Migration Plan

1. 建表与迁移；切片器升级为 `structure-v2`。
2. 重导：先清理旧父块与表格资产，再做全量重导（复用解析缓存）。
3. 灰度：先对新上传文档生效，再重导历史语料。
4. 回滚：切片器版本回退到 `structure-v1` 并使用旧集合。

## Open Questions

- 父块 token 上限的最终取值（需按真实语料与模型上下文预算确定）。
- 二级父块是否需要在引用中体现（当前引用只用子块位置）。
