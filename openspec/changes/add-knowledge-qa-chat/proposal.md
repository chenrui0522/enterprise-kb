## Why

企业内部知识分散在产品手册、制度文档和程序文件等 PDF 中，员工查找与理解成本高。当前需要从零搭建企业级知识库的第一期能力：让用户能够对已纳管文档进行**知识问答**并**连续多轮追问**，答案可追溯到具体文档和页码，为后续审计、多租户、权限、反馈闭环等企业级能力打好可演进的地基。

## What Changes

- 新建 FastAPI 后端服务，提供会话、问答、文档、反馈等 REST 接口，并通过 SSE 流式输出回答。
- 引入 LangGraph 对话编排图：结合历史改写问题 → 判定是否需要检索 → 混合检索（向量 + BM25）→ 重排 → 生成带引用的回答。
- 生成模型接入 DeepSeek `deepseek-v4-flash`（外部 API，OpenAI 兼容协议）；embedding 与重排使用本地 bge-m3 / bge-reranker-v2-m3，先 CPU 运行、预留 GPU 升级，文档全文不出内网。
- 构建异步文档接入流水线：上传 PDF → Redis 任务队列 → worker 解析（当前支持文字与表格 PDF）→ 切片 → 向量化 → 写入 Milvus 与 PostgreSQL，以文档状态机跟踪进度并支持增量更新。
- 引入基础设施：PostgreSQL（文档/会话/审计预留/反馈预留元数据）、Redis（缓存/任务队列/限流）、Milvus（向量 + 全文检索）。
- 新增 React/Vue 聊天前端，支持流式输出、引用来源展示，并预留答案反馈入口（本期不实现反馈闭环业务）。
- 所有核心数据模型预埋 `tenant_id`，为多租户、文档级权限、审计日志、答案反馈留出扩展位（本期不实现对应功能）。
- 以 Docker Compose 本地部署全部组件，面向约 50 并发、约 1000 页初始语料的运行规模。

- 多格式统一先转 Markdown：上传的 .pdf/.docx/.pptx/.xlsx/.md/.markdown/.txt/.html/.csv/.json 全部先转换为 Markdown，再统一走 Markdown 感知切片与向量化入库；PDF 保留页码标记，其余格式以章节定位。新增 PPT/Excel/HTML/CSV/JSON 由 MarkItDown 转换。
- OCR 扩展：接入本地 MinerU 解析服务（可选、HTTP 调用），图片与扫描 PDF 自动走 OCR、复杂彩页手册可强制 OCR，解析结果同样先进统一 Markdown 流水线再入库，CPU 期以 pipeline 后端起步、预留 GPU/VLM 切换。
## Capabilities

### New Capabilities

- `knowledge-qa`: 用户基于已纳管文档提问，系统检索相关内容并生成带引用、可溯源的答案；无相关内容时明确拒绝猜测。
- `multi-turn-chat`: 在多轮会话中结合对话历史理解追问，改写查询、判定检索必要性，保持上下文一致并持续返回带引用答案。
- `document-ingestion`: 上传 PDF/Word/PPT/Excel/Markdown/TXT/HTML/CSV/JSON 文档后异步完成 「先转 Markdown、切片、向量化、索引」，提供进度与状态查询，并支持更新后的重新入库。

### Modified Capabilities

无（全新项目，尚无既有规格）。

## Impact

- 新增代码模块：`app/`（api、chat、retrieval、ingestion、core、audit、worker 等）与前端聊天界面。
- 新增外部依赖与运行服务：DeepSeek API、Milvus、PostgreSQL、Redis、本地 TEI/Xinference 模型服务、任务队列 worker。
- 新增本地部署编排：`docker-compose.yml` 及环境配置。
- 运行环境：本地单机 Docker Compose 起步，模型推理先 CPU 后 GPU，为二次开发保留清晰模块边界。
