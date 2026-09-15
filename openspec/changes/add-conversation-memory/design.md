## Context

见 proposal.md。现状：`messages` 保存每轮原文与 `rewritten_query`；每轮把最近 `KB_HISTORY_TURNS` 轮历史显式塞进图状态；LangGraph 使用 `AsyncPostgresSaver`（thread_id = conversation_id）；Redis 用于检索缓存、限流与入库队列，不保存对话状态。

## Goals / Non-Goals

**Goals:** 跨天/长对话下上下文不丢；压缩不损失可审计性；会话标识稳定；Redis 可安全清空。
**Non-Goals:** 层级摘要、跨会话记忆、长期记忆的向量检索、多用户共享会话。

## Decisions

### D1 以 token 预算触发压缩

按会话累计 token 估算（字符数/模型分词启发式），超过预算时压缩"窗口外最旧的一段"；窗口始终保留最近 N 轮未压缩消息。避免用固定轮数导致长短问句混合时行为跳变。

### D2 滚动摘要 + 覆盖范围

每个会话维护一条滚动摘要（`conversation_summaries`），记录 `covered_from_message_id`、`covered_to_message_id`、`content`、`token_count`、`version`；新摘要基于"旧摘要 + 新滑出的消息"生成，替换为最新版本（保留历史版本以便追溯）。

### D3 压缩只标记不删除

`messages` 增加 `compressed`、`token_count`、`summary_id`。压缩后原文仍在库中，只是不再进入窗口；审计、回溯、引用核对都不受影响。

### D4 三层拼接加载

会话加载顺序：长期记忆摘要 → 未压缩的最近消息 → 当前问题。查询改写与答案生成都使用该拼接结果；摘要缺失时退化为纯窗口（兼容历史会话）。

### D5 数据库为唯一事实来源

消息内容以 PostgreSQL 为准；checkpointer 只保存图运行态，不参与历史重建。避免"两套历史"不一致。Redis 仅缓存，清空后不影响会话恢复。

### D6 会话标识稳定传递

`session_id` 与 `conversation_id` 同值；前端通过 URL 与 localStorage 持久化并每次请求显式携带；服务端校验归属，不存在时返回明确错误，不静默新建会话。

### D7 压缩并发保护

同一会话的压缩加锁（Redis 锁或数据库行锁），避免多标签页并发触发重复压缩；摘要写入使用事务。

## Risks / Trade-offs

- [摘要漂移丢失细节] → 摘要保留关键实体/编号/结论；原文不删，可回查。
- [压缩成本] → token 阈值触发 + 按会话加锁 + 摘要结果缓存。
- [估算 token 有误差] → 使用保守预算与安全余量，必要时可替换为精确分词。
- [前端丢失 session_id] → URL + localStorage 双保险，恢复失败给出明确提示。

## Migration Plan

1. 建表与迁移；历史会话默认 `compressed=false`，无需回填。
2. 部署压缩服务（可配置开关与预算），先只对新会话生效。
3. 前端升级会话标识持久化。
4. 验收：清空 Redis → 重启服务 → 同 session_id 追问，验证上下文正确。

## Open Questions

- token 预算的默认值（需按模型上下文与成本确定）。
- 摘要是否需要展示给用户（当前设计为对用户透明）。
