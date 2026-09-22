## Context

See proposal.md - Why。身份侧 Principal（部门、项目成员）由 `add-auth-and-rbac` 提供。

当前语料路径：

- Postgres `documents` / `document_versions` 与 Milvus chunk 仅有 `tenant_id` 与切片语义字段（`doc_type` 等）。
- `doc_type`（faq/policy/sop/…）只决定怎么切，不表示电气/机械或项目。
- `build_filter_expr(tenant_id, filters)` 已支持标量 `expr` 过滤；父子分块设计曾预留「部门」类过滤但未落地字段。
- 存量约千页级语料，已有 `reindex.py` 可重建索引。

## Goals / Non-Goals

**Goals:**
- 文档与 chunk 统一带上 `department_id` / `project_id` / `kind`，检索与列表强制可见性矩阵。
- 过滤发生在召回 `expr`，与 RBAC 动作权限解耦；所有读语料入口（含未来 Agent 工具）共用同一 scope 函数。

**Non-Goals:**
- 不实现登录/角色（依赖身份 change）。
- 不做 chunk 级或用户 ACL 列表；不上 OPA/Casbin。
- 不改变 `doc_type` 切片策略语义。

## Decisions

### D1 标签挂在文档版本，chunk 入库时继承

权威数据在 Postgres 文档/版本行；Milvus 存冗余标量以便 `expr`。版本替换时旧 chunk 删除/失效，新 chunk
带新标签。父块若仅存 Postgres，列表/展开时同样按文档可见性校验。

替代：仅 Postgres 打标、召回后再滤。放弃原因：不可见 chunk 仍占 top_n，有效召回被挤占。

### D2 kind 三值：spec / fault / general

对应业务：设计规格、故障经验、通识。可见性规则按 kind 分支；不把电气/机械编码进 kind。

### D3 可见性编译为 Milvus 布尔表达式

由 `resolve_corpus_scope(principal) -> expr`（或等价 filter 结构）生成，大致逻辑：

```
(project_id == "" AND department_id == user.dept)
OR
(kind == "spec" AND project_id IN user.projects AND department_id == user.dept)
OR
(kind IN ["fault","general"] AND project_id IN user.projects AND project_id != "")
```

与现有 `tenant_id == ...` AND 组合。文档列表用同一谓词查 Postgres。

### D4 上传 API 扩展字段并做校验

`POST /documents` 增加 department（可默认用户主部门）、project_id（可选）、kind。
校验：project 非空 ⇒ 成员；kind=spec ⇒ department == user.department。
无 `documents:write` 仍由 RBAC 拦截（身份 change）。

### D5 存量迁移

迁移列默认：`kind=general`，`project_id` 空，`department_id` 指向种子「共享/未分类」或要求运维指定默认部门。
重导后 chunk 才带齐字段；未重导前检索表达式需兼容缺字段（或强制先 reindex）。推荐：扩 schema 后跑一次
`reindex`，并在 README 写明。

### D6 与身份 change 的实施顺序

可先完成身份（含组织属性），再上本 change；测试可用依赖注入伪造 Principal。
若本 change 先行，必须有可注入的 department/projects，否则无法验收可见性。

## Risks / Trade-offs

- [Milvus 集合加字段] → 新集合或重建；用现有 reindex 流程，窗口期只读或停写。
- [存量未分类语料过宽或过窄] → 迁移默认偏保守（公共库 + 指定部门）并提供批量改标工具/SQL 说明。
- [一人一主部门] → 跨部门规格仍不可见（符合已确认规则）；接口规格若需双方可见，应用 `general` 或挂双份/共享部门策略（业务约定，不在本期自动复制）。
- [过滤与缓存键] → `SearchService` 缓存键必须包含 scope（部门+项目集合），避免串缓存。

## Migration Plan

1. DB 迁移加列；Milvus schema 升级或新 collection。
2. 部署 API：上传写标签；检索接 scope（身份就绪后）。
3. 跑 reindex；抽查可见性矩阵用例。
4. 回滚：回退 API 与集合名；数据列可保留。

## 组织架构模拟检查清单

实现前用公司真实/虚构组织表验证规则（与身份 design 清单衔接）：

1. 部门 × 项目 × 人员（主部门、成员关系）。
2. 文档样例覆盖：各部门公共 fault；各项目×部门的 spec；项目内 fault/general。
3. 对每个角色人物走一遍四条可见性规则，记录期望命中集合。
4. 若发现「联合设计必须互看的接口规格」被挡，先调整业务约定（例如该类文档 kind=general 或独立 shared 部门），再改规格——避免实现期临时开洞。

## Open Questions

无（已拍板：上传 API **必填** `kind`；存量迁移的默认部门仅作运维归类，不对全体用户开放为“人人可见旁路”。）
