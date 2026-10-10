## Why

合并上月已确认台账与本月结果时，加班日按「同键以上月为准」原样保留，但出差段会并集扩展。上月在**出差段外**按双证据计入的连休日加班（如端午放假 6/20–21），合并后落入并集出差段，却未按「段内仅法定假日本体日」重审，导致正式导出出现「放假三天加了三天调休」的错误（应为法定本体一日，如仅 6/19）。

## What Changes

- 段级合并在出差并集与加班 prior-wins 之后，**MUST** 再按并集后的项目实际出差段重审加班日：段内且非配置法定假日本体日的加班日不得保留额度（从合并结果中去除）。
- 合并路径加载与单次计算相同的法定假日配置表，用于判定本体日并刷新 `holiday` 标注。
- 文员操作说明补充：合并后段内非法定日加班会被去掉；已确认错误快照需作废或重建任务后重新合并。
- 不改变单次 `compute_ledger` 的 Rule 2/3；不改变「同键加班以上月为准」在**仍合法**场景下的行为。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `leave-ledger`: 扩展「段级合并」要求——出差并集后须重审加班日，使段内仅法定假日本体日可保留加班可调休。

## Impact

- 代码：`app/leave_ledger/merge.py`（合并后过滤）、`app/leave_ledger/service.py`（传入 holidays）；单测 `tests/test_leave_ledger_merge.py`。
- 配置：继续使用 `KB_LEAVE_LEDGER_HOLIDAYS_PATH` / `data/leave_ledger_holidays_*.txt`（只列法定本体日）。
- API 契约不变；已确认历史快照不自动重算，须重新合并并确认。
- 文档：`docs/leave-ledger-clerk-guide.md`。
