## Context

See proposal.md for motivation. Today ChatPage is RAG-only (streamChat, no attachments/tools). Staffing is a separate REST module (`/api/v1/staffing/*`) plus a bare `/staffing` page. Permissions `staffing:read`/`write` already exist and sync on API startup. Product decisions locked in explore: T3 in-chat tools, auto-trigger A, routing M3, keep `/staffing` (P1), confirm before commit/void.

## Goals / Non-Goals

**Goals:**

- Composer tool dropdown + xlsx attachment UX aligned with main chat styling.
- Orchestrate existing staffing services from the chat turn pipeline without duplicating parse/confirm logic.
- Persist enough session-scoped tool state for follow-ups in the same conversation.

**Non-Goals:**

- Generic multi-vendor plugin marketplace or OpenAI-style remote tools.
- Rewriting staffing domain rules.
- Removing top-nav `/staffing` or redesigning global IA (L2).
- Full LLM function-calling for all future tools in v1 (staffing may use rules + thin LLM assist only when weak).

## Decisions

### D1 — Tool registry (frontend + backend allowlist)

Small registry: `{ id: "staffing", label: "人员投入", permissions: ["staffing:read","staffing:write"] }`. Frontend filters by `user.permissions`. Backend rejects tool invocation without permission even if client spoofs.

Alternatives: hardcode only in UI — rejected (easy to bypass).

### D2 — Chat attachment upload path

Add `POST /api/v1/chat/attachments` (or reuse staffing upload only when staffing claimed) storing file in existing object storage with conversation_id + message draft id. For staffing-strong path, may call `staffing_service.create_import_batch` directly with the bytes (same as staffing imports). Prefer **one chat attachment API** then tool reads storage_key — keeps composer generic for future tools.

### D3 — Turn routing (M3) before RAG

In chat request handler (before or instead of ChatGraph RAG):

1. If `active_tool == staffing` → staffing orchestrator.
2. Else score rules (xlsx + filename/keywords) → strong / weak / none.
3. Strong → staffing; weak → return clarification message (no RAG invent); none → existing graph.

Staffing orchestrator steps map 1:1 to existing service: import → review → confirm → summary / void. UI sends structured `tool_action` (e.g. `confirm_import`, `ack_warnings`, `void_person`) for button clicks.

### D4 — Conversation tool state

Store JSON on conversation (new column or side table): `{ active_tool, staffing: { batch_id, project_id } }`. Cleared on new chat or tool switch. Avoid stuffing large parse_result into message text; messages hold human summaries + card payloads.

### D5 — Card protocol in messages

Assistant messages may include `ui` / `card` JSON (batch status, warnings, summary table, confirm buttons). ChatPage renders cards; unknown card types degrade to text. No separate websocket.

### D6 — Keep `/staffing` page

No deletion. Optional later restyle; out of critical path for this change.

## Risks / Trade-offs

- [False auto-trigger into import] → M3 weak path asks; confirm required before DB facts.
- [ChatGraph vs tool bifurcation complexity] → Keep router thin; staffing logic stays in staffing package.
- [Attachment size / encrypted xlsx] → Reuse staffing reject messages; surface in chat bubble.
- [State lost across devices] → Persist tool state server-side on conversation.

## Migration Plan

1. Ship registry + composer UI (dropdown visible by permission).
2. Add attachment + tool invoke API; wire staffing orchestrator.
3. Card rendering + confirm/void actions.
4. Regression: normal RAG chat unchanged when no tool/attachment.
5. Rollback: feature-flag tool dropdown off; staffing page still works.

## Open Questions

- Exact keyword/filename rule list for「强匹配」(can tune in implement without changing specs).
- Whether weak-match clarification uses LLM once or fixed copy (default fixed copy).
