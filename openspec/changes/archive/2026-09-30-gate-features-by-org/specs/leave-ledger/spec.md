## Purpose

支持运营上传太原调休台账四源并计算确认导出；本期增量约束仅运营管理中心组织范围可使用该功能。

## ADDED Requirements

### Requirement: 调休台账须落在运营管理中心组织子树
系统 SHALL 在既有 `leave_ledger:read` / `leave_ledger:write` 校验之外，要求操作者组织范围落在 `ops` 子树（运营管理中心及其下属计划运营部、人力资源管理部、行政部、朔州人事行政），或具备 `users:manage` 以绕过组织闸。不满足组织范围的主体 MUST NOT 创建/上传/复核/确认/作废/导出调休台账任务，MUST NOT 经对话工具认领调休台账。

#### Scenario: 非运营中心不可创建任务
- **WHEN** 具备 `leave_ledger:write` 但不在 `ops` 子树且无 `users:manage` 的用户创建调休台账任务
- **THEN** 系统拒绝创建

#### Scenario: 计划运营部可确认
- **WHEN** 具备 `leave_ledger:write` 且岗位在 `ops_planning` 的用户在告警已决议后确认任务
- **THEN** 系统允许确认（仍受既有告警阻塞规则约束）
