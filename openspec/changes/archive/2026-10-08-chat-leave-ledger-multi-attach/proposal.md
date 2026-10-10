## Why

文员在对话里做调休台账时，企微四源往往一次备齐，但聊天附件槽与发消息接口只接受**单个** `attachment_id`，只能分四轮上传；独立页已支持多选。需要让对话在选中「调休台账」时也能一轮附上多份 xlsx，减少重复操作。

## What Changes

- 对话作曲器支持多选附件（仍限 xlsx/xls/pdf 既有规则），发送时可携带多份已上传附件。
- 聊天请求在保留既有 `attachment_id` 的同时，增加可选的多附件字段；调休编排在同一轮内按序分类并写入同一 job。
- 同一轮中能自动分类的来源先入库；角色含糊的文件仍须用户指定后再计入（可只卡住含糊的那一份，不阻断已收录的）。
- **仍允许**分次上传；独立调休页与人员投入等多附件行为本期不改。
- 文员操作说明补充：对话亦可一次多选四源。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `chat-tools`: 扩展调休对话工作流——同一轮可提交多份来源附件，并明确多附件时的分类/pending 行为。

## Impact

- 前端：`ChatPage` 附件状态与 file input；`api.js` 发消息载荷。
- 后端：`ChatRequest` schema、`chat` 路由加载附件、`leave_ledger_orchestrator` 一轮多源；其它工具若收到多附件，本期仅取首个或忽略多余（在 design 中约定），避免误伤人员投入。
- 兼容：旧客户端只传 `attachment_id` 仍可用。
- 文档：`docs/leave-ledger-clerk-guide.md`。
