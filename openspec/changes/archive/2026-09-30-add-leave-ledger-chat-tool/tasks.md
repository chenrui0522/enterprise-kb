## 1. 注册与路由

- [x] 1.1 在 `registry` 增加 `leave_ledger` 工具与 `leave_ledger:read|write` 权限过滤，验证 `/chat/tools` 有权限可见、无权限不可见
- [x] 1.2 扩展 `route_turn`：显式工具 / 强调休匹配 / 弱确认 / 与人员投入冲突时的澄清，验证相关单测覆盖强/弱/显式路径

## 2. 编排与 tool-action

- [x] 2.1 实现 leave-ledger 对话编排：创建/挂接 job、附件 `classify_source`（含糊则询问角色）、`add_source_file`、进度写入 `tool_state`，验证分次上传后同一 `job_id` 且进度卡角色状态正确
- [x] 2.2 将 `/chat/tool-action` 按工具分发，支持接受缺失、复核决议、确认、导出、作废（写操作需 `leave_ledger:write` 且二次确认），验证确认前不落 confirmed、导出与 REST 口径一致
- [x] 2.3 在 `chat` 流式路径于 RAG 前认领调休工具回合，验证认领后不走知识库臆造台账数字

## 3. 前端卡片与验收

- [x] 3.1 ChatPage 工具下拉增加「调休台账」；渲染进度/告警/确认/导出卡片并调用 tool-action，验证会话内补齐四源（或接受缺失）后可确认并下载 xlsx
- [x] 3.2 确认 `/leave-ledger` 独立页仍可用；补或更新 chat-tools / leave-ledger 相关测试与 README 一句对话入口说明，验证与实现一致
