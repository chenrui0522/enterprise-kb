## Context

See proposal.md for motivation. Backend `GET /api/v1/audit/events` already accepts `action`, `actor`, `since`, `until`, `offset`, and `limit` (clamped 1–500) and returns `{ total, offset, limit, items }`. Frontend `listAuditEvents` already forwards those params; `AuditPanel` hardcodes `limit: 100`, `offset: 0` and ignores time range. Spec already required Admin filters to align with the query API; this change closes that UI gap.

## Goals / Non-Goals

**Goals:**
- Wire Admin audit UI to time range + offset pagination without changing API contracts.
- Time UX: presets (today / last 7 days / last 30 days / all) plus expandable custom datetime range.
- Keep page size modest (default 100; options 50/100/200) within existing API max.

**Non-Goals:**
- New endpoints, export, composite indexes, retention, write-path changes, ops log changes.
- Cursor-based pagination (offset remains sufficient at current scale).

## Decisions

1. **Frontend-only change**
   - Rationale: API and client helper already support required params; lowest risk to close the browse gap.
   - Alternative: Raise API `limit` or add cursor — deferred; offset + time filters address “can’t see older” without schema work.

2. **Time presets computed client-side as ISO `since`/`until`**
   - “今天”: local calendar day start → now (or end of day).
   - “近 7/30 天”: `since = now - N days`, omit or set `until` to now.
   - “全部”: omit both.
   - Custom: send both when set; validate `since <= until` before request.
   - Rationale: matches existing query params; no server clock/preset API.
   - Alternative: server-side presets — unnecessary complexity.

3. **Pagination UX**
   - Track `offset` in panel state; prev disabled at 0; next disabled when `offset + items.length >= total`.
   - Changing action/actor/time preset/custom range/page size resets `offset` to 0 then reloads.
   - Show “第 {offset+1}–{offset+items.length} 条，共 {total}” (empty list: 共 0).
   - Alternative: numbered page buttons — overkill for v1; prev/next is enough.

4. **Custom range expand**
   - Selecting “自定义” reveals two datetime inputs; other presets hide them and clear custom values on switch away (or ignore them when not in custom mode).
   - Prefer `datetime-local` for simplicity within Admin stack; convert to ISO with timezone offset for the API.

5. **No backend changes this round**
   - If list latency appears under large `total`, follow-up can add `(tenant_id, created_at DESC)` index — out of scope here.

## Risks / Trade-offs

- [Offset deep pages slow / inconsistent under high write rate] → Mitigate with time presets so users rarely deep-page; document that results are best-effort snapshots.
- [Client timezone vs server UTC skew on “今天”] → Compute bounds in local time then send ISO with offset; API already parses timezone-aware strings.
- [Invalid custom range] → Client-side validate before fetch; surface short error via existing `onError`.
- [Large `detail` JSON still noisy] → Out of scope; browsing older events is the priority.

## Migration Plan

- Deploy frontend only; no DB migration.
- Rollback: revert Admin panel; API unchanged.

## Open Questions

（无 — 交互与范围已在探索中确认）
