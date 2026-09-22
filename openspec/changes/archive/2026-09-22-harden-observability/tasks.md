## 1. 日志底座与请求关联

- [x] 1.1 实现 JSON Formatter、contextvars 上下文 Filter，以及 `KB_LOG_LEVEL` / `KB_LOG_JSON` / `KB_LOG_QUERY_PREVIEW_CHARS` 配置，验证默认输出为单行可解析 JSON
- [x] 1.2 实现 API `X-Request-ID` 中间件（复用或生成、注入上下文、响应头回传）与 HTTP 起止事件（含 status、duration_ms），验证无客户端头时响应头与日志 ID 一致
- [x] 1.3 Worker 入库任务入口注入 `job_id`（及等价 request 关联）上下文，验证同一次 job 的多条日志共享同一任务标识
- [x] 1.4 增加脱敏约定的单元测试（口令/Cookie 不得出现在格式化输出中；问句超长被截断），验证相关测试通过

## 2. 关键路径阶段日志

- [x] 2.1 在问答图节点（rewrite / need_retrieval / retrieve / generate 或 direct_answer）记录带 `event` 与 `duration_ms` 的阶段日志，验证一次成功检索问答可按 request_id 串起各阶段
- [x] 2.2 在 LLM / embed / rerank 调用边界记录 `provider.call` 事件（类别、耗时、成败），验证重排或生成失败时有对应失败事件
- [x] 2.3 在入库 pipeline 关键步骤（triage / convert / chunk / embed / index / done）记录阶段日志，验证失败任务可按 job_id 过滤出阶段序列
- [x] 2.4 检索服务在有意义的失败路径保留 warning/error 并带上上下文 ID，验证缓存损坏等现有告警仍带 request/job 上下文（若处于请求内）

## 3. 健康检查

- [x] 3.1 扩展 `/healthz`：分项探测 postgres / redis / milvus / model_service（短超时），按 design 区分 unavailable 与 degraded，验证 Milvus 单挂为 degraded、Postgres 挂为不可用语义
- [x] 3.2 为健康检查补充测试或脚本冒烟说明，验证各分项字段存在且超时不会拖死接口

## 4. 审计覆盖与查询 API

- [x] 4.1 为组织/岗位/绑岗换岗减岗/密级变更/项目成员变更等写操作补 `write_audit`，验证对应操作后 `audit_events` 有真实 actor 与动作名
- [x] 4.2 扩展 `GET /api/v1/audit/events`：动作、操作者、时间范围筛选与分页/限额，验证无 `audit:read` 返回 403、有权限仅见本租户
- [x] 4.3 补充审计 API 与关键写操作审计的自动化测试，验证 `uv run pytest -q` 相关用例通过

## 5. 管理端审计页与文档

- [x] 5.1 前端 Admin 增加「审计」页签（`audit:read`）：列表展示时间/操作者/动作/资源/摘要，支持基本筛选，验证无权限用户看不到入口
- [x] 5.2 更新 `.env.example` 与 README 可观测小节（request_id 用法、日志字段、审计页、healthz 语义），验证说明与实现一致

## 6. 验收

- [x] 6.1 端到端：登录 → 绑岗/上传/问答 → 用 request_id grep 容器日志见阶段链；审计页能筛到对应写操作；人为停 Milvus 后 healthz 呈降级
- [x] 6.2 运行 `uv run pytest -q`，验证全部通过
