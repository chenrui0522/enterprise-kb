## Why

管理端审计页写死只拉最近 100 条且无时间/翻页，并发升高后审计员根本翻不到更早事件。查询 API 已支持 `offset` / `since` / `until`，缺口在界面；需要把「与查询接口一致的基本筛选」落到可浏览历史的体验上。

## What Changes

- 管理端审计查阅增加分页：基于已有 `total` / `offset` / `limit`，支持上一页/下一页与「第 a–b 条 / 共 N」展示。
- 时间筛选：快捷预设（今天 / 近 7 天 / 近 30 天 / 全部）+ 可展开自定义起止时间；筛选变更时重置到第一页。
- 单页条数可选（默认 100，可选 50/100/200，不超过现有 API 上限 500）。
- 保留现有动作名、操作者筛选；列表仍为只读。
- 非目标：导出、提高 API `limit` 上限、审计表索引/归档、拆分 `chat.completion`、统一 `write_audit` 写入语义、运维日志改动。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `identity-access`: 明确管理端审计查阅须支持时间预设（含自定义展开）与分页浏览，与只读查询接口的时间范围及分页参数对齐，而不再仅展示固定窗口内的最近一批事件。

## Impact

- 代码：主要为 `frontend/src/pages/AdminPage.jsx` 的 `AuditPanel`；`listAuditEvents` 已支持所需查询参数，通常无需改 API。
- 接口：复用 `GET /api/v1/audit/events`（`action` / `actor` / `since` / `until` / `offset` / `limit`）。
- 权限：仍为 `audit:read`；租户隔离不变。
- 测试：前端行为与既有 `test_audit_api` 互补；若有前端测试则补分页/时间预设场景，否则以手工验收清单为准。
