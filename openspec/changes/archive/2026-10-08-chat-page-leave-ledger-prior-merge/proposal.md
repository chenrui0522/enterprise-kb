## Why

跨月连续出差等场景必须把「上月/以往已确认台账」并入本月结果，否则 30 天额度与加班口径会错。今天合并只在调休台账专页、且 prior 只能是系统内已确认任务；对话无合并入口，本机只有正式导出 Excel、系统里没有对应任务时也无法合并。文员需要在对话与专页都能选系统 prior，或上传本系统导出的太原一人多行台账后合并出最新版。

## What Changes

- **对话**：在已挂接当前未确认调休任务且已有计算结果时，支持显式选择同租户已确认 prior 任务并合并写回（与专页同一 merge 规则与 sticky）。
- **对话 + 专页**：支持上传本系统导出的太原正式台账 xlsx，逆导入为可选用的 prior 任务后，再对本月任务执行合并；用户 MUST 显式确认「用这份合并」，系统 MUST NOT 因文件名含「台账」自动合并。
- 导入产生的 prior 进入与已确认任务同一可选列表（可标注为导入来源），供对话与专页点选；合并规则、sticky `merged_from_job_id`、假日重审保持与现有段级合并一致。
- 更新文员指南：对话/专页均可选 prior 或上传导出台账合并。
- **不包含**：任意非系统导出模板的历史表解析；考勤/人员投入的「接上期」实现（仅在设计中预留契约说明）；自动猜测应选哪份 prior。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `leave-ledger`: 允许将本系统正式导出台账 xlsx 导入为可合并 prior；专页除选已确认任务外支持该上传导入路径。
- `chat-tools`: 对话调休台账支持选已确认/导入 prior 并合并，以及上传正式导出台账作为 prior 后合并。

## Impact

- 后端：导出台账逆解析 → 创建/登记 prior 任务；merge API 可复用；chat `leave_ledger.merge`（及可选 import）工具动作；审计区分系统确认 prior 与导入 prior。
- 前端：`LeaveLedgerPage` 合并区增加上传；`ChatPage` 进度卡增加 prior 选择与上传/合并动作。
- 文档：`docs/leave-ledger-clerk-guide.md` 同步对话与专页两条路径。
- 依赖：现有 `merge_ledger_rows` / sticky re-merge；导出模板结构（`build_ledger_xlsx`）作为 B 的唯一验收格式。
