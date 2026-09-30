## 1. Roster correction core

- [x] 1.1 在 `app/staffing/roster.py`（或同级新模块）实现 `correct_names_against_roster`：精确命中保留、唯一前缀/后缀（长度差 ≤2）自动纠名、否则 unresolved；无花名册返回 `roster_unavailable`。用纯单元测试覆盖命中 / 唯一纠名 / 歧义 / 空册。
- [x] 1.2 在导入路径（`create_import_batch` / 解析落库前）调用校正，改写 `parse_result` 行内姓名，并把 `roster_name_corrected`（已决议）与 `roster_name_unresolved` / `roster_unavailable` 并入 `warnings`。用集成测试：夹具日报 + 迷你花名册，断言批次 warnings 与待确认姓名。

## 2. Confirm / review gate

- [x] 2.1 扩展 `_open_warning_codes`（及确认前校验）：未决议的 `roster_name_unresolved` / `roster_unavailable` 阻断确认；仅有已自动纠名记录时允许确认。用测试断言确认 400/拒绝与放行两种路径。
- [x] 2.2 决议 API/payload：对 unresolved 支持 `select_roster_name`、`rename`（允许不在册并记 `acknowledged_off_roster`）、`discard`；决议后改写待确认行或剔除 token。用测试覆盖三种决议后再确认的入库结果。

## 3. Frontend review UX

- [x] 3.1 `StaffingPage` / 对话复核区展示花名册告警：候选全名列表、选定/改名/丢弃操作；无花名册时展示配置提示。手工点选三种决议后确认成功，或确认按钮在未决议时禁用/报错。

## 4. Regression & ops

- [x] 4.1 保留导出部门/职务花名册查找行为不变；跑既有 `test_staffing_collision` / parse 测试并修因告警集合变化导致的断言。
- [x] 4.2 确认默认 `data/staffing_roster.xlsx`（或 `KB_STAFFING_ROSTER_PATH`）在本地/部署说明中可找到；缺文件时导入出现 `roster_unavailable` 而非静默通过（用一次手动或测试验证）。
