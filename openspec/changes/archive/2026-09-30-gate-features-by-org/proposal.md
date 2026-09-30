## Why

人员投入与调休台账目前只按角色权限串开放（admin/editor/reader 默认可读或可写），任意部门挂 editor 即可使用。业务要求人员投入仅项目管理部、调休台账仅运营管理中心可用；需在动作权限之外增加组织范围闸门。

## What Changes

- 对人员投入、调休台账实行**双闸**：具备对应 `staffing:*` / `leave_ledger:*` **且**岗位/编制组织落在允许子树（或为管理员绕过）。
- 允许组织：人员投入 = `project_mgmt` 子树（含项目一/二部）；调休台账 = `ops` 子树（运营管理中心整棵）。
- 持有管理员能力（以 `users:manage` 为信号）的主体 **不受** 部门闸限制，仍受动作权限约束（admin 角色自带全部动作权）。
- 闸门覆盖服务端 API、对话工具认领/路由，以及前端导航/入口显隐（前端不可单独作为安全边界）。
- **BREAKING**（授权）：原仅凭 editor/reader 权限即可使用两功能、但岗不在允许子树的用户将被 403 / 入口隐藏。

## Capabilities

### New Capabilities

- （无）

### Modified Capabilities

- `identity-access`: 增加「部门专属业务功能」双闸与 admin 绕过的通用行为要求。
- `staffing-daily-import`: 人员投入在既有 `staffing:*` 与项目范围之外，增加项目管理部子树组织闸。
- `leave-ledger`: 调休台账在既有 `leave_ledger:*` 之外，增加运营管理中心子树组织闸（主规格若尚未收录该能力，以本变更增量引入该组织闸需求；与既有 leave-ledger 变更增量并存）。

## Impact

- 后端：`app/identity/`（子树解析 + 依赖/辅助校验）、`app/api/routers/staffing.py`、`leave_ledger.py`、chat 工具 `registry`/`router`/orchestrator。
- 前端：`App.jsx` 导航、`StaffingPage` / `LeaveLedgerPage`、对话工具下拉（与 `/me` 返回的权限及可选 org 能力对齐）。
- 可能需 `/me` 或既有 Principal 投影暴露「是否可用某功能」或前端用 org_unit 信息自行判断；以服务端拒绝为准。
- 默认 `ROLE_PERMISSIONS` 可不立刻拆包；部门闸即可挡住错部门用户。是否从 editor/reader 默认移除这两权可另议，非本期必须。
