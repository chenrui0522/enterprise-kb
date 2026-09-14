## Why

回答命中文字切片时不会带出相关图片：图片只有在"命中的切片本身就是图片切片"时才会出现，而 MinerU 抽出的图大多没有可检索文本，因此实际使用中几乎看不到图。用户需要"回答里能看到与该信息对应的图片"。

## What Changes

- 引用自动关联图片：引用优先保留自带的图片证据；否则按**同页**（有页码格式）或**同章节**（无分页格式）关联图片，每条引用最多 3 张且限定同一文档版本。
- `document_images` 增加 `heading_path`，MinerU `content_list` 解析时按标题跟踪为图片记录章节。
- 含内嵌媒体的 Office 文档优先经 MinerU 解析，使 Word/PPT/Excel 的图片也能获得章节归属。
- 非目标：VLM 图片语义描述（图片内容语义检索）、文档级图片画廊。

## Capabilities

### New Capabilities
- 无。

### Modified Capabilities
- `image-evidence`: 增加"引用自动关联相关图片"的行为（原需求只要求图片证据可读取与参与检索，未定义引用与图片的关联规则）。

## Impact

- 模型与迁移：`document_images.heading_path`（迁移 0006）。
- 入库：`app/ingestion/images.py`（章节跟踪、媒体检测）、`app/ingestion/pipeline.py`（Office 路由、字段落库）。
- 检索与引用：`app/api/routers/chat.py`（同页/同章节挂图）、`app/chat/graph.py`（引用携带 `version_id`/`heading_path`）。
- 测试：新增挂图与章节跟踪单测。
