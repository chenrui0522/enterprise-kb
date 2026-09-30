## 1. Rules: OT resolutions + segment payload

- [x] 1.1 扩展 `compute_ledger`：接入加班决议 map（exclude/accept_half/accept_full），验证单测覆盖缺打卡按满日→+1、半日→+0.5、排除→0
- [x] 1.2 每人结果输出 `travel_segments` / `ot_days` / `leave_segments`（及既有合计字段），验证单测断言段列表与合计一致
- [x] 1.3 `service._recompute` 从 `resolved_warnings` 派生决议并传入规则引擎，验证 review 后 `ot_comp_days` 随决议变化

## 2. Multi-row export

- [x] 2.1 重写 `build_ledger_xlsx` 为双行表头 A–R、人块多行、合并与黄底合计列，验证导出单测检查表头文案、合并单元格与样例数值
- [x] 2.2 确认仅 `credit > 0` 的加班日写入导出，验证排除日后 xlsx 无该日行
- [x] 2.3 更新 README 中调休导出说明（一人多行 / BREAKING），验证文档与实现列名一致

## 3. Frontend resolution UI

- [x] 3.1 `LeaveLedgerPage` 与对话 `LeaveLedgerJobCard` 增加「按半日记」，验证三档均可提交且复核后预览额度正确
- [x] 3.2 跑 `tests/test_leave_ledger.py`（及既有 chat leave-ledger 相关测）全部通过，验证无回归
