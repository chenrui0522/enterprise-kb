## ADDED Requirements

### Requirement: 人员投入须落在项目管理部组织子树
系统 SHALL 在既有人员投入动作权限与项目授权校验之外，要求操作者组织范围落在 `project_mgmt` 子树（含项目管理部、项目一部、项目二部），或具备 `users:manage` 以绕过组织闸。不满足组织范围的主体 MUST NOT 导入、复核、确认、作废、汇总或导出人员投入数据，MUST NOT 经对话工具进入人员投入流程。

#### Scenario: 非项目管理部不可导入
- **WHEN** 具备 `staffing:write` 但不在 `project_mgmt` 子树且无 `users:manage` 的用户上传项目日报
- **THEN** 系统拒绝导入

#### Scenario: 项目二部可汇总
- **WHEN** 具备 `staffing:read` 且岗位在 `project_div_2` 的用户查询已授权项目汇总
- **THEN** 系统按既有项目范围规则返回汇总
