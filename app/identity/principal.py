from __future__ import annotations

from dataclasses import dataclass

from app.identity.constants import CLEARANCE_RANK


@dataclass(frozen=True)
class Principal:
    """Per-request identity projection. Always rebuilt from live DB — never freeze in session."""

    user_id: str
    tenant_id: str
    username: str
    display_name: str
    site: str
    clearance: str
    org_unit_ids: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    project_ids: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    position_ids: tuple[str, ...] = ()
    establishment_org_unit_ids: tuple[str, ...] = ()
    # Department dual-gate (computed at load; admin / users:manage forces True).
    staffing_org_ok: bool = False
    leave_ledger_org_ok: bool = False

    def has_permission(self, code: str) -> bool:
        return code in self.permissions

    def clearance_rank(self) -> int:
        return CLEARANCE_RANK.get(self.clearance, 0)
