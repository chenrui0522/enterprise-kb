## Why

当前系统没有任何认证：没有用户/角色模型，`tenant_id` 直接取自请求头 `X-Tenant-ID`（客户端可随意伪造），
审计里的 `actor` 与会话 `created_by` 都写死为 `local-user`。这既无法支撑“公司局域网内多人使用”，
也无法作为多部门 Agent 平台的身份地基。

业务上，初版以电气/机械等业务部门的项目知识库为起点（故障问答、设计规格、知识检索），后续会扩展到其他
部门功能与多 Agent。权限必须提前定成可扩展框架：**Session 认证 + RBAC（动作）+ 部门/项目关系（数据范围属性）**，
而不是把部门拆成多个租户，也不是把角色写进向量库。

按演进路线，v1.5 的第一块地基就是身份与组织属性；语料检索过滤见独立 change `add-corpus-access-scope`。

## What Changes

- 新增 `identity-access` 能力：用户、角色、权限、部门、项目成员、会话登录、受保护接口的动作授权与归属审计。
- **权限框架**：Session AuthN + RBAC（角色 → 权限串 → `require_permission`）+ ReBAC/ABAC-lite 所需的组织属性
  （`department_id`、`project_ids[]` 进入 Principal）。**数据范围规则与检索过滤不在本期实现**，只把属性建好。
- **BREAKING**：受保护接口需要登录；不再信任请求头 `X-Tenant-ID`，租户一律来自登录用户。
- 认证方式：用户名 + 密码（argon2id 哈希），登录后签发服务端会话，浏览器通过 HttpOnly Cookie 携带；
  登出即时失效；会话有有效期。
- 授权方式：内置角色 admin / editor / viewer / auditor 与权限字符串；权限串是契约，角色是打包方式；
  **数据范围不写入权限串**（禁止 `documents:read:electrical:P-12` 这类组合爆炸）。
- 组织模型：每个用户有一个主部门；项目与项目成员多对多；登录/当前用户接口返回 Principal
  （user、tenant、department、projects、permissions）。
- 登录保护：登录接口限流与连续失败锁定；登录成功、失败、登出写入审计，`actor` 记录真实用户。
- 归属修正：会话（conversations）归属登录用户，用户只能看到自己的会话；审计事件记录真实 actor。
- 首个管理员通过显式引导命令/环境变量创建，代码中不存在默认口令。
- 前端：新增登录页、鉴权上下文、路由守卫、按权限显示功能项、401 统一跳转登录；所有请求携带 Cookie。
- 非目标（各自独立 change）：语料标签与检索可见性过滤（`add-corpus-access-scope`）、Agent 注册表与路由、
  企业微信 SSO、完整 IAM/OPA 策略引擎、chunk 级用户 ACL、局域网发布与端口收敛、工具调用与动作执行。

## Capabilities

### New Capabilities
- `identity-access`: 账号、会话登录、角色与动作权限、主部门与项目成员、受保护操作的授权校验，
  以及操作与审计的真实用户归属；请求级 Principal 供后续数据范围与多 Agent 复用。

### Modified Capabilities
- 无。授权与归属属于新能力引入的行为；现有 capabilities 的存量需求不改写。

## Impact

- 数据：新增 users / roles / permissions / user_roles / sessions / departments / projects /
  project_members 表与 Alembic 迁移；历史数据标记为 legacy 并归属初始管理员。
- 代码：新增安全模块与会话/用户服务；`app/core/tenant.py` 改为从登录用户解析租户；文档、问答、审计、
  系统路由全部接入授权依赖；`app/chat/service.py` 的会话语义改为按用户归属。
- 接口：新增登录/登出/当前用户/用户与角色管理/部门与项目成员管理接口；既有接口在未登录时返回 401。
- 前端：登录页、鉴权上下文、路由守卫、权限驱动 UI、请求凭据与 401 处理。
- 测试：新增认证/授权/登录保护/组织属性测试；既有接口测试注入测试用户。
- 依赖：新增密码哈希依赖（argon2）。
