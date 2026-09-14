## Context

动机见 proposal.md。实测与代码证据：

- MinerU 3.4.5 支持 `return_images`、`response_format_zip`、`return_content_list`；实测含示意图的 PDF 返回 ZIP，内含 `images/<sha256>.jpg` 与 `content_list.json` 的 `{"type":"image","img_path":...,"image_caption":[],"image_footnote":[],"bbox":[...],"page_idx":0}`。
- 图片以内容哈希命名，天然可去重；`image_caption` 常为空，pipeline 后端不会解释图，也不提取图中文字。
- 我们的 MinerU 客户端当前只请求 `return_md=true`、`response_format_zip=false`，因此抽出的图片与结构信息被丢弃。
- 文本 PDF 转换只遍历文本块，图片页会被整页跳过；MarkItDown 默认截断 data URI 图片。
- 现有结构块类型只有 heading/paragraph/list/table/code，切片与引用里没有任何图片字段。

## Goals / Non-Goals

**Goals:**
- 任何含图文档都不再静默丢内容：图片被抽取、去重、可读取、可在回答中展示。
- 图内文字与原图说明可以参与检索，命中后引用能直接展示原图。
- 为第二步 VLM 语义描述预留结构，不需要推翻本期实现。

**Non-Goals:**
- 不做图片语义理解/图表问答（第二步）；不做以图搜图与图像向量；不做图片裁剪、OCR 后处理与图片编辑。

## Decisions

### D1 由 MinerU 统一抽图，本地抽取作为兜底

含图文档走 MinerU（ZIP + images + content_list），一次性拿到图片、页码、bbox 与结构；MinerU 不可用（未配置/失败）时回退本地抽取：PDF 用 PyMuPDF `get_image_info`、DOCX 用关系与内联图形、PPTX 用媒体部件。

替代方案：为每种格式自研抽取与版面分析。放弃原因是定位与多格式成本高，且 MinerU 已提供结构化输出。

### D2 内容寻址存储与去重

图片写入 `data/documents/<doc_id>/<version_id>/images/<sha256>.<ext>`，以 sha256 作为去重键（同文档内重复图片只存一份）；同一版本引用多份图片时保留 bbox/page 映射。

### D3 新增 document_images 表

字段：id、tenant_id、doc_id、version_id、page、bbox、storage_key、sha256、mime、width、height、caption、description（预留给第二步）、source（mineru/local）、created_at。图片与版本同生命周期。

### D4 结构块与切片新增 image 维度

`Block` 增加 `image` 类型（携带 image_id/page/bbox/alt），chunker 生成 `chunk_type=image` 的切片，文本为"原图说明 + 图内 OCR 文字"，两者都为空时使用"图片（第 X 页）"占位，避免零文本切片；Milvus 与 `ChunkRecord`/`SearchHit` 增加 `image_id`。

### D5 新集合版本承载新字段

Milvus 无法给既有集合加字段，因此创建新集合版本（如 `kb_chunks_v3`）并通过既有 reindex 流程全量重导；旧集合保留可回滚。

### D6 图片读取接口

`GET /api/v1/documents/{doc_id}/images/{image_id}`：校验租户与文档归属，返回正确 Content-Type 与长缓存头；不直接暴露文件系统路径。

### D7 引用结构携带图片

引用对象增加 `images: [{image_id, url, caption}]`；SSE `done` 事件与消息持久化中的 citations 同步扩展；历史消息缺该字段时按空列表处理，保持向后兼容。

### D8 前端展示

答案引用区展示图片缩略图，点击放大查看；文档详情页展示该文档的图片列表。图片加载失败时降级为文字引用。

### D9 过滤与告警

最小边长/字节阈值过滤装饰图；按 sha256 去重；扫描页整页图按页面证据处理；无法抽取图片的文档写入告警日志与处理状态，不再静默。

## Risks / Trade-offs

- [图片使存储显著增长] → 去重 + 阈值过滤 + 版本替换时清理旧图片。
- [入库耗时增加（抽图 + 图内 OCR）] → 图片处理只在检测到图片时触发；批量入库沿用队列，失败不影响文档整体状态。
- [Milvus 换集合需要重导] → 复用 reindex 与回滚模式，先 dry-run 再全量。
- [装饰性图片污染检索] → 尺寸阈值 + 哈希去重 + 引用展示时优先展示正文图片。
- [图片接口的权限边界] → 按租户与文档归属校验；认证能力接入后复用权限依赖。

## Migration Plan

1. 新增表与迁移，图片存储与抽取实现，单测覆盖。
2. 新建 `kb_chunks_v3` 并切换配置，dry-run 后全量重导含图文档。
3. 前端随版本升级，历史消息缺失图片字段时降级为纯文字引用。
4. 回滚：切回旧集合版本；图片文件按 version 目录整体保留。

## Open Questions

- 第二步 VLM 的部署位置与模型选型（同卡按需/独立服务），不影响本期实现。
- 是否需要跨文档复用完全相同图片的去重（当前按版本目录存储，仅在版本内去重）。