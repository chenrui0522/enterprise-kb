## Why

身份层（`add-auth-and-rbac`）会给出「谁、哪个部门、参与哪些项目」，但语料侧仍只有 `tenant_id`：
同租户内电气与机械、不同项目的设计规格与故障经验会混在检索结果里。业务初版围绕项目做部门知识库
（故障问答、设计规格、知识检索），需要在入库与检索统一落实数据范围，否则登录后仍会串库。

## What Changes

- 新增 `corpus-access` 能力：文档与 chunk 携带 `department_id`、`project_id`（可空=部门公共库）、
  `kind ∈ {spec, fault, general}`；检索与列表按 Principal 的组织属性应用固定可见性规则。
- 可见性规则（已确认）：
  - 部门公共库（`project_id` 空）：仅同部门可见
  - 项目规格（`kind=spec`）：项目成员 **且** 同部门
  - 项目故障/通识（`kind=fault|general` 且挂了项目）：项目成员即可（跨部门共享）
  - 未参与的项目：不可见
- 上传/重导时写入并校验标签：不得标到用户未参与的项目；规格不得标成外部门资料。
- 检索统一经 `SearchService` / Milvus `expr` 过滤；禁止在召回后再靠“碰巧没排进 top_k”充当权限。
- 依赖身份侧 Principal（部门 + 项目成员）；本 change **不**实现登录或 RBAC 动作权限。
- 非目标：chunk/章节级 ACL、每文档用户 ACL 列表、OPA/Casbin、按部门拆租户、Agent 注册表。

## Capabilities

### New Capabilities
- `corpus-access`: 语料资源的部门/项目/用途标签、入库校验、以及基于 Principal 的检索与文档列表可见性。

### Modified Capabilities
- `knowledge-qa`: 问答检索 MUST 只命中当前用户可见的语料；不得返回不可见文档的引用内容。
- `document-ingestion`: 上传与版本 MUST 持久化部门/项目/用途标签，并在入库时继承到 chunk。

## Impact

- 数据：`documents` / `document_versions`（及必要时父块表）增加部门、项目、kind；Milvus chunk schema
  增加对应标量字段；存量语料默认策略（如 public 部门公共或迁移期标记）需在 design 中明确。
- 代码：`pipeline` 写入标签；`build_filter_expr` / `SearchService` 注入 scope；文档上传 API 接受并校验标签；
  文档列表按可见性过滤。
- 运维：集合字段变更可能需要重建/重导（现有 `reindex.py`）。
- 依赖：`add-auth-and-rbac` 提供 Principal；可先用测试注入 Principal 实现与验收。
