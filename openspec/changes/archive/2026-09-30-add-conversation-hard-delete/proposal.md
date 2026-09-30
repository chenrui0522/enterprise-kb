## Why

问答侧栏已支持打开与改名历史会话，但用户无法清理无用对话，列表会越积越乱。需要本人可硬删除会话，并在删除前二次确认，避免误触。

## What Changes

- 授权用户可硬删除自己拥有的会话；删除前 MUST 经确认框确认。
- 删除会话时一并移除该会话的消息、引用与长期摘要；列表中不再出现该会话。
- 若删除的是当前打开的会话，前端 MUST 切换到空态或其它可用会话。
- 人员投入 / 调休台账等业务任务 MUST NOT 因会话删除而被删除（仅丢掉会话内 `tool_state` 引用）。
- 新增 `DELETE /api/v1/conversations/{id}`（或等价）接口。

## Capabilities

### New Capabilities

- （无）

### Modified Capabilities

- `multi-turn-chat`: 增加「用户可硬删除本人历史会话（确认后）」的要求与场景。

## Impact

- API：`app/api/routers/chat.py` 及会话服务层；可能需清理 LangGraph checkpoint（尽力而为）。
- 前端：`ChatPage.jsx` 侧栏删除按钮 + 确认；`api.js` 增加 delete 调用。
- 数据：依赖现有 `messages` / `conversation_summaries` 等对 `conversations` 的 `ON DELETE CASCADE`；聊天附件磁盘文件可顺带清理或留待后续。
- 权限：与改名一致，本人 + `chat:use`。
