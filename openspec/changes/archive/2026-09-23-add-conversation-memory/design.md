## Context

见 proposal.md。现状：`messages` 保存每轮原文与 `rewritten_query`；每轮把最近 `KB_HISTORY_TURNS` 轮历史显式塞进图状态；LangGraph 使用 `AsyncPostgresSaver`（thread_id = conversation_id）；Redis 用于检索缓存、限流与入库队列，不保存对话状态。

## Goals / Non-Goals

**Goals:** 跨天/长对话下上下文不丢；压缩不损失可审计性；会话标识稳定；Redis 可安全清空；用户能在聊天主界面看到当前会话的长期摘要；压缩路径可自观测（健康度 + 效果探针），支撑预算校准。
**Non-Goals:** 层级摘要、跨会话记忆、长期记忆的向量检索、多用户共享会话、用户编辑/清空摘要、根据观测自动改预算（自调节）、默认启用 LLM-as-judge 评摘要。

## Decisions

### D1 未压缩窗口 token 预算 + 摘要硬顶

压缩触发量的是**未压缩窗口消息的合计 token**（定义 A），不是「摘要 + 窗口」。配置：

- `KB_MEMORY_TOKEN_BUDGET`：未压缩窗口合计上限；超过则把窗口外最旧一段入队压缩。
- `KB_SUMMARY_TOKEN_CAP`：滚动摘要硬顶；生成后超限则截断或再压，防止摘要挤占上下文。
- `KB_HISTORY_TURNS`（现网默认 5）：窗口至少保留最近 N 轮未压缩原文；与预算正交。

Token 估算沿用项目启发式（中文语料约 2 字/token）。占位量级按「约 10 轮 × 估长」：`MEMORY` ~6000–8000、`SUMMARY_CAP` ~600–800；**实现先占位 + env 可调，正式默认值留到验收前用真实长会话校准**。避免只用固定轮数触发（长短问句混合时行为跳变）。

### D2 滚动摘要 + 覆盖范围

每个会话维护一条滚动摘要（`conversation_summaries`），记录 `covered_from_message_id`、`covered_to_message_id`、`content`、`token_count`、`version`；新摘要基于"旧摘要 + 新滑出的消息"生成，替换为最新版本（保留历史版本以便追溯）；写入前受 `KB_SUMMARY_TOKEN_CAP` 约束。

### D3 压缩只标记不删除

`messages` 增加 `compressed`、`token_count`、`summary_id`。压缩后原文仍在库中，只是不再进入窗口；审计、回溯、引用核对都不受影响。

### D4 三层拼接加载

会话加载顺序：长期记忆摘要 → 未压缩的最近消息 → 当前问题。查询改写与答案生成都使用该拼接结果；摘要缺失时退化为纯窗口（兼容历史会话）。

### D5 数据库为唯一事实来源

消息内容以 PostgreSQL 为准；checkpointer 只保存图运行态，不参与历史重建。避免"两套历史"不一致。Redis 仅缓存，清空后不影响会话恢复。

### D6 会话标识稳定传递

`session_id` 与 `conversation_id` 同值；前端通过 URL 与 localStorage 持久化并每次请求显式携带；服务端校验归属，不存在时返回明确错误，不静默新建会话。

### D7 压缩并发保护

同一会话的压缩加锁（Redis 锁或数据库行锁）在 **worker 内**持有，避免多标签页 / 重复入队触发重复压缩；摘要写入使用事务。聊天路径只做「超预算则入队」，不持有压缩锁。

### D8 异步压缩（主路径）

压缩不阻塞聊天 SSE：本轮改写 / 检索 / 生成与消息落库完成后即结束响应；若判定超预算，仅入队压缩任务，由后台 worker 生成滚动摘要并标记 `compressed`。新摘要通常在后续轮次加载时生效。可接受「晚一轮」窗口：连发时依赖尚未压缩的窗口原文顶住上下文。不采用同步压缩作为默认路径（避免超预算轮次额外 LLM 延迟）。

### D9 会话记忆主界面可见（只读）

长期摘要对用户可见，落在**聊天主界面**（如会话侧栏「会话记忆」卡片），而非仅管理/审计入口。展示当前版本摘要正文；无摘要时隐藏或显示空态。接口只读（随会话消息/详情一并返回最新摘要即可）。用户不可编辑或清空摘要；历史摘要版本供系统追溯，默认 UI 只展示最新版。因异步压缩，卡片可能短暂滞后，前端可在会话刷新或下次加载时更新。

### D10 压缩自观测（L1 健康度 + L2 效果探针）

沿用现有 JSON ops / `log_event` / `timed_event`，不另建观测栈。默认做人调 env，不做自动改预算。

**L1 机械指标（必做）** — 聊天与 worker 路径发出可解析事件：

| event | 关键字段 |
|-------|----------|
| `memory.budget_check` | `conversation_id`, `window_tokens`, `budget`, `over_budget` |
| `memory.compress_enqueued` | `conversation_id`, `window_tokens` |
| `memory.compress_done` | `conversation_id`, `covered_from`, `covered_to`, `summary_tokens`, `capped`, `version` |
| `memory.compress_failed` | `conversation_id`, `error`（可截断） |
| 可选 `memory.compress_lag_ms` | 入队到完成的耗时 |

用于判断：压得太勤/太懒、硬顶命中、队列滞后、超预算会话是否最终 `compress_done`。

**L2 效果探针（必做）** — 自动化 golden 剧本（pytest 或脚本）：先写入可检验实体（如型号/审批人），聊到触发压缩并等待 worker，再追问该实体；断言回答（及只读摘要 API）仍含关键实体。用于判断「压缩后事实是否还在」，支撑验收前校准 `KB_MEMORY_TOKEN_BUDGET` / `KB_SUMMARY_TOKEN_CAP`。

**不做（本变更）**：按分数自动改预算；默认 LLM 评判摘要质量（可后续抽样，非本 change 范围）。

## Risks / Trade-offs

- [摘要漂移丢失细节] → 摘要保留关键实体/编号/结论；原文不删，可回查；L2 探针回归。
- [压缩成本] → token 预算触发 + 按会话加锁 + 摘要结果缓存。
- [估算 token 有误差] → 使用保守预算与安全余量，必要时可替换为精确分词；L1 `window_tokens` 可对照手感。
- [前端丢失 session_id] → URL + localStorage 双保险，恢复失败给出明确提示。
- [异步摘要滞后] → 第 N 轮入队后第 N+1 轮可能仍读到旧摘要；靠未压缩窗口覆盖近期事实；验收与 L2 探针须等待 worker 完成再断言；主界面卡片同步可能晚一拍。
- [队列积压 / worker 宕机] → 压缩失败不影响本轮答案；可重试入队；L1 `compress_failed` / lag 告警；窗口未压缩消息仍可用。
- [用户误读摘要为完整记录] → UI 标明「会话记忆 / 压缩摘要」；完整原文仍在消息列表。
- [自观测误判] → L1 只反映机制健康；效果以 L2 实体保留为准；不根据单次失败自动改预算。

## Migration Plan

1. 建表与迁移；历史会话默认 `compressed=false`，无需回填。
2. 部署压缩 worker；配置 `KB_MEMORY_TOKEN_BUDGET` / `KB_SUMMARY_TOKEN_CAP`（先占位）并接入现有队列习惯；聊天路径仅入队；接通 L1 事件。
3. 前端：会话标识持久化 + 聊天主界面只读「会话记忆」卡片（有摘要才展示内容）。
4. 跑 L2 golden 探针 + 真实长会话，结合 L1 信号校准预算占位 → 写入正式默认值与 README。
5. 验收：清空 Redis → 重启服务 → 同 session_id 追问；摘要断言前等 worker；主界面摘要可见；L2 探针通过。

## Open Questions

- （无）预算语义与占位已定；正式默认值在验收前校准，不阻塞实现。
