## Context

动机见 proposal.md。影响方案的既定事实：

- `app/core/tenant.py` 的 `tenant_dependency` 读取 `X-Tenant-ID`，缺省 `default`；所有表与 Milvus 都带
  `tenant_id`，这是做隔离的现成基础。
- `app/models/entity.py` 里没有用户/角色表；`Conversation.created_by`、`AuditEvent.actor` 写死 `local-user`。
- 前端 `frontend/src/api.js` 已用 fetch（含 SSE 流式读取），改成携带 Cookie 成本低。
- 后端目前只有一个 FastAPI 进程 + Redis 限流，没有会话存储；Redis 可用，但会话需要可审计与可吊销。

## Goals / Non-Goals

**Goals:**
- 每个请求都能确定“是谁、属于哪个租户、有哪些权限”，并且这个身份不可被客户端伪造。
- 登录体验简单（浏览器会话），同时支持后续多部门扩展与审计追溯。
- 保持检索/问答/切片等既有能力不变，只在入口处增加身份与授权。

**Non-Goals:**
- 不做部门/知识空间的细粒度数据权限（下一 change）。
- 不做企业微信 SSO、不做公网暴露与 TLS、不做多因素认证。
- 不引入完整 IAM/权限表达式引擎，先用内置角色 + 权限字符串。

## Decisions

### D1 会话制认证（HttpOnly Cookie + 服务端会话），不用 localStorage JWT

浏览器会话更安全（JS 读不到令牌），SSE 流式问答天然携带 Cookie，服务端可即时吊销。会话记录存
Postgres `sessions` 表（user_id、token_hash、expires_at、created_at、last_seen_at、user_agent、ip）。

替代方案：JWT 存 localStorage。放弃原因是 XSS 风险、无法即时吊销，且 SSE 场景还要额外处理。

### D2 密码使用 argon2id 哈希，登录限流 + 失败锁定

复用现有 Redis 限流设施做登录维度限流；同一账号连续失败达到阈值后短期锁定。哈希与校验集中在一个
安全模块，便于后续替换策略。

### D3 RBAC：内置角色 + 权限字符串，接口用 `require_permission` 校验

角色：`admin`（用户/角色管理、审计、全部功能）、`editor`（文档上传/重试/重导）、`viewer`（问答、
查看自己的会话）、`auditor`（只读审计）。权限以字符串表示（如 `documents:write`、`chat:use`、
`audit:read`、`users:manage`），授权依赖统一注入。

替代方案：在路由里手写 if 判断。放弃原因是散落且易漏，测试也难以覆盖。

### D4 租户来源改为登录用户，移除对 `X-Tenant-ID` 的信任

`tenant_dependency` 改为从会话用户解析租户；缺少登录态时返回 401。保留“管理员跨租户”作为后续能力，
本期不实现。

### D5 归属与审计记录真实用户

`Conversation.created_by` 写登录用户 id；审计事件 `actor` 写用户名或用户 id；登录、失败、登出都写审计。
历史数据的策略：`created_by='local-user'` 的历史会话归初始管理员可见（或标记 legacy），迁移脚本记录说明。

### D6 首个管理员显式引导创建

提供引导命令（如 `python -m app.cli create-admin`）或首次启动环境变量（用户名 + 初始密码），
创建后要求修改密码；`.env.example` 只放占位与说明，不写默认口令。

### D7 前端登录态与权限驱动 UI

新增登录页与鉴权上下文；路由守卫拦截未登录；菜单/按钮按权限渲染；`api.js` 全部请求 `credentials: "include"`；
401 统一清除本地状态并跳登录；403 显示无权限提示而不是伪装成功。

### D8 测试策略：既有接口测试注入测试用户

现有路由测试（如 `tests/test_documents_api.py`）通过依赖覆盖注入已认证用户，避免每个用例都走真实登录；
新增用例覆盖登录成功/失败/锁定、401/403、会话过期、会话归属。

## Risks / Trade-offs

- [移除 `X-Tenant-ID` 会破坏现有脚本/前端调用] → 前后端同版本升级；`README` 记录新的登录流程。
- [历史会话/审计没有真实 owner] → 迁移时归属初始管理员并标记 legacy，不做伪造归属。
- [Cookie + CORS 跨源配置容易出错] → 开发期精确配置允许来源并开启 `allow_credentials`；同源部署作为推荐形态。
- [登录接口成为攻击面] → 限流 + 失败锁定 + 审计 + argon2 成本参数可调。
- [权限模型过早复杂化] → 本期只用内置角色与权限字符串，不做表达式引擎与数据级 ACL。

## Migration Plan

1. 迁移新增表与种子角色/权限；历史会话与审计标记 legacy 并归属初始管理员。
2. 部署后先创建管理员，再创建首批用户并分配角色。
3. 前端升级到带登录页的版本，旧的无鉴权调用将收到 401。
4. 回滚：保留 `.env` 中的开关可临时放行（仅限迁移期），或回退到上一版本镜像/提交。

## Open Questions

- 是否需要“同一租户内用户只能看自己会话”之外的共享会话能力（本期按“只看自己”实现）。
- 企业微信 SSO 与通讯录同步的时间点（依赖可信域名方案，见后续 change）。