"""Department dual-gates for staffing / leave-ledger features.

Action permission strings stay org-agnostic; org allowlists are enforced here
(and cached onto Principal at load time).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.constants import (
    PERM_LEAVE_LEDGER_READ,
    PERM_LEAVE_LEDGER_WRITE,
    PERM_STAFFING_READ,
    PERM_STAFFING_WRITE,
    PERM_USERS_MANAGE,
)
from app.identity.org_seed import ORG_SEED_NODES
from app.identity.principal import Principal
from app.models.identity import OrgUnit

FEATURE_STAFFING = "staffing"
FEATURE_LEAVE_LEDGER = "leave_ledger"

# Org unit *codes* (roots); descendants are included.
FEATURE_ORG_ROOTS: dict[str, frozenset[str]] = {
    FEATURE_STAFFING: frozenset({"project_mgmt"}),
    FEATURE_LEAVE_LEDGER: frozenset({"ops"}),
}

# WeCom / address-book imports may use numeric codes while seed uses stable
# kebab codes; both trees can coexist. Also match these display names as roots.
FEATURE_ORG_ROOT_NAMES: dict[str, frozenset[str]] = {
    FEATURE_STAFFING: frozenset({"项目管理部"}),
    FEATURE_LEAVE_LEDGER: frozenset({"运营管理中心"}),
}


def descendant_org_codes(root_codes: set[str] | frozenset[str]) -> set[str]:
    """Closure of root codes using the declarative seed parent links."""
    children: dict[str | None, list[str]] = {}
    for _type, code, _name, parent, _site in ORG_SEED_NODES:
        children.setdefault(parent, []).append(code)
    out: set[str] = set()
    stack = list(root_codes)
    while stack:
        code = stack.pop()
        if code in out:
            continue
        out.add(code)
        stack.extend(children.get(code, []))
    return out


async def resolve_org_ids_for_codes(
    session: AsyncSession,
    *,
    tenant_id: str,
    codes: set[str],
) -> set[str]:
    if not codes:
        return set()
    rows = (
        await session.execute(
            select(OrgUnit.id, OrgUnit.code, OrgUnit.parent_id).where(
                OrgUnit.tenant_id == tenant_id
            )
        )
    ).all()
    if not rows:
        return set()
    code_to_id = {code: oid for oid, code, _ in rows}
    id_to_parent = {oid: parent for oid, _code, parent in rows}
    children: dict[str | None, list[str]] = {}
    for oid, parent in id_to_parent.items():
        children.setdefault(parent, []).append(oid)

    roots = [code_to_id[c] for c in codes if c in code_to_id]
    out: set[str] = set()
    stack = list(roots)
    while stack:
        oid = stack.pop()
        if oid in out:
            continue
        out.add(oid)
        stack.extend(children.get(oid, []))
    return out


async def resolve_feature_org_ids(
    session: AsyncSession,
    *,
    tenant_id: str,
    feature: str,
) -> set[str]:
    """Org ids allowed for a feature: seed codes + same-name WeCom roots, with DB descendants."""
    root_codes = set(FEATURE_ORG_ROOTS.get(feature) or ())
    root_names = set(FEATURE_ORG_ROOT_NAMES.get(feature) or ())
    # Seed-code closure (project_mgmt → project_div_*) then resolve ids.
    code_ids = await resolve_org_ids_for_codes(
        session,
        tenant_id=tenant_id,
        codes=descendant_org_codes(root_codes) if root_codes else set(),
    )
    if not root_names:
        return code_ids

    rows = (
        await session.execute(
            select(OrgUnit.id, OrgUnit.name, OrgUnit.parent_id).where(
                OrgUnit.tenant_id == tenant_id
            )
        )
    ).all()
    if not rows:
        return code_ids
    children: dict[str | None, list[str]] = {}
    for oid, _name, parent in rows:
        children.setdefault(parent, []).append(oid)
    name_roots = [oid for oid, name, _parent in rows if name in root_names]
    out = set(code_ids)
    stack = list(name_roots)
    while stack:
        oid = stack.pop()
        if oid in out:
            continue
        out.add(oid)
        stack.extend(children.get(oid, []))
    return out


async def compute_feature_org_flags(
    session: AsyncSession,
    *,
    tenant_id: str,
    org_unit_ids: set[str] | tuple[str, ...],
    permissions: set[str] | tuple[str, ...],
) -> tuple[bool, bool]:
    """Return (staffing_org_ok, leave_ledger_org_ok). Admin bypasses org check."""
    perms = set(permissions or ())
    if PERM_USERS_MANAGE in perms:
        return True, True
    org_ids = set(org_unit_ids or ())
    staffing_ids = await resolve_feature_org_ids(
        session, tenant_id=tenant_id, feature=FEATURE_STAFFING
    )
    leave_ids = await resolve_feature_org_ids(
        session, tenant_id=tenant_id, feature=FEATURE_LEAVE_LEDGER
    )
    return bool(org_ids & staffing_ids), bool(org_ids & leave_ids)


def org_allows_staffing(principal: Principal) -> bool:
    return bool(principal.staffing_org_ok)


def org_allows_leave_ledger(principal: Principal) -> bool:
    return bool(principal.leave_ledger_org_ok)


def can_use_staffing(principal: Principal, *, write: bool | None = None) -> bool:
    """write=True → need write; write=False → need read; None → either."""
    if not org_allows_staffing(principal):
        return False
    perms = set(principal.permissions or ())
    if write is True:
        return PERM_STAFFING_WRITE in perms
    if write is False:
        return PERM_STAFFING_READ in perms
    return bool(perms & {PERM_STAFFING_READ, PERM_STAFFING_WRITE})


def can_use_leave_ledger(principal: Principal, *, write: bool | None = None) -> bool:
    if not org_allows_leave_ledger(principal):
        return False
    perms = set(principal.permissions or ())
    if write is True:
        return PERM_LEAVE_LEDGER_WRITE in perms
    if write is False:
        return PERM_LEAVE_LEDGER_READ in perms
    return bool(perms & {PERM_LEAVE_LEDGER_READ, PERM_LEAVE_LEDGER_WRITE})
