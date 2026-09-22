## Context

动机见 proposal.md。行为契约见 `specs/ops-observability` 与 `specs/identity-access` 增量。

影响方案的既定事实：

- `app/core/logging.py` 为 stdlib StreamHandler + 文本 Formatter；`get_logger(name)` 散落在 api / chat / retrieval / ingestion / worker。
- API 无请求中间件；无 `request_id` / contextvars；问答图与 provider 几乎无阶段耗时日志。
- `audit_events` 表已存在（tenant、actor、action、resource_*、detail、created_at）；`GET /api/v1/audit/events` 仅 limit；Admin 无审计页；`auditor` 角色有 `audit:read` 但无处可用。
- 已知写审计：登录成功/失败/锁定/登出、文档上传与重试、`chat.completion`。组织/岗位/绑岗/项目授权等写操作多数未审计。
- `/healthz` 仅探测 Redis；Compose 另有 postgres / milvus / model-service。
- 部署形态：Docker Compose 单机，日志以容器 stdout 采集为主；不自建 ELK。

## Goals / Non-Goals

**Goals:**

- 一次请求（或一次入库 job）可用同一 `request_id` / `job_id` 在 stdout 中串起全链路阶段与错误。
- 运维日志为机器可解析的 JSON 行；关键阶段带 `duration_ms`。
- 审计员能在管理端按时间/动作/操作者筛选查看本租户审计事件。
- 健康检查能分项报告核心依赖是否可用。

**Non-Goals:**

- 不上 LangSmith、OpenTelemetry Collector、Prometheus 全量指标栈、自建告警。
- 不把完整用户问句 / 文档正文 / 口令写入运维日志；审计 `detail` 不存口令明文。
- 不在本 change 做反馈分析、长对话记忆或 SSO。

## Decisions

### D1 JSON 结构化日志 + contextvars，不引入重型日志框架

在 `setup_logging` 中改为 JSON Formatter（一行一事件），字段至少包括：`ts`、`level`、`logger`、`msg`、`request_id`（若有）、以及可选的 `tenant_id` / `user_id` / `conversation_id` / `document_id` / `job_id` / `duration_ms` / `event`。

用 `contextvars` 在中间件 / worker 入口注入上下文，业务代码继续 `get_logger(...).info(...)`，由 Filter 自动合并上下文，避免每个调用点手传 ID。

替代：structlog / loguru。放弃：新增依赖与改造面大，stdlib 足够支撑 Compose stdout 验收。

### D2 请求关联：`X-Request-ID` 中间件

API：若客户端已带合法 `X-Request-ID` 则复用，否则生成 UUID；写入 contextvars；在响应头回传。Worker：每个入库 job 使用 `job_id` 作为关联键（可另生成 `request_id` 等同值），保证 pipeline 日志可串。

替代：仅依赖 uvicorn access log。放弃：access log 不含业务阶段与业务 ID。

### D3 阶段事件命名约定（运维日志，非审计表）

统一 `event` 字段，例如：

| 域 | 事件示例 |
|---|---|
| HTTP | `http.request_start` / `http.request_end`（含 method、path、status、duration_ms） |
| 问答 | `chat.rewrite` / `chat.judge` / `chat.retrieve` / `chat.generate` / `chat.done`（或失败） |
| 入库 | `ingest.triage` / `ingest.convert` / `ingest.chunk` / `ingest.embed` / `ingest.index` / `ingest.done` |
| 依赖 | `health.check` 分项结果（也可只走 healthz 响应，不必全打日志） |

计时用简单 `time.perf_counter()` 包裹；失败时同事件带 `ok=false` 与错误摘要（截断）。

Provider（LLM / embed / rerank）在调用边界打 `provider.call`（name、duration_ms、ok），兑现早期设计「埋点位」而不接外网 trace。

### D4 脱敏规则（硬约定）

运维日志 MUST NOT 包含：密码、Cookie / Session token、Authorization 头、文档全文、切片全文。问句与改写结果最多记录长度与哈希或截断前 N 字符（配置，默认偏短）。异常栈可保留，但需避免把请求体整段打进 `exc_info` 自定义字段。

### D5 审计：复用 `audit_events`，补覆盖 + 查询 API + Admin 页

不新建审计表。补齐关键写操作的 `write_audit`（至少：组织/岗位/用户绑岗与密级变更/项目成员变更/文档删除若存在/会话相关已有则保持）。动作名保持 `domain.verb` 风格（如 `org.create`、`auth.login`）。

扩展 `GET /api/v1/audit/events`：支持 `action`、`actor`、时间范围、`cursor`/`offset` + `limit`（上限不变）；仍强制租户隔离与 `audit:read`。

前端 `AdminPage` 新增「审计」页签（`audit:read`），表格展示时间、操作者、动作、资源、摘要；只读。

替代：把审计打进运维日志仓再查。放弃：验收需要系统内可查；与权限模型已有 `audit:read` 对齐。

### D6 健康检查分项，不因单依赖失败而误报进程存活（可选策略）

`GET /healthz` 返回：

```json
{
  "status": "ok" | "degraded" | "unavailable",
  "checks": {
    "postgres": "ok|fail",
    "redis": "ok|fail",
    "milvus": "ok|fail",
    "model_service": "ok|fail"
  }
}
```

- 进程能响应但核心依赖挂：`degraded` 或 `unavailable`（设计取：postgres 失败 → `unavailable` + 非 200；仅 milvus/model 失败 → `degraded` + 200，便于编排区分「进程死」与「能力降级」）。
- 各检查带短超时，避免 healthz 本身拖死。

替代：Kubernetes 式拆 liveness/readiness。本期单机 Compose，一个端点 + status 枚举足够；若后续拆分再加路径。

### D7 配置

新增（前缀 `KB_`）：`LOG_LEVEL`、`LOG_JSON`（默认 true）、`LOG_QUERY_PREVIEW_CHARS`（默认如 64）、健康检查超时秒数。写入 `.env.example` 与 README「可观测」小节（如何用 request_id grep、审计页入口）。

## Risks / Trade-offs

- [JSON 日志体积变大] → 控制预览长度；http 结束事件不记 body；DEBUG 默认关闭。
- [阶段日志漏打导致「以为没做」] → tasks 按路径列必打事件；单测或集成断言关键 event 字段存在。
- [审计写入失败拖垮主路径] → 审计写失败打运维 error 日志，主路径是否失败在实现时选「尽力而为」：登录类审计失败可记录但仍返回业务结果；配置类写操作保持与现网一致（失败则事务回滚若同事务）。
- [healthz 探测 model-service 过慢] → 严格超时；失败记 fail 不重试。
- [敏感信息误入日志] → 代码评审清单 + 单测禁止 password/cookie 键出现在 formatter 输出样例。

## Migration Plan

1. 先合并日志底座与中间件（行为向后兼容：仍 stdout）。
2. 再补阶段日志与 healthz。
3. 再扩展审计 API 与 Admin 页、补写操作审计。
4. 回滚：回退部署即可；无强制数据迁移。若仅增加审计索引可保留。

## Open Questions

- 无（分页用 offset 或 cursor 在实现时按现有 API 风格二选一，不影响规格语义）。
