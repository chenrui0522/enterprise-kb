# Enterprise KB（企业级知识库 MVP）

面向约 50 并发、约 1000 页初始语料的企业知识库 MVP：PDF 异步接入 + 基于本地 embedding/rerank 与 DeepSeek 生成的多轮知识问答。所有文档正文留在内网，出网内容仅为对话上下文与改写后的问句。

## 能力

- 知识问答：混合检索（向量 + BM25）→ 重排 → 带引用（文档名 + 页码）生成回答；无依据时拒绝猜测。
- 多轮对话：追问改写、检索必要性判定、会话持久化、SSE 流式输出。
- 文档接入：PDF / Word / PPT / Excel / Markdown / TXT / HTML / CSV / JSON / 图片(PNG/JPG) 先经**转换分诊**选择最合适的解析路径（本地 / Docling / MinerU / 表格语义化）→ 统一转为结构块与 Markdown → 切片 → bge-m3 向量化 → 写入 Milvus；PDF 保留页码定位，支持更新版本替换与失败重试，并记录**转换报告**（转换器、分诊依据、回退、耗时、表格/图片数）。
- 扫描件 / 复杂彩页 OCR（可选）：接入本地 MinerU 服务后，图片与无文本层的扫描 PDF 自动走 OCR，复杂版式彩页手册可上传时强制 OCR（`ocr=true`）。
- 预留扩展位：`tenant_id`、审计事件、答案反馈均落表，业务逻辑后续迭代。

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.12 · FastAPI · SQLAlchemy(async) · Alembic |
| 对话编排 | LangGraph（PostgreSQL checkpointer，thread_id=conversation_id） |
| 生成模型 | DeepSeek `deepseek-v4-flash`（OpenAI 兼容） |
| 本地模型 | Xinference：bge-m3（embedding）+ bge-reranker-v2-m3（重排，并发上限 10，CPU 起步） |
| 检索存储 | Milvus 2.5（dense + BM25 Function，RRF 融合） |
| 业务存储 | PostgreSQL + Redis（缓存/队列/限流） |
| 前端 | React + Vite（SSE 流式聊天 + 文档管理） |
| 部署 | Docker Compose（本地单机） |

> **安全提示**：`docker-compose.yml` 中内嵌的数据库/对象存储口令（如 `kb/kb`、`minioadmin/minioadmin`）仅供本地开发使用，公开部署前必须修改。真实密钥（如 `KB_LLM_API_KEY`）请填入本地 `.env`（该文件不会入库，可参考 `.env.example`）。

## 快速开始

### 1. 准备配置

```bash
cp .env.example .env
# 编辑 .env：填入 KB_LLM_API_KEY；按需调整本地模型地址等
```

### 2. 启动基础设施与模型服务

```bash
docker compose up -d postgres redis etcd minio milvus model-service
# 有 NVIDIA GPU 时改用 GPU override 启动模型服务（基础 compose 仍可用于纯 CPU）：
#   docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d model-service
# 等待健康检查通过后，注册本地模型（默认 GPU，从 ModelScope 下载权重，首次可能需要几分钟）
.\scripts\init-models.ps1    # Windows；CPU 回退：-Device cpu
# bash 环境：./scripts/init-models.sh        CPU 回退：MODEL_DEVICE=cpu ./scripts/init-models.sh
```

### 3. 启动后端与前端

```bash
uv sync --extra dev
uv run python run.py            # Windows（内含事件循环策略）；Linux/macOS 也可用 uvicorn 直接启动
uv run python -m app.worker          # 另一个终端：接入 worker

cd frontend
npm install
npm run dev                           # http://localhost:5173
```

首次启动会按 `KB_AUTO_CREATE_TABLES=true` 自动建表（生产环境建议关闭并用 Alembic）：

```bash
alembic upgrade head
```

> 若仓库代码是从旧版本升级（数据库已存在），请在重启 API/worker 前先执行 `alembic upgrade head`（新增 `document_versions.parse_mode` 列，用于记录“自动解析 / 强制 OCR”）。

## 主要配置（`.env`，前缀 `KB_`）

| 变量 | 说明 |
|---|---|
| `KB_LLM_API_KEY` / `KB_LLM_MODEL` | DeepSeek key 与模型（默认 `deepseek-v4-flash`） |
| `KB_EMBEDDER_BASE_URL` / `KB_EMBEDDER_MODEL` | Xinference embedding 地址与 bge-m3 |
| `KB_RERANKER_BASE_URL` / `KB_RERANKER_MODEL` | Xinference rerank 地址与模型 |
| `KB_RERANK_MAX_CONCURRENCY` | 重排并发上限（CPU 默认 10，GPU 可调到 32） |
| `KB_EMBED_BATCH_SIZE` | 入库 embedding 批大小（CPU 默认 32，GPU 可用 128） |
| `KB_RETRIEVAL_TOP_N` / `KB_RETRIEVAL_TOP_K` | 召回 / 精排数量（默认 20 / 3，初始值待语料调优） |
| `KB_MILVUS_URI` / `KB_MILVUS_COLLECTION` | Milvus 地址与集合名 |
| `KB_DATABASE_URL` / `KB_REDIS_URL` | PostgreSQL / Redis |
| `KB_CHUNK_SIZE` / `KB_CHUNK_OVERLAP` | 切片参数（待语料调优） |
| `KB_MINERU_URL` | MinerU OCR 服务地址；留空则关闭 OCR（图片上传会返回 503 提示） |
| `KB_MINERU_BACKEND` | MinerU 后端，CPU 期用 `pipeline`（默认），GPU 升级后可按需切 VLM/hybrid |
| `KB_MINERU_TIMEOUT_SECONDS` / `KB_MINERU_POLL_INTERVAL` | OCR 任务超时与轮询间隔（默认 3600s / 3s） |
| `KB_MINERU_LANG` / `KB_MINERU_TABLE_ENABLE` / `KB_MINERU_FORMULA_ENABLE` | OCR 语言（默认 ch）、是否启用表格/公式解析 |
| `KB_MINERU_PREFER_COMPLEX` | 含表格/公式的 PDF 是否优先走 MinerU（默认 true；CPU OCR 较慢时可设 false 改成本地优先） |
| `KB_DOCLING_URL` | Docling 解析服务地址（如 `http://127.0.0.1:8003`）；留空则跳过该候选 |
| `KB_DOCLING_OCR_ENABLED` / `KB_DOCLING_TABLE_MODE` | Docling 的 OCR 开关与表格模式（`fast`/`accurate`） |
| `KB_CONVERSION_TRIAGE_ENABLED` / `KB_PARSE_CACHE_ENABLED` | 转换分诊与解析缓存开关（默认均开启） |

## GPU 推理（可选）

词嵌入（bge-m3）与重排（bge-reranker-v2-m3）默认可以在 CPU 上运行；有 NVIDIA GPU 且 Docker 支持 GPU 直通时，推荐切到 GPU：

```bash
# 1) 用 GPU override 启动模型服务（基础 compose 保持 CPU 可用）
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d model-service

# 2) 启动/恢复两个模型（默认 cuda）
powershell -ExecutionPolicy Bypass -File scripts\init-models.ps1
# bash：./scripts/init-models.sh         CPU 回退：MODEL_DEVICE=cpu ./scripts/init-models.sh
```

验证：`curl http://127.0.0.1:9997/v1/models`，两个模型的 `accelerators` 应显示 GPU 编号（CPU 时为空数组）。

- 显存参考：两个模型 fp32 同时驻留约 4.7GB（RTX 5060 8GB 实测可用）；
- `KB_EMBED_BATCH_SIZE`：CPU 建议 32，GPU 可用 128；
- `KB_RERANK_MAX_CONCURRENCY`：CPU 保持 10，GPU 可提高到 32；
- 重启 `model-service` 会清空已启动模型列表（权重仍缓存在卷中），重新执行 `init-models` 脚本即可恢复，脚本是幂等的。
## MinerU OCR 接入（可选）

MinerU 独立作为「统一解析服务」，本系统通过 HTTP 调用，不打包进 API/worker 镜像：

- 图片（`.png/.jpg/.jpeg`）上传 → 自动走 MinerU OCR；
- 文字层为空的 PDF（扫描件）→ 先走本地 PyMuPDF，无内容自动回退 MinerU OCR；
- 复杂彩页手册（有文字层但版式复杂）→ 上传时勾选「强制 OCR」或带 `ocr=true`，直接交给 MinerU；
- OCR 产出的 Markdown 与普通文档共用同一套「切片 → bge-m3 → Milvus」，OCR 文档按章节标题定位引用。

### 方式 A：CPU 优先（本期推荐）

```bash
# 1) 构建 CPU pipeline 镜像（首次构建拉取 CPU 版 torch + mineru，体量大、耗时长）
docker build -f docker/mineru/Dockerfile.cpu -t mineru-cpu .

# 2) .env 里指向镜像并启用
#    MINERU_IMAGE=mineru-cpu
#    KB_MINERU_URL=http://127.0.0.1:8002        # 宿主本地调试 worker 用

# 3) 启动（api/worker 在容器内时改 KB_MINERU_URL=http://mineru-api:8000）
docker compose --profile mineru up -d mineru-api
```

首次解析会从 ModelScope 按需下载 OCR/布局权重（数 GB），之后缓存在 `mineru-home` 卷中。

### 方式 B：GPU（后续升级路径）

按 [MinerU 官方 Docker 文档](https://github.com/opendatalab/MinerU/blob/master/docs/zh/quick_start/docker_deployment.md) 使用 `docker/china/Dockerfile` 构建 `mineru:latest`（需 NVIDIA 驱动/CUDA），然后同样执行 `docker compose --profile mineru up -d mineru-api`；`.env` 保持 `KB_MINERU_BACKEND=pipeline` 即可先用 GPU 跑 pipeline，后续再切换 VLM 类后端。

### 直接跑 Python 服务（替代 Docker）

在 Linux/WSL2 内 `pip install "mineru[pipeline]"` 后启动：

```bash
mineru-api --host 0.0.0.0 --port 8002
export MINERU_MODEL_SOURCE=modelscope   # 国内下载模型权重
```

然后把 `KB_MINERU_URL` 指向该服务即可。本系统只需 MinerU 提供 `/health`、`/tasks`、`/tasks/{id}`、`/tasks/{id}/result` 接口。

## 文档转换分诊与解析缓存

入库前会先做一次**轻量分诊**（`app/ingestion/triage.py`）：PDF 按页判断文字层、图片与表格，再决定用哪个转换器；分诊结论与最终路由（`triage` / `plan`）会写入该文档版本的**转换报告**。

| 文件特征 | 首选转换器 | 回退顺序 |
|---|---|---|
| 无文字层（扫描件） | MinerU OCR | 本地解析 |
| 部分页面无文字层 | 混合解析：文字页本地 + 扫描页单独 OCR | MinerU 整篇 OCR → 本地 |
| 含表格/公式的 PDF | MinerU（`KB_MINERU_PREFER_COMPLEX=false` 改成本地优先） | Docling → 本地 |
| 普通文字 PDF | Docling（未配置则本地） | 本地解析 → OCR |
| DOCX | python-docx（标题层级 + 图片按章节挂载） | MinerU |
| XLSX | 表格语义化（按 sheet 分节、逐行「字段=值」） | MarkItDown → MinerU |
| PPTX / HTML / CSV / JSON / MD / TXT | MarkItDown / 直读 | —— |
| 图片 | MinerU OCR | —— |

- **首选失败按顺序回退**：只有“转换器不可用 / 无法提取内容 / 上游失败”才回退；文件本身损坏或加密会立即报错，不会再去跑几分钟 OCR。
- **转换报告**：`GET /api/v1/documents/{id}/conversion-report` 返回转换器与版本、分诊依据、回退链与失败原因、页数、表格数、图片数、耗时与缓存命中情况。
- **解析缓存**：键为「文件 sha256 + 转换器 + 版本 + 参数」，落在 `data/documents/_parse_cache/`；重复入库同一文件直接复用，转换器升级或参数变化自动失效（删除该目录即强制重解析）。
- XLSX 等表格文档的原始网格作为元数据写入 `data/documents/<doc>/<ver>/tables/*.json`，只用于后续行级切片，**不额外进入向量库**，避免同一内容重复索引。

### Docling 解析服务（可选，独立 HTTP 服务）

与 MinerU 同构：Docling 跑在独立容器里，worker 通过 HTTP 调用（`KB_DOCLING_URL`）；服务不可用时自动跳过该候选，不影响转换完成。

```bash
# 1) 构建镜像（首次拉取 docling 依赖，体量较大）
docker build -f docker/docling/Dockerfile -t docling-api .

# 2) 启动服务（compose profile: docling，宿主端口 8003）
docker compose --profile docling up -d docling-api

# 3) .env 指向服务后重启 api / worker
#   KB_DOCLING_URL=http://127.0.0.1:8003
```

服务接口：`GET /health` 与 `POST /convert`（multipart `files` + `to_formats` / `do_ocr` / `table_mode` / `return_blocks`），返回 `{markdown, page_count, blocks[]}`。

### 转换基线评测

```bash
uv run python scripts/eval_conversion.py --samples data/conversion_eval             # 本地解析基线
uv run python scripts/eval_conversion.py --samples data/conversion_eval --docling   # 叠加 Docling 对比
uv run python scripts/eval_conversion.py --samples data/conversion_eval --ocr       # 叠加 MinerU（CPU 慢）
```

输出每个样例的分诊结果、各候选转换器的耗时/块数/表格数/图片数与汇总，并写入 `<samples>/conversion_results.json`；检索侧对比仍用 `scripts/eval_recall.py`。把几份真实文档放进 `data/conversion_eval` 即可复现基线。

参考基线（本机，189KB 制度类 PDF）：本地解析约 0.5s / 177 个结构块 / 6 张表格；DOCX 约 30–200ms。引入 Docling 的收益用同一脚本 `--docling` 对比即可量化。

## 图片证据（抽取与展示）

含图文档入库时会抽取图片（MinerU 的 ZIP/content_list，或本地 PyMuPDF/Office 兜底）、按内容哈希去重并过滤装饰性小图；图片以 `document_images` 记录并与文档版本绑定。图片切片带 `image_id`，检索命中后引用中会返回 `images: [{image_id, url, caption}]`，前端在引用区展示缩略图、在文档页可浏览该文档的全部图片。

- 图片读取接口：`GET /api/v1/documents/{id}/images`（列表）与 `GET /api/v1/documents/{id}/images/{image_id}`（原图），均按租户与文档归属校验
- 版本替换或重导时旧版本图片会被清理；当前集合为 `kb_chunks_v3`（含 `image_id` 字段）
- 图片的语义理解（VLM 描述）为后续第二步，本期只做抽取、展示与图内文字检索

## 主要 API

- `POST /api/v1/documents`：上传 PDF / Word / PPT / Excel / Markdown / TXT / HTML / CSV / JSON / 图片(PNG/JPG)（立即受理，后台先转 Markdown 再入库）；可带 `?ocr=true` 强制走 MinerU OCR
- `GET /api/v1/documents`、`GET /api/v1/documents/{id}`、`GET /api/v1/documents/{id}/conversion-report`（转换报告）、`POST /api/v1/documents/{id}/retry`
- `POST /api/v1/chat/stream`：SSE 流式问答（`message` + 可选 `conversation_id`）
- `POST /api/v1/conversations`、`GET /api/v1/conversations`、`GET /api/v1/conversations/{id}/messages`
- `POST /api/v1/feedback`：答案反馈占位
- `GET /api/v1/audit/events`、`GET /healthz`

SSE 事件：`message_start` → `token`* → (`error`) → `done`。`done` 携带完整答案与 `citations`（文档名 + 页码）。

## 目录结构

```
app/
  api/         路由、SSE、中间件、应用组装
  chat/        LangGraph 状态与节点、会话仓库服务
  retrieval/   Milvus schema/混合检索、重排、缓存
  ingestion/   parser 接口、chunker、本地存储、队列、流水线
  worker/      接入 worker 入口
  providers/   LLM / Embedder / Reranker 接口与实现
  core/        配置、DB、Redis、租户、限流、日志
  models/      SQLAlchemy 模型
frontend/      React 聊天界面
alembic/       数据库迁移
scripts/       init-models.sh 等
```

## 二次开发指引

- **换模型**：只替换 `app/providers/factory.py` 对应工厂的实现；接口见 `app/providers/base.py`。GPU 部署见上文「GPU 推理（可选）」。
- **OCR 与解析器**：`app/ingestion/triage.py` 负责分诊与路由（`plan_candidates`），`app/ingestion/mineru.py` / `app/ingestion/docling.py` 是两个独立解析服务的 HTTP 客户端，`app/ingestion/tabular.py` 做 XLSX 语义化，`app/ingestion/cache.py` 是内容寻址的解析缓存。调整路由只改 `triage.plan_candidates` 一处。旧文档解析失败后调用重试即走新解析。
- **换向量库 / 检索策略**：`app/retrieval/milvus_store.py` 是唯一直接触碰 Milvus 的地方。
- **多租户 / 权限 / 审计 / 反馈**：所有表与集合均带 `tenant_id`；`app/chat/service.py` 的审计与反馈写入已预留，后续只需增加鉴权中间件与业务规则。
- **LangSmith / trace**：模型 provider 与图节点中已留出埋点位；本期使用结构化日志，无需改接口即可后续接入。

## 测试

```bash
uv run pytest -q
```

覆盖：切分、改写/判定/拒绝猜测图流程、PDF 解析、存储路径安全等（无需外部服务）。依赖真实服务的端到端验收（上传 → ready → 问答 → 多轮追问、50 并发 SSE、CPU 延迟记录）需在本地 Compose 拉起后执行。
