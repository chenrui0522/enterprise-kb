## Context

See proposal.md for motivation. Conversations already support list + `PATCH` title (`chat.py` / `ChatPage` sidebar). There is no delete path. ORM FKs already cascade messages and summaries when a conversation row is deleted. `tool_state` may reference staffing/leave jobs; those domain tables must stay. LangGraph checkpoints (if enabled) are keyed by conversation id separately from app tables. Chat attachments live under disk paths by attachment id.

## Goals / Non-Goals

**Goals:**

- `DELETE /api/v1/conversations/{id}` for owner + `chat:use`.
- Sidebar delete control with `window.confirm` (or equivalent) before calling API.
- After delete: refresh list; if deleted id was active, clear local conversation state (same as losing the session).

**Non-Goals:**

- Soft-delete / recycle bin / admin purge of others' chats.
- Deleting staffing batches or leave-ledger jobs.
- Guaranteed cleanup of every orphaned attachment blob (best-effort OK; full GC later).
- Bulk multi-select delete (V1 single-item only).

## Decisions

### D1 Hard delete via SQLAlchemy delete of Conversation

- Load conversation by id + tenant; require `created_by == principal.user_id` (same ownership as rename).
- `session.delete(conversation)` + commit; rely on DB CASCADE for messages/summaries/citations.
- 404 if missing or not owned (do not leak existence across users — match existing get patterns if they already collapse to 404).

Alternative: soft `deleted_at`. Rejected per product choice.

### D2 Checkpoint cleanup best-effort

- If app has checkpointer with delete/thread API, invoke for this conversation id after DB delete; failures log only, do not fail the user delete.

### D3 UI

- Sidebar item: 「删除」 next to 「改名」; `confirm("确认删除该对话？删除后不可恢复。")` then `DELETE`.
- On success: remove from `conversations`; if `conversationId === deleted`, call existing clear/new-session path (`applyConversationId(null)` or equivalent).

### D4 Audit / ops

- Emit existing-style audit or `log_event` for `conversation.delete` if chat rename/create already audits; otherwise structured log is enough for V1. Prefer matching rename's audit pattern if present.

## Risks / Trade-offs

- [Risk] User deletes chat but still needs leave-ledger job → Mitigation: jobs untouched; user opens `/leave-ledger` or new chat.
- [Risk] Orphan attachment files → Mitigation: accept for V1; optional best-effort delete of attachment ids found in message meta.
- [Trade-off] confirm() vs modal → use confirm for consistency with leave-ledger void/confirm in chat.

## Migration Plan

- No schema migration.
- Deploy API + frontend together.
- Rollback: remove DELETE route and sidebar button; data already deleted cannot be restored.
