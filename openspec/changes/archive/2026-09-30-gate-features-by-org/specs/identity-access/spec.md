## ADDED Requirements

### Requirement: 部门专属业务功能双闸
系统 SHALL 对声明为部门专属的业务功能在服务端同时校验：**动作权限**与**组织范围**。组织范围 MUST 以当前主体岗位及编制所属组织是否与功能允许的组织子树相交判定（含子节点）。仅有动作权限但组织不在允许子树内的主体 MUST 被拒绝（403），且对话工具 MUST NOT 向其认领或暴露该功能。持有管理员用户管理权限（`users:manage`）的主体 MUST 绕过组织范围闸，仍须满足该功能所需的动作权限。前端入口显隐 MUST 与上述规则一致，且 MUST NOT 作为唯一安全边界。

本期部门专属映射：
- 人员投入（`staffing:*`）：允许组织子树根为 `project_mgmt`（项目管理部及其下属项目一/二部）。
- 调休台账（`leave_ledger:*`）：允许组织子树根为 `ops`（运营管理中心及其下属各部门）。

#### Scenario: 有权但错部门被拒
- **WHEN** 用户具备 `staffing:write` 但其岗位/编制组织均不在 `project_mgmt` 子树内，且不具备 `users:manage`
- **THEN** 系统拒绝人员投入写操作并返回 403，且不向其认领人员投入对话工具

#### Scenario: 项目管理部子树可过闸
- **WHEN** 用户具备 `staffing:read` 且岗位挂在 `project_div_1`（项目一部）
- **THEN** 系统允许其人员投入只读操作

#### Scenario: 运营管理中心子树可过闸
- **WHEN** 用户具备 `leave_ledger:write` 且岗位挂在 `ops_hr`（人力资源管理部）
- **THEN** 系统允许其调休台账写操作

#### Scenario: 管理员绕过组织闸
- **WHEN** 用户具备 `users:manage` 与 `leave_ledger:write`，但其组织不在 `ops` 子树
- **THEN** 系统仍允许其调休台账写操作
