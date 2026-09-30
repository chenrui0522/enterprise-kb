## Why

每月调休台账任务目前彼此独立：本月四源重算不会接上月已确认快照。运营源导出窗口常与上月重叠，若只看本月结果会丢上月已决议额度与跨月出差并段后的 30 天计块；需要把「上月定稿 + 本月新算」合成最新台账后再确认导出。

## What Changes

- 支持将**用户显式选择的已确认 job**快照与**当前未确认 job**的计算结果做**段级合并**，写回本月 `compute_result`，再走既有告警决议 / 确认 / 导出。
- 合并规则：出差段并集后重跑间隔合并并重算 30 天块额度；加班按 `(姓名, 日期)`、调休按 `(姓名, start, end)` 去重；同键冲突**以上月已确认快照优先**。
- 提供列出本租户已确认任务的只读入口，供选择 prior job。
- 合并仅允许在本月任务非 `confirmed` / `voided` 且已有计算结果时执行；审计记录 `merged_from_job_id`。
- 合并后丢弃本月告警中键已在上月快照出现的加班类阻塞项（上月优先已覆盖）。

## Capabilities

### New Capabilities

- （无）

### Modified Capabilities

- `leave-ledger`: 增加「选已确认 prior job → 段级合并写回本月 → 再确认」行为及已确认任务列表；合并去重与上月优先口径成为可验收需求。

## Impact

- 后端：`app/leave_ledger/`（合并纯函数 + `service` 写回）、`app/api/routers/leave_ledger.py`、schemas；可能需 `GET /leave-ledger/jobs`（按 status 过滤）。
- 前端：`LeaveLedgerPage.jsx`（及可选对话卡）增加选择已确认 prior 并触发合并。
- 不改变既有四源上传与单任务计算规则；不改变一人多行导出模板契约（合并后仍经 confirm 再 export）。
- 无 **BREAKING** API 删除；新增 merge / list 端点。
