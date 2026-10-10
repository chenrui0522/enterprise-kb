## Why

考勤汇总台账曾在本机落地（专页 + 对话 + 计算导出），主规格与对话规格已归档，但源码从未进入 `origin/main`。工作区已用 `.pyc`/marshal 等方式拼回大量后端源，但对话主路径尚未验收「能算能导出」。运营当前优先要在问答里跑通台账，专页可后补。

## What Changes

- **本阶段目标（对话优先）**：对话工具认领 → prior/花名册 → 三源上传 → 月历/期间（已证据化者）→ 重算 → 告警决议 → 确认 → 太原模板正式导出；进度卡动作绑定真实后端。验收口径：**对话里能算、能确认、能导出**。
- **本阶段延后**：独立专页 `AttendanceSummaryPage.jsx`、导航入口恢复、专页专用 api 客户端补齐（路由可继续指向首页以免白屏）。专页不阻塞本阶段 done。
- **一并恢复能证据化的增量**（未归档 attendance-*/chat-attendance-* 与 pyc/UI 交叉验证后才纳入）：期间、应出勤日历、打卡×出差/驻地裁剪等——以对话路径可触达者为先。
- **真源顺序**：主规格 → `.pyc` 语义 → `ChatPage` 动作清单 → 未归档 OpenSpec 增量 → 会话口径决议作回归。
- 对话主路径恢复后 **MUST commit** 进仓库（领域/API/orchestrator 源文件）；专页可另开后续提交。
- **不包含**：从零重写另一套口径；无法证据化的增量当已交付；本阶段强制交付专页；顺带大改调休/人员投入。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `attendance-summary-ledger`: 实现必须可运行且与已归档 V1 一致；本阶段以对话/API 可达路径验收，专页入口要求延后。
- `chat-tools`: 恢复对话侧考勤汇总工具的可验证要求（认领、进度卡、确认、导出）；专页入口场景标为延后。

## Impact

- 后端：保证 `app/attendance_summary/*`、models、router、orchestrator/query 可导入并接线；identity 门禁可用。
- 前端（本阶段）：`ChatPage` 考勤卡与导出/预览 API 对齐；专页与 nav 延后。
- 测试：至少覆盖对话/API 建任务→计算→确认→导出（未确认不可正式导出）。
- OpenSpec：未归档 attendance-* change 证据并入后可另归档；非本阶段一次清完。
