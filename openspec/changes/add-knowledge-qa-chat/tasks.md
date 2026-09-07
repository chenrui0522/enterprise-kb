## 1. 项目初始化与基础设施

- [x] 1.1 采用 React 初始化 monorepo 骨架：`app/` 后端包（pyproject/uv）+ `frontend/`（Vite + React）
- [x] 1.2 编写 `docker-compose.yml` 与 `.env.example`：postgres、redis、milvus(standalone + etcd + minio)、model-service(Xinference)，并本地拉起冒烟
- [x] 1.3 落地 `core`：pydantic-settings 配置、SQLAlchemy/asyncpg 引擎、Alembic 迁移、Redis 客户端、结构化日志
- [x] 1.4 创建核心数据模型并生成迁移：`documents`、`document_versions`、`conversations`、`messages`、`message_citations`、`audit_events`、`feedback_responses`（均含 `tenant_id`）

## 2. 模型接入抽象与本地模型服务

- [x] 2.1 定义 `LLMProvider` / `Embedder` / `Reranker` 接口与 OpenAI 兼容实现，配置驱动（DeepSeek base_url、模型名、温度）
- [x] 2.2 在 Xinference 中加载 bge-m3 与 bge-reranker-v2-m3，提供健康检查脚本与 CPU(int8) 配置模板，GPU 升级仅改设备参数
- [x] 2.3 检索侧为 reranker 加信号量限流（最大并发 10），并提供 provider 的本地冒烟测试（mock 可用）

## 3. 文档接入流水线

- [x] 3.1 实现文档上传 API：保存原文到本地卷（存储接口抽象）、写入 `documents`、投递 Redis 任务队列、非法格式/损坏文件返回明确错误
- [x] 3.2 实现 worker 消费入口与 `parser` 接口；提供 PDF 文字+表格解析实现（PyMuPDF/pdfplumber），统一输出页面/块模型
- [x] 3.3 实现 chunker：按标题/章节/页码切片并带重叠窗口，元数据含 `doc_id/version_id/page/tenant_id/section`
- [x] 3.4 实现 embedder 调用与 Milvus 写入（建集合、批量 upsert），驱动文档状态机与失败重试
- [x] 3.5 实现更新重新入库：新版本完成后原子切换 `current_version_id` 并删除旧版本切片
- [x] 3.6 实现文档状态/进度查询与列表 API（含失败原因与重试入口）

## 4. 检索层

- [x] 4.1 封装 Milvus 客户端与集合 schema（`id/vector/text/doc_id/chunk_index/page/section/tenant_id/version_id`）
- [x] 4.2 实现混合检索：向量召回 + BM25 加权融合，强制携带 `tenant_id` 过滤
- [x] 4.3 实现重排管线：top-N（默认 20）→ reranker → top-K（默认 3），参数做成配置项
- [x] 4.4 实现查询结果 Redis 短时缓存（键含改写问句指纹 + 租户）

## 5. 对话编排（LangGraph）

- [x] 5.1 定义对话 State（Pydantic）与会话/消息服务；接入 PostgreSQL checkpoint，`thread_id = conversation_id`
- [x] 5.2 实现 `rewrite` 节点：结合最近 3–5 轮历史将追问改写为可独立检索的问题
- [x] 5.3 实现 `need_retrieval` 判定节点：寒暄/追问既有答案等场景跳过检索直接作答
- [x] 5.4 实现 `hybrid_retrieve` 与 `direct_answer` 分支，及低相关/无结果时的拒绝猜测输出
- [x] 5.5 实现 `generate` 节点：仅允许引用返回的 chunk，输出强制引用格式，并持久化 `message_citations`
- [x] 5.6 实现历史窗口截断与会话恢复，保证超长会话不中断（对应 specs 场景）
- [x] 5.7 实现 SSE 流式问答 API：token 增量/结束/错误事件、消息落库、Redis 限流

## 6. API 与预留扩展位

- [x] 6.1 组装 FastAPI 应用：health、统一异常处理、租户上下文中间件占位（默认租户/请求头）
- [x] 6.2 实现会话 CRUD 与历史消息查询 API
- [x] 6.3 实现 `audit_events` 写入占位（记录问答与上传事件，业务消费后续实现）
- [x] 6.4 实现 `feedback_responses` 提交/查询接口占位（绑定 `message_id`，本期不做闭环业务）
- [x] 6.5 核对 OpenAPI 文档与前后端契约（SSE 事件格式、引用结构）

## 7. 前端聊天界面

- [x] 7.1 搭建前端骨架：路由、API client、流式读取封装
- [x] 7.2 实现会话列表/新建/历史加载
- [x] 7.3 实现聊天窗口：SSE 流式渲染、引用块展示（文档名+页码可定位）、加载与错误态
- [x] 7.4 实现文档管理页：上传、处理进度/状态展示、失败重试入口
- [x] 7.5 接入答案反馈占位按钮并调用反馈接口

## 8. 验收与收尾

- [x] 8.1 用约 1000 页样本跑通端到端验收：上传 → ready → 问答 → 多轮追问，引用可定位到文档页码
- [x] 8.2 编写并跑通覆盖 specs 场景的自动化测试：入库状态机、更新替换旧版本、拒绝猜测、指代消解、会话恢复、非法文件报错
- [x] 8.3 性能冒烟：模拟 50 并发 SSE、验证 reranker 并发上限 10、记录 CPU 下首轮响应延迟
- [x] 8.4 完善 README 与二次开发指引：compose 启动、`.env` 说明、parser/模型服务替换方法

## 9. 统一 Markdown 转换流水线

- [x] 9.1 新增转换器接口与 PDF(.docx/.md/.txt) 实现：PDF 保留页码标记、Word 标题/表格转 Markdown、Markdown/TXT 直通
- [x] 9.2 实现 Markdown 感知切片器：标题=章节、表格/代码块整体保留、分页标记跟随切片、长块切窗
- [x] 9.3 流水线改为“转换 → Markdown 切片 → 向量化”，上传接口校验对应扩展名与文件头
- [x] 9.4 前端支持选择 PDF/Word/Markdown/TXT 并调整引用展示（有页码显页码、无页码显章节）
- [x] 9.5 补充转换器与 Markdown 切片自动化测试并跑通

## 10. 多格式统一转换扩展（MarkItDown）
- [x] 10.1 新增 MarkItDownConverter，接入 .pptx/.xlsx/.html/.htm/.csv/.json，全部先转 Markdown 再切片
- [x] 10.2 上传 API 扩展 ALLOWED_EXTENSIONS，并校验 Office 压缩包签名（PK\x03\x04）
- [x] 10.3 前端上传 accept 与说明同步支持 PPT/Excel/HTML/CSV/JSON
- [x] 10.4 补充转换器自动化测试（PPTX/XLSX/HTML/CSV/JSON）并跑通
- [x] 10.5 真实链路冒烟：md/docx/pdf/pptx/xlsx/html/csv/json 八种格式全部入库 ready

## 11. 扫描件/复杂彩页 OCR（MinerU）
- [x] 11.1 新增 MinerU 配置：KB_MINERU_URL/API_KEY/超时/轮询/语言/后端（pipeline）与表格、公式开关
- [x] 11.2 新增 MinerUConverter（HTTP 客户端）：/health 探活、/tasks 异步提交、轮询状态、解析 results.md_content（兼容 zip 与 v2 结果结构）
- [x] 11.3 摄取流水线自动路由：图片直接 OCR、扫描 PDF（无可提取内容）自动回退 MinerU、parse_mode=ocr 强制 OCR；DB 新增 document_versions.parse_mode 并补迁移 0002
- [x] 11.4 上传 API 扩展 .png/.jpg/.jpeg 白名单、图片文件头校验、ocr 查询参数与 MinerU 未启用时的明确报错
- [x] 11.5 前端文档页支持图片上传与“强制 OCR”开关、accept 与文案同步
- [x] 11.6 docker-compose 增加可选 mineru profile 服务与 CPU 镜像 Dockerfile（docker/mineru/Dockerfile.cpu），GPU 升级路径写入 README
- [x] 11.7 补充 MinerU 客户端与流水线 OCR 路由自动化测试并跑通（31 passed）
- [ ] 11.8 端到端冒烟：本机启动 mineru-api（首次从 ModelScope 拉权重数 GB）后，用真实扫描 PDF/图片/复杂彩页走通 上传→ready→问答 并核对引用
