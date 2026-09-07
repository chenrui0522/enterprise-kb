# Enterprise KB（企业级知识库 MVP）

面向约 50 并发、约 1000 页初始语料的企业知识库 MVP：PDF 异步接入 + 基于本地 embedding/rerank 与 DeepSeek 生成的多轮知识问答。所有文档正文留在内网，出网内容仅为对话上下文与改写后的问句。

## 能力

- 知识问答：混合检索（向量 + BM25）→ 重排 → 带引用（文档名 + 页码）生成回答；无依据时拒绝猜测。
- 多轮对话：追问改写、检索必要性判定、会话持久化、SSE 流式输出。
- 文档接入：PDF / Word / PPT / Excel / Markdown / TXT / HTML / CSV / JSON / 图片(PNG/JPG) 统一先转为 Markdown → Markdown 切片 → bge-m3 向量化 → 写入 Milvus；PDF 保留页码定位，支持更新版本替换与失败重试。
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
# 等待健康检查通过后，注册本地模型（CPU，从 ModelScope 下载权重，可能需要几分钟）
.\scripts\init-models.ps1    # Windows PowerShell：powershell -ExecutionPolicy Bypass -File scripts\init-models.ps1
# bash 环境：./scripts/init-models.sh
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
| `KB_RERANK_MAX_CONCURRENCY` | 重排并发上限（默认 10） |
| `KB_RETRIEVAL_TOP_N` / `KB_RETRIEVAL_TOP_K` | 召回 / 精排数量（默认 20 / 3，初始值待语料调优） |
| `KB_MILVUS_URI` / `KB_MILVUS_COLLECTION` | Milvus 地址与集合名 |
| `KB_DATABASE_URL` / `KB_REDIS_URL` | PostgreSQL / Redis |
| `KB_CHUNK_SIZE` / `KB_CHUNK_OVERLAP` | 切片参数（待语料调优） |
| `KB_MINERU_URL` | MinerU OCR 服务地址；留空则关闭 OCR（图片上传会返回 503 提示） |
| `KB_MINERU_BACKEND` | MinerU 后端，CPU 期用 `pipeline`（默认），GPU 升级后可按需切 VLM/hybrid |
| `KB_MINERU_TIMEOUT_SECONDS` / `KB_MINERU_POLL_INTERVAL` | OCR 任务超时与轮询间隔（默认 3600s / 3s） |
| `KB_MINERU_LANG` / `KB_MINERU_TABLE_ENABLE` / `KB_MINERU_FORMULA_ENABLE` | OCR 语言（默认 ch）、是否启用表格/公式解析 |

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

## 主要 API

- `POST /api/v1/documents`：上传 PDF / Word / PPT / Excel / Markdown / TXT / HTML / CSV / JSON / 图片(PNG/JPG)（立即受理，后台先转 Markdown 再入库）；可带 `?ocr=true` 强制走 MinerU OCR
- `GET /api/v1/documents`、`GET /api/v1/documents/{id}`、`POST /api/v1/documents/{id}/retry`
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

- **换模型**：只替换 `app/providers/factory.py` 对应工厂的实现；接口见 `app/providers/base.py`。GPU 升级只改 Xinference 设备参数与容器资源。
- **OCR 与解析器**：`app/ingestion/mineru.py` 是 MinerU HTTP 客户端，`app/ingestion/pipeline.py` 的 `_plan_converters` 决定路由（auto：文字 PDF→扫描回退 OCR；ocr：直接 OCR）。旧文档解析失败后调用重试即走新解析。
- **换向量库 / 检索策略**：`app/retrieval/milvus_store.py` 是唯一直接触碰 Milvus 的地方。
- **多租户 / 权限 / 审计 / 反馈**：所有表与集合均带 `tenant_id`；`app/chat/service.py` 的审计与反馈写入已预留，后续只需增加鉴权中间件与业务规则。
- **LangSmith / trace**：模型 provider 与图节点中已留出埋点位；本期使用结构化日志，无需改接口即可后续接入。

## 测试

```bash
uv run pytest -q
```

覆盖：切分、改写/判定/拒绝猜测图流程、PDF 解析、存储路径安全等（无需外部服务）。依赖真实服务的端到端验收（上传 → ready → 问答 → 多轮追问、50 并发 SSE、CPU 延迟记录）需在本地 Compose 拉起后执行。
