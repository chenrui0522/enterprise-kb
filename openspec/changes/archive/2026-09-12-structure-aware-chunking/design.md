## Context

动机见 proposal.md。当前链路的既定事实决定了方案边界：

- 转换器直接产出扁平 Markdown：PDF 用 PyMuPDF 提平文本、pdfplumber 表格追加到页尾；Word 只识别
  `Heading N` / `Title` 样式；Office/CSV 走 MarkItDown。表格相对位置与中文标题样式会丢。
- 切片只有 `chunk_markdown` 一种实现（800 字符窗口、超长块内 80 字符重叠），`chunk_pages` 仅被测试引用。
- Milvus 集合 `kb_chunks` 字段固定且 `enable_dynamic_field=False`，`ensure_collection()` 对已存在集合直接跳过，
  因此新增字段必须落到新集合；`text` 与 `ChunkRecord` 上限均为 4096。
- worker 只消费 Redis 队列中的新上传任务，没有扫描已入库文档重新入队的入口。
- 本地已有一份 38.7MB PDF 已入库，Milvus 旧集合需要保留用于回滚。

## Goals / Non-Goals

**Goals:**
- 让 FAQ / 制度 / SOP / 表格四类内容按语义单元切片，并携带可定位到条款 / 步骤 / 问答 / 表格行的元数据。
- 在不删除旧集合的前提下完成集合切换与全量重导，重导可中断续跑、可核对、可回滚。
- 保持现有检索与问答链路可用（dense + BM25 混合检索、现有 API 路径不变）。

**Non-Goals:**
- 本期不做 parent-child 两级检索，仅在 schema 中预留 `parent_id`。
- 本期不做 PDF 图纸 / 视觉解析与 MinerU 全面替代，复杂版式仍走现有降级路径。
- 本期不做中文 BM25 analyzer 调优与 FAQ 独立问题字段检索，留作后续变更。

## Decisions

### D1 在转换与切片之间引入文档结构中间表示

新增 `DocumentStructure`，由块列表构成，每块含 `type`（heading/paragraph/list/table/code）、`level`、
`text`、`page`、行号范围与表格行列数据；转换器负责产出该结构，切片器只消费该结构。

替代方案：继续用 Markdown 文本 + 正则回溯标题与表格。放弃原因是 PDF 表格位置、合并单元格与
中文 Word 标题样式无法从扁平 Markdown 恢复；引入第三方文档解析库则增加重依赖，且对中文制度/
SOP 的版式支持不明确。

### D2 文档类型显式声明优先，启发式兜底

上传接口新增可选 `doc_type`（faq/policy/sop/table/generic），落在 `document_versions` 上，
由入库任务携带；未提供时先在结构上做轻量启发式判断（编号步骤、问答标记、条款编号、表格占比），
仍无法判断则使用 `generic`。

替代方案：完全自动识别。放弃原因是企业文档命名与排版差异大，显式类型准确率更高，且允许后续
人工纠正；同时保留兜底以满足"不阻塞入库"的要求。

### D3 按类型实现独立切片器，通用切片器保留为回退

- `faq`：按问答对成块，禁止跨问答对合并；答案过长时在同一 `faq_id` 下拆子块。
- `policy`：按条/款成块，记录 `clause_no` 与完整 `heading_path`；超长条款按句界拆子块并沿用条款号。
- `sop`：按步骤成块，记录 `step_no`；前置条件与步骤同块，步骤内部不拆分。
- `table`：按表格成块；超容量时按行组拆分并重复表头，记录 `table_id` 与行号范围。
- 未识别类型：回退现有 `chunk_markdown` 行为，保证向后兼容。

替代方案：单一"结构化 + 固定窗口"切片器。放弃原因是四类内容的自然边界不同，统一窗口会重新
引入本次要解决的问题。

### D4 新集合 schema 采用平铺新字段，字段命名保持既有约定

新集合 `kb_chunks_v2` 字段：

```
id, text(4096), title, doc_id, version_id, chunk_index, page, section, tenant_id,
chunk_type, heading_path, clause_no, step_no, faq_id, table_id, row_start, row_end,
parent_id, chunker_version, dense(FLOAT_VECTOR), sparse(SPARSE, BM25(text))
```

保留既有字段名与检索 `output_fields`，只新增字段，减少检索层改动。`heading_path` 用 ` > ` 连接，
无标题时回退文档标题；`page` 对无分页格式为 0，沿用现有语义。

替代方案：开启动态字段。放弃原因是无法建索引与 BM25 函数约束，检索过滤不可靠。

### D5 集合切换通过配置，旧集合只读保留

`KB_MILVUS_COLLECTION` 指向新集合，`ensure_collection()` 按新 schema 创建；旧集合不删、不改。
回滚即把配置改回 `kb_chunks`。删除旧集合是独立的显式操作，不包含在重导流程中。

替代方案：集合别名（alias）切换。放弃原因是当前代码直接按名字操作集合，引入别名需要额外状态管理，
收益不足以抵消复杂度。

### D6 全量重导复用入库队列，并新增切片器版本记录

新增重导入口（CLI 脚本调用应用层，不直接写 Milvus）：

1. 扫描 `document_versions` 关联 `documents`，得到 `doc_id / version_id / storage_key / doc_type`；
2. 校验原文是否存在，缺失记 `skipped` 并给出原因；
3. 生成入库任务投递到现有队列，任务体带 `chunker_version`；
4. worker 复用 `IngestionPipeline`：结构抽取 → 类型切片 → 向量化 → 写入当前集合；
5. 单文档失败只标记该版本，继续处理其余文档；结束输出成功/失败/跳过摘要。

重导幂等：写入前先按 `version_id` 删除当前集合中该版本的切片，再插入本次结果，避免新旧切片残留。
`document_versions` 新增 `chunker_version` 与 `doc_type` 字段（Alembic 迁移）。

替代方案：进程内同步重导。放弃原因是 38.7MB 文档的 CPU embedding 耗时长，同步执行无法观测进度，
也容易与 API 争用资源。

### D7 转换层按"尽量保结构、失败可降级"改造

- Word：标题识别同时匹配 `Heading N` 与本地化标题样式；表格按文档顺序产出，合并单元格展开规则固定。
- PDF：用 PyMuPDF 的块/字体信息推断标题层级；表格按其页面位置插入正文顺序，避免与正文重复；
  复杂版式仍可回退到 MinerU（已支持）。
- Markdown/Office：沿用现有解析，补充列表与表格块类型标注。

替代方案：全部 PDF 走 MinerU。放弃原因是 CPU 成本与耗时不可接受，且并非所有 PDF 都需要 OCR。

## Risks / Trade-offs

- [结构抽取对复杂版式不稳定] → 保留 `generic` 降级路径并把降级情况记录到文档版本，便于抽查。
- [表格识别误判导致内容错位] → 用真实制度/SOP 样本建立回归用例，表格切片强制携带表头与行号。
- [重导耗时长、占用 CPU] → 复用队列可观测进度，支持中断后续跑；单文档失败不影响整体。
- [新切片改变 chunk_index，历史引用失配] → 本期语料处于早期，接受重建后旧引用失效；schema 预留
  `parent_id`，后续可做引用重映射。
- [双模型常驻内存压力] → 重导期间避免同时进行大量在线问答；必要时分批重导。

## Migration Plan

1. 实现结构表示、类型切片器、schema v2、重导脚本与 DB 迁移，补齐单元/集成测试。
2. 启动 Docker Desktop 与 compose 服务，确认 bge-m3 与 bge-reranker-v2-m3 以
   `model_engine=sentence_transformers` 在线。
3. 将 `KB_MILVUS_COLLECTION` 改为 `kb_chunks_v2`（旧集合 `kb_chunks` 不动）。
4. 先执行重导 dry-run 核对文档清单与原文存在性，再执行全量重导。
5. 校验新集合切片数量与抽样检索/引用，确认后再决定是否删除旧集合。

回滚：把 `KB_MILVUS_COLLECTION` 改回 `kb_chunks` 并重启 API/worker 即可恢复旧索引。

## Open Questions

- FAQ 独立问题字段的 BM25 权重何时引入（依赖后续检索评测结果）。
- 中文 analyzer 从 `standard` 切换到更适合中文的分析器的最佳时机。
- PDF 图纸的视觉解析方案（MinerU VLM / 其他）在二期如何接入。
