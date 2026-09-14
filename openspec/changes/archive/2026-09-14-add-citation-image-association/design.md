## Context

见 proposal.md。已实现并有代码证据：引用携带 `version_id`/`heading_path`；`document_images.heading_path`（迁移 0006 已执行）；MinerU content_list 章节跟踪；含媒体 Office 走 MinerU；检索时按同页/同章节挂图（每条最多 3 张，版本限定）。

## Goals / Non-Goals

**Goals:** 回答的引用能带上对应图片；覆盖 PDF 同页与 Office/无分页的章节关联。
**Non-Goals:** VLM 语义描述、文档级画廊、图片排序与模型挑选。

## Decisions

### D1 先同页，后同章节

有页码的格式（PDF、扫描件）按 `(doc_id, version_id, page)` 关联，最贴近"这一页的图"；无页面的格式（Office）按 `(doc_id, version_id, heading_path)` 关联。

### D2 数量上限与版本限定

每条引用最多 3 张，且必须属于同一文档版本，避免跨版本或整篇图片噪声。

### D3 优先自身图片证据

若切片本身是图片切片（`image_id`），保留其图片，不再追加同页/同章节图片。

### D4 Office 含媒体时改走 MinerU

为保证 Word/PPT/Excel 的图片获得章节归属，检测到内嵌媒体且 MinerU 可用时优先 MinerU 解析；MinerU 不可用时回退本地抽取（此时图片无章节，仅能靠同页/无关联）。

## Risks / Trade-offs

- [同页可能带入不相关图片] → 数量上限 + 版本限定；后续可按图片顺序或模型挑选优化。
- [Office 走 MinerU 变慢] → 只在检测到媒体时触发。
- [历史图片仍无 heading_path] → 需要一次 reindex 才能补全章节信息。

## Migration Plan

迁移 0006 已执行；历史图片的 `heading_path` 为空，重新入库（reindex）后补齐。回滚：前端忽略 `images` 字段即可恢复纯文字引用。
