## Why

业务文档里普遍含图（流程图、架构图、表格截图、扫描页、照片），但当前入库链路会静默丢掉图片：文本 PDF 只取文字层与表格、图片页被整页跳过；Word 只取段落与表格；PPTX/XLSX 经 MarkItDown 后图片被截断成无效文本；MinerU 已经抽出的图片因为客户端只请求 Markdown 而被丢弃。
用户明确需要"在回答里看到图片"。第一步先让图片被完整抽取、存储、随引用返回并在前端展示，同时把图内文字与原图说明纳入检索；图片的语义理解（VLM 描述）作为后续独立步骤。

## What Changes

- 含图文档统一由 MinerU 抽取图片与结构（`return_images` + `response_format_zip` + `return_content_list`）；MinerU 不可用时用本地抽取兜底（PyMuPDF / python-docx / python-pptx）。
- 图片按内容哈希去重后存入文档存储；过滤过小的装饰性图片（图标、分割线、页眉页脚 logo）。
- 新增 `document_images` 表与 Alembic 迁移，记录图片归属、页码、位置、哈希、尺寸、存储键与说明字段（为第二步 VLM 预留 `description`）。
- 文档结构新增 `image` 块类型，切片新增 `image_id`；图片的可检索文本 = 原图说明 + 图内 OCR 文字（本期不含 VLM 描述）。
- Milvus schema 增加 `image_id` 字段，需新集合版本并全量重导（复用既有 reindex 流程）。
- 新增按租户校验的图片读取接口，引用结构携带图片引用，前端在答案与文档页展示图片并可放大查看。
- 文档版本替换或重导时清理旧版本图片，避免孤儿文件。
- 非目标：VLM 图片语义描述与图表理解（第二步 `add-image-understanding`）、以图搜图/图像向量检索、图片编辑与批注。

## Capabilities

### New Capabilities
- `image-evidence`: 文档图片的抽取、去重、存储、读取与引用展示，使回答能够携带并显示原文图片。

### Modified Capabilities
- `knowledge-qa`: 引用定位要求扩展——当支撑答案的切片关联图片证据时，引用必须同时提供可展示的图片标识。

## Impact

- 入库：`app/ingestion/mineru.py`（zip 与 content_list 解析）、`app/ingestion/converters.py`（本地兜底抽取）、`app/ingestion/pipeline.py`（图片落盘与登记）、`app/ingestion/storage.py`。
- 模型：`app/models/entity.py` 新增 `document_images` 与迁移；`app/ingestion/structure.py` 新增 image 块；`app/retrieval/chunk.py` 新增 `image_id`。
- 检索与接口：`app/retrieval/milvus_store.py`（新字段与新集合）、引用组装（`app/chat/graph.py`、`app/chat/service.py`、`app/api/routers/chat.py`）、新增图片读取接口。
- 前端：引用与文档页的图片展示组件。
- 数据：文档存储容量增长；Milvus 需新集合与全量重导。