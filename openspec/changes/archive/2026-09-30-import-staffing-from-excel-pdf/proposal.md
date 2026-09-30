## Why

人员投入目前只接受标准 `.xlsx` 项目日报。现场常把同一张表从 Excel 导出成 PDF 再上传，系统会直接拒绝，用户只能再另存一次工作簿。

## What Changes

- 人员投入导入（独立页与对话附件）接受从 Excel 导出的项目日报 PDF，并得到与上传原 xlsx 相同的解析结果、复核与确认流程。
- PDF 先在本地还原为单元格网格并写成临时 xlsx，再交给现有日报解析；不新增第二套姓名、身份或日期规则。
- 扫描件、拍照件、Word 以及其他无法还原出「日期 / 现场施工人员」表的 PDF 仍拒绝或进入现有「无法阅读」告警，不写入出勤事实。
- 汇总导出保持 `.xlsx`，不增加 PDF 导出。

## Capabilities

### New Capabilities

- 无

### Modified Capabilities

- `staffing-daily-import`：直接导入除标准 xlsx 外，还接受 Excel 导出的日报 PDF，经还原网格后沿用现有内部员工解析与复核。
- `chat-tools`：对话中触发人员投入的日报附件除 `.xlsx` 外，包含同类 Excel 导出 PDF。

## Impact

- 解析入口：`app/staffing/parse.py` 之前增加 PDF 网格还原（复用已有 `pdfplumber`），再调用 `parse_daily_report`。
- 导入 API：`POST /api/v1/staffing/imports` 按扩展名接受 `.pdf`。
- 对话附件：`save_chat_xlsx` 所在的附件校验，以及 `ChatPage` / `StaffingPage` 的文件选择与文案。
- 不改出勤事实模型、复核决议、确认覆盖、工期段、汇总与 xlsx 导出。
- 不调用知识库转换（Docling / MinerU / Markdown），也不为这类 PDF 做 OCR。
