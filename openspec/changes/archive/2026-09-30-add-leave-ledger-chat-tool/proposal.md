## Why

调休台账已有独立页与 `leave_ledger` 服务，但业务主路径是「在对话里分次丢企微导出」。人员投入已验证对话工具壳；调休提案曾把聊天入口列为后续。现在要把同一套「工具认领 → 会话内工作流 → 卡片确认」接到调休台账，且支持会话内补齐四源，而不是强制一次丢齐。

## What Changes

- 问答工具下拉增加「调休台账」（需 `leave_ledger:read` 或 `leave_ledger:write`）；显式选中后本会话优先走调休工作流。
- 支持未显式选择时，凭附件 + 话术（调休/出差/加班/请假/打卡等）强匹配直达或弱匹配先确认；规则优先、含糊则确认。
- 同一会话内按 **B 形态** 分次补齐四源：创建/挂接 job → 每份附件自动分类角色（含糊则问）→ `add_source` 刷新进度卡 → 缺源可「接受缺失」→ 告警复核 → 二次确认 → 导出模板形 xlsx。
- 复用现有 `leave_ledger.service`（create/add/review/confirm/void/export）与权限；确认/作废经 `/chat/tool-action`，MUST NOT 仅靠自由文本确认写库。
- **保留** `/leave-ledger` 独立页；不改计算规则与四源解析口径。
- 非目标：改规则引擎、企微回写、通用 LLM function-calling 平台、去掉独立页、人员投入行为回归变更。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `chat-tools`: 扩展工具注册与路由，纳入「调休台账」；支持会话内分次补齐四源、进度/复核/确认/导出卡片呈现；独立调休页继续可用。

## Impact

- 后端：`app/chat/tools/registry.py`、`router.py`、新 leave-ledger orchestrator（或等价）、`chat.py` 认领分支与 `tool-action` 分发；业务调用 `app/leave_ledger/service.py`。
- 前端：`ChatPage` 工具项、进度/告警/确认/导出卡片；附件仍走现有 chat attachments（xlsx 为主）。
- 权限：现有 `leave_ledger:*`；审计/ops 沿用 leave_ledger 既有事件。
- 规格：仅改 `chat-tools`；`knowledge-qa` / `multi-turn-chat` 已对「已注册工具」泛化表述，本期不强制改 delta（实现时遵守既有「工具认领不臆造事实」与「会话承载工具上下文」）。
