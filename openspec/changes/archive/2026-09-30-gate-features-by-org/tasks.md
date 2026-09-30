## 1. Identity helper

- [x] 1.1 Add org-subtree resolver (root codes → descendant org ids for tenant) and `can_use_staffing` / `can_use_leave_ledger` (perm + subtree or `users:manage` bypass); verify unit tests for project_div under project_mgmt, ops_hr under ops, outsider denied, admin bypass
- [x] 1.2 Expose gate results on `/me` (or equivalent Principal projection) so UI can hide entries without reimplementing subtree logic; verify response fields for in-tree vs out-of-tree users

## 2. API enforcement

- [x] 2.1 Apply dual gate to all `staffing` router endpoints (read/write); verify 403 for permitted-but-wrong-org and 200 path for project_mgmt subtree + admin
- [x] 2.2 Apply dual gate to all `leave_ledger` router endpoints; verify same pattern for ops subtree

## 3. Chat tools

- [x] 3.1 Update tool registry/router eligibility and leave/staffing orchestrator actions to use the same helpers; verify wrong-org users are not offered/claimed and actions return 403

## 4. Frontend

- [x] 4.1 Gate nav and page access for Staffing / Leave Ledger using server-provided flags; verify entries hidden for out-of-tree editor and visible for in-tree / admin
- [x] 4.2 Hide chat tool options for the two features when gated out; verify tool dropdown matches `/me` flags

## 5. Docs & tests

- [x] 5.1 Document department allowlists + admin bypass in README identity/staffing/leave sections; verify codes match `org_seed`
- [x] 5.2 Run identity + staffing + leave-ledger (+ chat tool) related tests and verify suite green
