## Why

12 月底验收要求系统「功能齐全、可观测、可维护」。当前仅有半结构化 stdout 文本日志、零散 `logger.*` 调用、无请求关联 ID，问答主链路几乎无阶段耗时；审计事件虽部分落库但缺少管理端查询闭环。业务功能可等到 10 月初再开，必须先把运维日志与审计日志两套基础设施打牢，否则验收与排障都会卡在「看不见」。

## What Changes

- 新增运维可观测能力：JSON 结构化日志、每请求 `request_id`（响应头回传并写入日志上下文）、关键路径阶段事件与耗时、依赖分项健康检查。
- 补强审计闭环：关键写操作审计覆盖补全；具备 `audit:read` 的用户可在管理端只读查询审计事件（筛选、分页）。
- 约定敏感字段脱敏（口令、Cookie、完整文档正文与超长问句不入运维日志）；审计详情保持可追溯但不存口令明文。
- 配置项扩展：日志级别、是否 JSON、健康检查超时等进入 `.env.example` 与 README。
- 非目标：LangSmith / 全链路 OpenTelemetry、自建 ELK/告警平台、答案反馈分析看板、长对话记忆、SSO、过时未归档 change 的清理。

## Capabilities

### New Capabilities
- `ops-observability`: 结构化运维日志、请求关联上下文、问答与入库关键阶段耗时事件、依赖分项健康检查，供运维与研发排障。

### Modified Capabilities
- `identity-access`: 扩展操作审计覆盖面，并要求提供基于 `audit:read` 的审计事件只读查询界面（或等价管理端能力），使 auditor 角色可用。

## Impact

- 代码：`app/core/logging.py` 升级为 JSON + contextvars；新增请求中间件；chat 图节点、retrieval、ingestion pipeline、providers 写入阶段日志；`/healthz` 扩展；前端 Admin 增加审计页。
- 接口：响应增加 `X-Request-ID`（或等价头）；审计 list API 增加筛选/分页（若现有不足）；健康检查返回分项状态。
- 数据：优先复用 `audit_events`；若筛选字段不足再评估迁移（设计阶段确认）。
- 依赖：尽量不新增重量级 APM 库；必要时仅用标准库或轻量 JSON formatter。
- 运维：Compose 下仍以 stdout 采集为主；文档说明如何用 `request_id` 串起一次故障。
