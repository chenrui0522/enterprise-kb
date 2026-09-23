## Context

See proposal.md. Today: `Conversation.title` defaults to「新对话」; FE `createConversation()` pre-creates empty sessions; stream only sets `title=message[:30]` when creating without `conversation_id`. No PATCH title API; no title-source tracking. Memory compress already uses Redis queue + worker — reuse that pattern for title polish.

## Goals / Non-Goals

**Goals:**

- Immediate rule title on first user turn when title is still default.
- Async LLM polish that never blocks chat and never overwrites user edits.
- Manual rename API + FE edit affordance.
- Clear `title_source` so polish/auto logic is deterministic.

**Non-Goals:**

- Regenerating titles on every turn or from full history after polish.
- Multi-language title UX settings.
- Admin bulk rename tools (optional one-shot backfill of default titles is enough).

## Decisions

### D1 — `title_source` column

Add `conversations.title_source` with values: `default` | `auto` | `user` (string, server default `default`).

- Create → `default`, title「新对话」
- Rule or polish write → `auto`
- PATCH by user → `user`

Auto/polish only when `title_source != "user"` and (for rule) `title_source == "default"` (or title still equals default placeholder). Polish may update when `title_source == "auto"`.

Alternative: infer from title ==「新对话」 only — rejected; hand-rename back to「新对话」或规则与润色冲突时不可靠。

### D2 — Rule title helper

Pure function e.g. `derive_rule_title(message: str, filename: str | None) -> str`:

- Prefer stripped message; if empty/whitespace, use filename stem.
- Collapse whitespace; truncate to ~30 Unicode chars (consistent with existing create path).
- Fallback:「新对话」only if both empty (should not happen on a real turn).

Apply inside chat stream after resolving conversation, before/alongside saving user message, when `title_source == "default"`. Also apply when creating conversation inline without prior id (set source `auto` immediately).

### D3 — Async polish via Redis + worker

Mirror memory compress:

- After rule title commit, enqueue `{conversation_id, tenant_id, rule_title, enqueued_at}`.
- Worker calls existing chat LLM with a short prompt: 8–15 字中文对话标题, no quotes/punctuation spam; validate length; if `title_source == "auto"` and title still equals `rule_title` (or any auto title), set polished title.
- If user PATCHed meantime → skip.

Alternative: inline asyncio.create_task in API process — rejected for reliability on Windows single-worker and consistency with compress.

### D4 — Manual rename API

`PATCH /api/v1/conversations/{id}` body `{ "title": "..." }` (owner + `chat:use`). Trim; reject empty; set `title_source=user`.

FE: double-click or edit icon on sidebar row / header; optimistic update then PATCH.

### D5 — Backfill

Optional one-shot or lazy: list conversations with `title_source=default` (or title「新对话」) that have ≥1 user message → set rule title from first user message, `title_source=auto`. Do not enqueue polish for all historical rows by default (cost); polish only new traffic unless explicitly requested.

## Risks / Trade-offs

- [Worker offline → no polish] → Rule title remains; acceptable.
- [Race: polish vs PATCH] → Check `title_source == "auto"` at write time; user wins.
- [LLM returns long/junk] → Hard max length + strip quotes; discard if empty.
- [Migration on existing rows] → Backfill `title_source`: title==「新对话」→`default`, else →`user` (conservative: treat unknown custom as user so polish won't overwrite).

## Migration Plan

1. Alembic: add `title_source` with default `default`; backfill heuristic above.
2. Rule naming in stream + create path.
3. Queue + worker polish job.
4. PATCH + FE edit.
5. Optional CLI/script or startup-once backfill for default titles with messages.

## Open Questions

（无 — 规则先上 + 异步润色 + 手改已确认）
