## Why

当前各格式的转换路径不统一：文本 PDF 用 PyMuPDF 提平文本再把表格追加到页尾（可能重复、位置丢失）；扫描件只有"整篇无文字层"才回退 OCR；Word 靠 python-docx 但图片定位依赖 MinerU；Excel 直接转成 Markdown 大表，检索效果差。同时缺少转换过程的可观测性，出问题无法区分"转换丢内容"和"检索未命中"。需要把转换流程细化为按格式分诊、可回退、可度量的链路。

## What Changes

- 新增**转换分诊**：按格式与文件特征选择转换器（扫描页/含表格公式的 PDF → MinerU；普通文字 PDF → Docling；DOCX → python-docx 自定义；XLSX → pandas 语义模板；图片 → MinerU OCR），并保留"下一个候选"回退链与本地解析兜底。
- 接入 **Docling 独立 HTTP 服务**（与 MinerU 同构部署）：worker 通过 HTTP 调用，返回结构化块（标题/段落/表格/图片 + 页码与位置）映射到统一结构。
- **XLSX 语义化转换**：按 sheet 分节、自动推断表头、逐行生成"字段=值"语义文本，语义行作为切片文本、表格结构仅作元数据，避免同一内容重复入索引。
- 新增**转换报告**：每份文档版本记录所用转换器与版本、分诊结果、降级情况、页数、表格/图片数量与耗时，供排查与回滚。
- 新增**解析缓存**：以"文件内容哈希 + 转换器 + 版本 + 参数"为键缓存解析结果，重导时可复用，避免重复解析。
- 非目标：VLM 图片语义描述、答案质量重排、以及 Docling 之外的第三方解析器。

## Capabilities

### New Capabilities
- 无。

### Modified Capabilities
- `document-ingestion`: 转换阶段由"单一本地解析"改为"分诊路由 + 独立解析服务 + 语义化表格 + 转换报告 + 解析缓存"。

## Impact

- 转换层：`app/ingestion/converters.py`、新增 `app/ingestion/triage.py`、`app/ingestion/docling.py`、`app/ingestion/tabular.py`。
- 流水线：`app/ingestion/pipeline.py`（路由、报告、缓存）、`app/ingestion/storage.py`（缓存目录）。
- 部署：`docker-compose.yml` 新增 docling 服务与模型缓存卷；worker 通过 `KB_DOCLING_URL` 调用。
- 数据：`document_versions` 增加转换报告字段（迁移）；无 Milvus schema 变化（切片结构不变）。
- 测试：各格式转换的回归用例 + 分诊/回退/报告/缓存单测。