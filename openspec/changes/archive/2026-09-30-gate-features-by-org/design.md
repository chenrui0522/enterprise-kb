## Context

See proposal.md for motivation. Today staffing/leave-ledger routers and chat tools only call `require_permission(staffing:*|leave_ledger:*)`. `Principal` already exposes `org_unit_ids` (position + establishment) and `permissions`. Org codes live in `org_seed.ORG_SEED_NODES` (`project_mgmt` / `project_div_*`, `ops` / `ops_*`). Admin is not a Principal field; default admin role uniquely includes `users:manage`.

## Goals / Non-Goals

**Goals:**

- Shared helper: permission + org-subtree (or admin bypass) for the two features.
- Enforce on API, chat tool claim/route, and UI visibility.
- Stable allowlist by org **code** roots with descendant closure.

**Non-Goals:**

- Removing `staffing:*` / `leave_ledger:*` from editor/reader default packs (optional follow-up).
- Encoding org into permission strings.
- WeCom sync of membership (positions already drive org_unit_ids).
- Per-project ACL changes for staffing beyond existing project membership checks.

## Decisions

### D1 Dual-gate helper, not new permission strings

- Add e.g. `principal_can_use_feature(principal, feature)` or `require_permission_in_orgs(perm, root_codes=...)`.
- Feature allowlist config (code roots):
  - `staffing` → `{"project_mgmt"}`
  - `leave_ledger` → `{"ops"}`
- Resolve root codes → set of org **ids** for the tenant (cache per request or small memo), then intersect `principal.org_unit_ids`.
- Bypass when `users:manage` in permissions.
- Still require the specific read/write permission for the endpoint.

Alternative: strip perms from editor and only assign custom roles. Rejected as sole mechanism—ops wants org-based; people move orgs without role surgery.

### D2 Subtree closure

- Build children map from `OrgUnit` rows (or seed parent links) and DFS/BFS from each root code.
- Include the root node itself.
- Establishment org ids count the same as position org ids (already unioned on Principal).

### D3 Wire-up surfaces

- FastAPI: wrap staffing + leave_ledger routes (read and write) with the dual gate (dependency factory).
- Chat: `registry` / `router` eligibility and orchestrator write actions use the same helper (not only `PERM_* in permissions`).
- Frontend: hide nav/pages/tool options when dual gate fails; prefer `/me` exposing booleans `can_staffing` / `can_leave_ledger` computed server-side to avoid duplicating subtree logic in JS. If `/me` already returns `org_unit_ids` + codes, frontend may mirror—but server remains authoritative.

### D4 Admin signal

- Bypass org check iff `users:manage` present.
- Document that custom roles granting `users:manage` also bypass; acceptable for this tenant.

## Risks / Trade-offs

- [Risk] Multi-position users in both trees get both features → Mitigation: intentional (intersection with either allowlist).
- [Risk] Stale org id cache if units reparent mid-process → Mitigation: resolve per request from DB; tree is small.
- [Risk] Frontend-only hide forgotten on new entry → Mitigation: checklist in tasks; API tests are the contract.
- [Trade-off] editor outside trees still “has” unused perms in token → noisy but harmless; optional later role pack trim.

## Migration Plan

- Deploy; no schema migration.
- Existing sessions pick up new 403 immediately.
- Communicate to editors outside 项目管理部 / 运营管理中心.
- Rollback: revert release; prior permission-only behavior returns.

## Open Questions

- None blocking; optional later: trim default role packs.
