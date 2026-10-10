## Why

考勤汇总台账专页已可用，但运营文员日常在问答会话里做调休时，无法用同一套对话工具完成「太原考勤汇总」。三源附件与调休高度重叠，若不做对话认领与澄清，文员只能反复切专页；V1 曾明确推迟对话工具，现需对齐调休全套体验。

## What Changes

- 问答工具下拉增加「考勤汇总台账」（按 `attendance_summary` 读/写权限过滤）；显式选中后本轮优先认领。
- 同一会话内完成与专页同口径的工作流：建当月（或话术指定月）任务、接 prior / 上传正式导出台账、可选人事花名册差异决议、分次或一次上传三源、冲突/HR 告警决议、二次确认、模板导出；绑任务后可对当前 `compute_result` 只读问答。
- 路由：未显式选中且附件/话术像调休或考勤（含含糊三源）时 **总是先问**「调休台账 / 考勤汇总台账 / 只要讲解」，确认前 MUST NOT 建考勤任务或写确认；显式工具与 sticky job 优先。
- 年月：默认自然月当月；文案含「做 9 月」等可解析月份则用该月；说不清再问。
- 独立「考勤汇总台账」专页 MUST 继续可用。
- **不包含**：加班作为第四源；自动扣款；月历/国外关键字配置改到对话（仍走专页/配置 API）；从任意非系统模板猜 prior；因对话工具移除专页。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `chat-tools`: 增加考勤汇总台账工具的可见性、显式认领、含糊澄清（相对调休）、对话内全套工作流与当前任务只读问答；澄清文案覆盖调休与考勤二选一（及讲解）。

## Impact

- 后端：`chat/tools` 注册表与路由、新 `attendance_summary` orchestrator / query / tool-action；复用 `app/attendance_summary` service；会话 `tool_state` sticky job。
- 前端：`ChatPage` 工具项、进度卡与动作按钮（对齐 `LeaveLedgerJobCard` 模式）；导出走既有 `/attendance-summary/.../export.xlsx`。
- 规格：`openspec/specs/chat-tools/spec.md` 增量要求。
- 领域：不改考勤计算口径；依赖已落地的 `attendance_summary` API（`add-attendance-summary-ledger`）。
