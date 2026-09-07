## Context

全新项目，仓库尚无代码与既有规格（见 proposal.md - Why）。约束条件：

- 单人开发，需要清晰的模块边界，便于后续二次开发与渐进演进。
- 生成层使用 DeepSeek `deepseek-v4-flash`（外部 API，OpenAI 兼容）；向量与重排必须本地化，文档全文不出内网。
- 本地模型先 CPU 运行，后续升级 GPU；重排并发上限 10。
- 初期语料约 1000 页文字/表格型 PDF，未来会扩展到扫描件与复杂表格彩页手册。
- 目标本地 Docker Compose 部署、约 50 并发；多租户、审计、反馈、文档权限本期只预埋结构，不实现业务。

## Goals / Non-Goals

**Goals:**

- 交付可用的 MVP：PDF 异步入库、知识问答、多轮对话，全部带可追溯引用。
- 明确分层（API / 对话编排 / 检索 / 接入 / 存储），让 ingestion、retrieval、chat 可独立演进。
- 将模型（LLM / embedding / reranker）与解析器抽象成可替换接口，CPU→GPU、文字 PDF→OCR 只换实现不换上层。
- 预埋 `tenant_id`、审计、反馈的数据位，为后续企业级能力铺路。
- 面向 50 并发与 SSE 流式输出的运行结构。

**Non-Goals:**

- 本期不实现多租户隔离策略、RBAC/文档权限、审计日志消费、答案反馈闭环的业务逻辑（仅预留表结构与事件位点）。
- 本期不做扫描件 OCR 与复杂版面分析（解析器预留扩展点）。
- 本期不做多机集群、K8s 编排与高可用。
- 本期不做模型评测平台与运营后台。

## Decisions

### D1：模块化单体仓库

```
app/
  api/         路由：chat、documents、conversations、feedback、health
  chat/        LangGraph 图、状态、节点、prompt、流式输出
  retrieval/   Milvus 客户端、混合检索、重排、查询改写、缓存
  ingestion/   转换器(converters，PDF/DOCX/MarkItDown) + Markdown 感知切片 + embedding + 入库编排
  core/        配置、DB 会话、租户上下文、鉴权占位（本地账号，SSO 后置）、公共类型
  audit/       审计事件模型与写入占位
  models/      SQLAlchemy 模型
  schemas/     Pydantic 请求/响应
  worker/      任务队列消费端（解析→切片→向量化→入库）
frontend/      聊天 UI（Vite + React；SSE 流式、引用展示、反馈占位）
docker-compose.yml / .env
```

理由：单人开发阶段避免微服务开销；模块按边界收敛，未来可把 `worker`、`retrieval`、`model-service` 拆为独立服务。备选方案「单体无分层」不利于二次开发，未采纳。

### D2：LangGraph 只编排「对话」，不包揽接入

对话侧用 LangGraph `StateGraph` 表达确定性的状态流：

```
rewrite(结合历史改写)
   │
   ▼
need_retrieval?(判定)
   │ yes                     │ no
   ▼                         ▼
hybrid_retrieve          direct_answer
   │
   ▼
rerank(取 top-N)
   │
   ▼
generate(带引用、流式) → 校验引用 → 结束
```

每个节点是纯函数，状态用 Pydantic 建模；会话持久化使用 PostgreSQL checkpointer，`thread_id = conversation_id`。备选方案「直接按请求写 pipeline 胶水代码」也能跑，但会失去可观测的中间状态与可恢复性；LangChain 高层 agent 循环（工具循环）不适合本场景的确定性 RAG 流程。

### D3：模型接入全部接口化，配置驱动

- `LLMProvider`：默认 DeepSeek `deepseek-v4-flash`，走 OpenAI 兼容协议（`base_url=https://api.deepseek.com`），`deepseek-reasoner` 类模型可通过配置切换。提示词注入改写/判定/生成三个角色模板，生成阶段强制引用格式。
- `Embedder` / `Reranker`：默认指向本地模型服务（Xinference，同时托管 bge-m3 与 bge-reranker-v2-m3，提供 OpenAI 兼容 embedding/rerank 接口）；通过 `.env` 切换设备（`cpu` → `cuda`），GPU 升级时仅改容器资源配置与模型设备参数。
- 检索层对 reranker 使用信号量限流，最大并发 10；CPU 阶段启用 `int8` 量化选项。

备选方案：embedding 直接用 HuggingFace `sentence-transformers` 进程内加载。优点是少一个服务；缺点是 CPU 推理占用 API 进程、GPU 升级与横向扩展时绑定死，未采纳。

### D4：Milvus 承担向量 + 关键词混合检索

- 集合字段：`id`、`vector`、`text`、`doc_id`、`chunk_index`、`page`、`section`、`tenant_id`、`version_id`。
- 检索采用向量召回 + BM25（全文）加权融合，先召回 top-N（默认 20），再经 reranker 精排取 top-K（默认 3）；两者为初始默认值，做成配置项，待真实语料评估后调优。
- 按 `tenant_id` 过滤（或 partition key）实现租户级隔离，检索层强制携带租户过滤条件。
- 查询结果按「改写后的问题 + 租户 + 语义指纹」在 Redis 做短时缓存。

理由：纯向量对中文专有名词、编号、缩写召回不稳，必须与关键词互补（对应 knowledge-qa 的编号检索需求）。

### D5：PostgreSQL 数据模型（业务元数据，正文不进 PG）

核心表（全部含 `tenant_id`）：

- `documents`：文档元数据与状态机（`pending → parsing → chunking → embedding → indexing → ready | failed`），含 `current_version_id`。
- `document_versions`：每次上传/更新产生新版本；入库成功后原子切换 `current_version_id`，旧版本切片从 Milvus 删除。
- `conversations`、`messages`：会话与消息；消息记录角色、内容、改写后的检索问句、耗时等。
- `message_citations`：消息 ↔ 文档/页码/chunk 的引用关系（反馈闭环与审计的基础）。
- `audit_events`：本期只落模型与写入接口，业务消费后续实现。
- `feedback_responses`：预置消息级评价字段（好评/差评/备注），绑定 `message_id`，业务逻辑后续实现。

Redis 用途：任务队列、SSE/接口限流、改写查询与检索结果缓存、短期会话热状态。

### D6：异步接入流水线

上传 → 保存原文（本期本地卷，通过存储接口抽象，后续可换 MinIO/S3）→ 写入 `documents` → 投递 Redis 任务队列 → worker 消费：

解析（parser 接口 + PyMuPDF/pdfplumber 文字与表格提取）→ 按标题/章节/页码切片（含重叠窗口）→ embedder 向量化 → 写入 Milvus → 更新文档状态。

- parser 接口返回统一的结构化页面/块模型，未来扫描件 OCR（如 MinerU）实现同一接口，替换后旧文档重新入队即可。
- chunk 元数据强制包含 `doc_id + version_id + page`，保证引用可定位到页。

### D8：统一“先转 Markdown”的接入范式
补充（本期已实现）：支持 .pptx/.xlsx/.html/.htm/.csv/.json 输入，统一经 MarkItDown 转换为 Markdown 后进入同一 chunk_markdown 链路；上传 API、前端选择器与文档校验同步开放对应扩展名，Office 压缩包以 PK\x03\x04 文件头校验。

所有支持格式先经转换层归一为 Markdown，再由 Markdown 感知切片器处理：

```
上传 → 格式识别 → 转换器
   PDF    → PDFMarkdownConverter（保留 <!-- PAGE:N --> 页码标记，表格转 pipe table）
   .docx  → DocxMarkdownConverter（标题→# 层级，表格按文档顺序保留）
   .md/.txt → TextMarkdownConverter（原样/清洗后进入）
   → chunk_markdown（标题=章节、表格/代码块整体保留、长块切窗）
   → bge-m3 → Milvus
```

理由：下游只面对一种表示，切片/检索/引用逻辑不再为每种格式写分支。PDF 是唯一保留分页的格式；Word/Markdown 等无分页格式通过 `page=0 + section=章节标题` 提供定位，前端据此只展示页数或章节。替代方案“各格式分别切片”会让引用与切片策略分叉，未采纳。

### D7：SSE 流式与 50 并发

- 问答接口用 SSE（`text/event-stream`）输出 token 增量与结束事件；LangGraph 以 `astream` 事件驱动推送。
- API 无状态、可水平扩容；单机先用 Uvicorn 多 worker + Redis 限流；DeepSeek 与本地模型调用均带超时、重试与熔断占位。
- 50 并发按「在线会话数」估算，检索/生成峰值取决于活跃提问比例；重排并发上限 10 是受控瓶颈，配合结果缓存与 top-N 截断避免排队放大。
- 可观测性：本期使用结构化日志，不接入 LangSmith/自建 trace；在模型 provider 调用与图节点执行处预留 trace 埋点，后续接入不改变接口。

### D9：扫描件/复杂彩页 OCR 通过 MinerU 异步编排（本期实现）

OCR 能力不打包进 API/worker 镜像，而是作为可选的 HTTP 统一解析服务附加：

```
上传(图片 | 扫描PDF | ocr=true 的复杂彩页手册)
  -> 摄取流水线 _plan_converters 路由
       auto+PDF  -> PDFMarkdownConverter(文字/表格)  --无任何可提取内容--> MinerUConverter
       图片/强制OCR -> MinerUConverter (HTTP /tasks 异步提交 -> 轮询状态 -> 取结果 Markdown)
  -> 统一 Markdown 切片 -> bge-m3 向量化 -> Milvus
```

- 路由决策写入 `document_versions.parse_mode`（auto | ocr），重试保持原解析方式；迁移 0002 增加该列。
- MinerU 服务仅需提供 `/health`、`/tasks`、`/tasks/{id}`、`/tasks/{id}/result`；客户端兼容 3.x results 结构与 2.x batch_result_list 结构。
- MinerU 输出的 Markdown 不保证带页码标记，OCR 文档以章节标题定位引用；CPU 期使用 `backend=pipeline`（OCR 模型可在 CPU 推理），GPU 升级后仅改配置切换 VLM/hybrid 后端。
- 服务部署作为 compose 可选 `mineru` profile + `docker/mineru/Dockerfile.cpu`，首次解析从 ModelScope 拉取权重（数 GB）；GPU 路径使用官方镜像构建，业务代码不变。
- 本期不做 OCR 服务的降级/排队策略与任务鉴权（后续有需求再引入）。

## Risks / Trade-offs

- [CPU 推理慢：全量 1000 页向量化 + 重排延迟可能到秒级] → int8 量化、批量入库、离线时段做首次回填、检索结果缓存、重排只处理 top-N；GPU 升级路径已留。
- [DeepSeek 外部依赖：网络故障、限流、内容边界] → LLM 接口化便于切换；超时/重试/降级文案；敏感正文不出网，出网仅限改写后的问句与上下文片段。
- [表格 PDF 解析质量影响检索] → pdfplumber 保留单元格文本与页码；把典型表格样本纳入验收用例；未来复杂表格走 MinerU 替换 parser。
- [生成引用与内容不一致（幻觉）] → 生成阶段强引用格式 + 引用仅允许来自返回的 chunk；消息入库时持久化 `message_citations` 供事后校验；知识库范围外问题走「拒绝猜测」分支。
- [Milvus standalone 资源占用（etcd + MinIO）] → 单机内存预留 ≥16G；文档原文不用 Milvus 内置 MinIO，避免耦合。
- [多租户/权限后置带来的返工] → 本期所有表与集合字段已带 `tenant_id`，检索强制过滤，降低后续返工面。

## Migration Plan

全新项目，无存量数据迁移：

1. 落地 `docker-compose.yml`（postgres、redis、milvus、model-service）+ `.env` 模板，本地拉起基础设施并做连通性冒烟。
2. 按依赖顺序实现：`core`/`models` → `ingestion`（含 worker）→ `retrieval` → `chat`（LangGraph）→ `api` → 前端联调。
3. 用约 1000 页样本回填索引，跑通「上传 → 问答 → 追问」端到端验收场景。
4. 回滚策略：应用层改动走 Git 回退并重启容器；数据层保持向后兼容（新表新增，不破坏既有），Milvus collection 可整集合重建重建索引。

## Open Questions

- 切分参数（chunk 大小/重叠窗口）与 top-N/top-K 的最终取值待真实语料评估后确定；当前默认 top-N=20、top-K=3，已在检索层做成配置项。
