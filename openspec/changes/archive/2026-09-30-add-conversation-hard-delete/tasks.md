## 1. API

- [x] 1.1 实现 `DELETE /api/v1/conversations/{id}`（本人 + `chat:use`，级联删消息/摘要），验证单测：本人可删、他人/不存在 404、删后列表与 messages 不可再取
- [x] 1.2 尽力清理该会话 LangGraph checkpoint（失败仅打日志），验证有 checkpointer 时删除不因清理失败而 5xx

## 2. Frontend

- [x] 2.1 `api.js` 增加删除会话调用；侧栏增加「删除」+ 确认框，验证取消不请求、确认后列表移除
- [x] 2.2 删除当前会话时清空本地会话态，验证界面离开该会话内容

## 3. Docs / regression

- [x] 3.1 README 会话 API 列表补充 DELETE 一句，验证与实现路径一致
- [x] 3.2 跑相关 chat/conversation 测试通过，验证无回归
