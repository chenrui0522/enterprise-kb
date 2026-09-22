## Context

动机见 proposal.md。影响方案的既定事实：

- `app/core/tenant.py` 的 `tenant_dependency` 读取 `X-Tenant-ID`，缺省 `default`；所有表与 Milvus 都带
  `tenant_id`，这是做隔离的现成基础。
- `app/models/entity.py` 里没有用户/角色表；`Conversation.created_by`、`AuditEvent.actor` 写死 `local-user`。
- 前端 `frontend/src/api.js` 已用 fetch（含 SSE 流式读取），改成携带 Cookie 成本低。
- 后端目前只有一个 FastAPI 进程 + Redis 限流，没有会话存储；Redis 可用，但会话需要可审计与可吊销。
- 业务演进：电气/机械等部门围绕项目做故障/规格知识库，后续还有其他部门功能与多 Agent；需要统一 Principal，
  而不是为每个模块再造登录。

## Goals / Non-Goals

**Goals:**
- 每个请求都能确定不可伪造的 Principal：是谁、哪个租户、主部门、参与哪些项目、有哪些动作权限。
- 登录体验简单（浏览器会话），同时支持后续多部门扩展、语料数据范围与审计追溯。
- 保持检索/问答/切片等既有能力不变，只在入口处增加身份与动作授权；组织属性本期入库，检索过滤后置。

**Non-Goals:**
- 不做语料 `department/project/kind` 打标与检索可见性过滤（见 `add-corpus-access-scope`）。
- 不做企业微信 SSO、不做公网暴露与 TLS、不做多因素认证。
- 不引入完整 IAM / OPA / Casbin 策略引擎；不引入 chunk 级用户 ACL。
- 不把电气/机械拆成多个租户（部门是租户内属性）。

## Decisions

### D0 权限框架：Session AuthN + RBAC + 组织关系属性（ReBAC / ABAC-lite 的数据面）

三层分离，禁止混进同一套字段：

| 层 | 机制 | 本期 |
|---|---|---|
| 认证 AuthN | HttpOnly Cookie + 服务端会话 | 实现 |
| 动作授权 | RBAC：角色 → 权限串 → `require_permission` | 实现 |
| 数据范围 | 用户 `department_id` + `project_members`；资源标签规则 | **只建人侧属性**；规则与过滤见下一 change |

所有业务路由（含未来 Agent 工具）只依赖 Principal，不得再读可伪造请求头。

### D1 会话制认证（HttpOnly Cookie + 服务端会话），不用 localStorage JWT

浏览器会话更安全（JS 读不到令牌），SSE 流式问答天然携带 Cookie，服务端可即时吊销。会话记录存
Postgres `sessions` 表（user_id、token_hash、expires_at、created_at、last_seen_at、user_agent、ip）。

替代方案：JWT 存 localStorage。放弃原因是 XSS 风险、无法即时吊销，且 SSE 场景还要额外处理。

### D2 密码使用 argon2id 哈希，登录限流 + 失败锁定

复用现有 Redis 限流设施做登录维度限流；同一账号连续失败达到阈值后短期锁定。哈希与校验集中在一个
安全模块，便于后续替换策略。

### D3 RBAC：内置角色 + 权限字符串，接口用 `require_permission` 校验

角色：`admin`（用户/角色/部门/项目管理、审计、全部功能）、`editor`（文档上传/重试/重导）、`viewer`（问答、
查看自己的会话）、`auditor`（只读审计）。权限以字符串表示（如 `documents:write`、`chat:use`、
`audit:read`、`users:manage`、`projects:manage`），授权依赖统一注入。

**权限串是契约，角色是打包方式。** 新部门功能只新增权限串并挂到角色，不新建用户体系。
**数据范围不进权限串**（不要 `documents:read:electrical`）。

替代方案：在路由里手写 if 判断。放弃原因是散落且易漏，测试也难以覆盖。

### D4 租户来源改为登录用户，移除对 `X-Tenant-ID` 的信任

`tenant_dependency` 改为从会话用户解析租户；缺少登录态时返回 401。保留“管理员跨租户”作为后续能力，
本期不实现。租户表示公司/部署环境；部门与项目在租户之内。

### D5 归属与审计记录真实用户

`Conversation.created_by` 写登录用户 id；审计事件 `actor` 写用户名或用户 id；登录、失败、登出都写审计。
历史数据的策略：`created_by='local-user'` 的历史会话归初始管理员可见（或标记 legacy），迁移脚本记录说明。

### D6 首个管理员显式引导创建

提供引导命令（如 `python -m app.cli create-admin`）或首次启动环境变量（用户名 + 初始密码），
创建后要求修改密码；`.env.example` 只放占位与说明，不写默认口令。引导时可指定初始部门（如「管理」）。

### D7 前端登录态与权限驱动 UI

新增登录页与鉴权上下文；路由守卫拦截未登录；菜单/按钮按权限渲染；`api.js` 全部请求 `credentials: "include"`；
401 统一清除本地状态并跳登录；403 显示无权限提示而不是伪装成功。当前用户响应携带 department 与 projects，
供后续「当前项目」选择器使用（本期可不做项目切换 UI）。

### D8 测试策略：既有接口测试注入测试用户

现有路由测试（如 `tests/test_documents_api.py`）通过依赖覆盖注入已认证用户，避免每个用例都走真实登录；
新增用例覆盖登录成功/失败/锁定、401/403、会话过期、会话归属、部门与项目成员读写。

### D9 Principal 与组织模型

请求级 Principal：

```
user_id, tenant_id, department_id, project_ids[], permissions[]
```

数据表：

- `departments`：租户内部门（电气、机械、人事…）
- `users.department_id`：每个用户一个主部门（必填；管理员引导时指定）
- `projects`：租户内项目
- `project_members(user_id, project_id)`：项目参与关系（ReBAC）

管理员可维护部门、项目与成员；普通用户只读自己的部门与项目列表。
本期**不**根据这些属性过滤文档检索；过滤矩阵见 `add-corpus-access-scope`。

替代方案：把部门做成独立租户。放弃原因：同一项目内跨部门故障协作、后续多模块共享身份都会变难。

### D10 与后续语料范围 / 多 Agent 的边界

- 语料侧：`department_id` / `project_id` / `kind` 打在文档与 chunk 上，检索 `expr` 应用可见性规则 → 下一 change。
- 多 Agent：Agent 工具必须携带 `on_behalf_of` 当前 Principal，不得比用户看得更多；本期不实现 Agent。

## Risks / Trade-offs

- [移除 `X-Tenant-ID` 会破坏现有脚本/前端调用] → 前后端同版本升级；`README` 记录新的登录流程。
- [历史会话/审计没有真实 owner] → 迁移时归属初始管理员并标记 legacy，不做伪造归属。
- [Cookie + CORS 跨源配置容易出错] → 开发期精确配置允许来源并开启 `allow_credentials`；同源部署作为推荐形态。
- [登录接口成为攻击面] → 限流 + 失败锁定 + 审计 + argon2 成本参数可调。
- [组织属性先建、过滤后接] → 短期检索仍可能过宽；用独立 change 接过滤，并用组织样例模拟验证矩阵后再实现。
- [一人多部门] → 本期只支持一个主部门；跨部门协作靠项目成员 + 后续 fault/general 共享规则。

## Migration Plan

1. 迁移新增表与种子角色/权限；种子至少含示例部门占位（或空表由管理员创建）；历史会话与审计标记 legacy
   并归属初始管理员。
2. 部署后先创建管理员与部门，再创建首批用户并分配角色、部门、项目成员。
3. 前端升级到带登录页的版本，旧的无鉴权调用将收到 401。
4. 回滚：保留 `.env` 中的开关可临时放行（仅限迁移期），或回退到上一版本镜像/提交。

## 用组织架构模拟可行性（检查清单）

实现前可用纸面/表格模拟，不必写代码：

1. 列出部门（如电气、机械）与项目（如 P-12、P-18）。
2. 为若干员工填：主部门、参与项目、角色（admin/editor/viewer）。
3. 为若干文档草稿填：部门、项目（可空）、kind（spec/fault/general）——对照下一 change 的可见性矩阵。
4. 抽查：同项目跨部门看故障应可见、看对方规格应不可见；未参与项目应全不可见；部门公共库仅同部门可见。
5. 若矩阵与现场不符，先改 `add-corpus-access-scope` 的规则，再改实现；身份侧 Principal 字段通常仍够用。

## Open Questions

- 是否需要“同一租户内用户只能看自己会话”之外的共享会话能力（本期按“只看自己”实现）。
- 企业微信 SSO 与通讯录同步的时间点（依赖可信域名方案，见后续 change）。
- 项目成员是否需要角色（负责人/只读成员）；本期成员关系无角色，动作权限仍走全局 RBAC。
