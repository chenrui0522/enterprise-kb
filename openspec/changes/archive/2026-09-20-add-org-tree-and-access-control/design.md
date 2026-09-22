## Context

动机见 proposal.md。需求见 `specs/identity-access` 与 `specs/corpus-access`。

影响方案的既定事实：

- `app/core/tenant.py` 的 `tenant_dependency` 读 `X-Tenant-ID`，缺省 `default`；Postgres 与 Milvus 均有 `tenant_id`。
- `app/models/entity.py` 无用户/组织表；`Conversation.created_by`、`AuditEvent.actor` 写死 `local-user`。
- 检索已有 `build_filter_expr(tenant_id, filters)` 与 `SearchService` 缓存；缓存键目前不含身份范围。
- 前端 `frontend/src/api.js` 用 fetch（含 SSE）；改 Cookie 成本低。尚无登录页。
- Redis 已用于限流；会话需要可吊销，适合进 Postgres。
- 未实现的 `add-auth-and-rbac` / `add-corpus-access-scope` 按扁平部门与 `kind=spec|fault|general` 写就，不得按原文落地。

## Goals / Non-Goals

**Goals:**

- 每个请求得到不可伪造的 Principal（用户、租户、地点、岗位组织本级、编制本级、专业并集、密级、项目、动作权限）。
- 可见性用同一套谓词覆盖文档列表与 Milvus 召回；身份与语料过滤在同一 change 内可验收（袁工/马工矩阵）。
- 认证与动作 RBAC 沿用会话 + 权限串，但人只绑岗位。

**Non-Goals:**

- 不上 Casbin/OPA；策略硬编码为规格中的公式。
- 不做文档级/chunk 级 ACL、企业微信 SSO、多租户管理 UI、汇报线子树视野。
- 不把 `doc_type` 当权限字段；不保留旧 change 的 `kind` 权限开关。

## Decisions

### D0 三层分离

| 层 | 机制 | 存储 |
|---|---|---|
| 认证 | HttpOnly Cookie + `sessions` | 人 |
| 动作 | 岗位 → 角色 → 权限串 → `require_permission` | 角色 |
| 范围 | 岗位本级 ∪ 编制本级 ∪ 项目∩专业；部门路径过密级 | Principal + 文档标签 |

业务路由只依赖 Principal，禁止再读 `X-Tenant-ID`。

### D1 会话 Cookie，不用 localStorage JWT

与旧身份设计相同：SSE 自然带 Cookie，服务端可吊销。会话表：`user_id, token_hash, expires_at, last_seen_at, user_agent, ip`。

替代：JWT。放弃：无法即时吊销、XSS、SSE 额外处理。

### D2 argon2id + 登录限流锁定

复用 Redis 限流；连续失败锁定账号。哈希集中在安全模块。

### D3 权限只挂角色，人只绑岗位

无 `user_roles` 主路径；无 `position_permissions`。`user_positions` 一人可多行；`position_roles`；`role_permissions`。

内置角色种子：`admin`（用户/组织/岗位/项目管理、审计）、`editor`（文档写）、`reader`（读 + 问答）、`auditor`（只读审计）。管理员岗位关联 `admin`，**不**默认打开全库语料。

替代：人直接绑角色。放弃：与「先绑岗位」冲突。替代：权限挂岗位。放弃：已否决。

### D4 组织树一张表，视野精确本级

`org_units(id, tenant_id, parent_id, type, code, name, status)`。`type` 含 company / office / center / dept / committee。委员会可建节点，demo 不往上挂文档。

可见性比较 `doc.org_unit_id == unit_id`，不算祖先或子孙。总经办助理因此不会看到各中心。

替代：闭包表/物化路径做子树。放弃：规格明确本级。

### D5 岗位必挂组织节点；管理边被岗位吸收

`positions.org_unit_id` 必填，`(tenant_id, org_unit_id, code)` 唯一。`domain` 可空（空=不向项目贡献专业）。

「归软件部管理」= 岗在软件部，不再单建 `manager` 关系。

### D6 编制独立

`user_org_relations(user_id, org_unit_id, relation='establishment')`。仅用于无该部岗位的家园（袁工-研发中心）。马工两岗已覆盖的节点不必再写编制。

### D7 地点在人上

`users.site` ∈ `{taiyuan, shuozhou, suzhou}`。组织节点可有可选 `default_site` 仅作展示，授权不读地点。一个租户。

### D8 密级只在用户上，岗变动表单必选

`users.clearance` ∈ `{general, core}`。未绑岗时为 `general`。创建/更新/删除 `user_positions` 的 API 必须带 `clearance`；缺省 422。系统不计算 `max(岗位默认)`，岗位无密级字段。岗不变时允许单独 PATCH 密级。

替代：岗变动自动打回一般。放弃：用户要求表单必选、系统不猜。

### D9 项目授权 = `project_members`

对象是项目，不是文档。项目路径：`project_id ∈ principal.project_ids AND domain ∈ principal.domains`，**不过密级**。部门/编制路径过密级。

`principal.domains` = 各岗位 `domain` 去空后的并集。

替代：文档级 grant。放弃：一般以项目形式授权。

### D10 可见性编译进召回 expr

```
tenant_id == user.tenant
AND (
  (org_unit_id IN org_unit_ids AND classification <= clearance)
  OR
  (project_id IN project_ids AND domain IN domains AND project_id != "")
)
```

Postgres 文档列表用同一谓词。`SearchService` 缓存键 MUST 含 org_unit_ids、domains、clearance、project_ids，避免串缓存。

权威标签在 `document_versions`；chunk 入库继承；Milvus 加标量字段。存量：运维指定默认组织节点，`classification=general`，`project_id` 空，`domain` 空（仅部门路径、须密级够）；扩 schema 后 `reindex`。

替代：召回后再滤。放弃：不可见 chunk 占 top_n。

### D11 上传校验

`POST /documents`：`org_unit_id`、可选 `project_id`、`domain`、`classification`。项目非空则专业必填且 ∈ 用户专业并集，且用户已授该项目；否则 `org_unit_id` 必须 ∈ 岗位或编制本级。写权限仍走 RBAC。

### D12 Principal

```
user_id, tenant_id, site, clearance,
org_unit_ids[], domains[], project_ids[], permissions[]
```

`org_unit_ids` = 岗位节点 ∪ 编制节点。

### D13 种子与 demo 人物

单租户种子公司「奥特莱物物流科技有限公司」，组织树按总公司架构图（总经办及八中心与下属部）。地点不建成分公司根节点。

| 账号 | 地点 | 岗位 | 编制 | 密级 | 项目 |
|---|---|---|---|---|---|
| 引导管理员 | 太原 | 总经办/系统管理员 → admin | 无 | 表单指定 | 无 |
| 袁工 | 苏州 | 软件部/软件工程师 domain=软件 → reader | 研发中心 | demo 默认一般 | 可授示例项目 |
| 马工 | 太原 | 总经办/总经理助理 domain=空；销售部/大客户经理 domain=销售 | 无 | 表单指定 | 可授示例项目 |

样例文档覆盖：软件部一般/核心、研发中心一般/核心、电气标准化研发部、生产中心、采购部、示例项目内软件核心与电气一般。测试按 specs 场景断言。

### D14 前端

登录页；`credentials: "include"`；401 跳登录；403 明示无权限。管理员：组织树、岗位、绑岗（密级必选）、项目授权、用户密级。菜单按权限串渲染。当前用户展示岗位/密级/项目，本期不做「切换身份」。

### D15 与旧 change 的关系

本 change 取代 `add-auth-and-rbac` 与 `add-corpus-access-scope`。实现时不要创建 `users.department_id` 或 `kind=spec|fault|general` 权限字段。README 注明那两份规划作废。

## Risks / Trade-offs

- [移除 `X-Tenant-ID` 破坏旧脚本] → 同版本升级；README 写登录流程。
- [历史会话无 owner] → legacy 归初始管理员。
- [Cookie CORS] → 开发期精确允许来源 + `allow_credentials`；推荐同源。
- [岗位本级使总经办看不到各中心] → 符合规格；高管要看全库需另开策略（非本期）。
- [项目不过密级] → 核心只在该项目专业刀内打开，避免提全身密级；须防止把部门库误标成项目。
- [Milvus 加字段] → 新集合或重建，走现有 `reindex.py`。
- [空专业文档挂在部门] → 部门路径不看专业，允许；挂项目则拒绝无专业。
- [图上部分部门名称像素不清] → 种子用可改正的 code/name；不影响模型。

## Migration Plan

1. Alembic：组织/身份/会话/项目成员表 + 文档列；种子角色权限、专业枚举约束、奥特莱物组织树与 demo 岗。
2. 引导创建管理员（绑管理员岗 + 必选密级）。
3. API 与前端上线；未登录 401。
4. 存量文档打默认组织标签并 `reindex`。
5. 回滚：开关临时放行仅限迁移窗，或回退镜像；新列可保留。

## Open Questions

- 共享会话是否需要（本期仍只看自己的 conversations）。
- 项目负责人是否单独成岗位，还是任意 `projects:manage` 均可授人进项目（拟定：有 `projects:manage` 即可）。
