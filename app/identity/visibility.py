"""Corpus visibility predicates shared by Postgres lists and Milvus expr."""

from __future__ import annotations

from sqlalchemy import and_, or_
from sqlalchemy.sql import ColumnElement

from app.identity.constants import CLEARANCE_RANK
from app.identity.principal import Principal
from app.models.entity import Document


def document_visible_clause(principal: Principal) -> ColumnElement[bool]:
    """SQLAlchemy filter matching design D10 for document list."""
    org_clause = None
    if principal.org_unit_ids:
        allowed = [
            code
            for code, rank in CLEARANCE_RANK.items()
            if rank <= principal.clearance_rank()
        ]
        org_clause = and_(
            Document.org_unit_id.in_(principal.org_unit_ids),
            Document.classification.in_(allowed),
        )

    project_clause = None
    if principal.project_ids and principal.domains:
        project_clause = and_(
            Document.project_id.in_(principal.project_ids),
            Document.domain.in_(principal.domains),
            Document.project_id.is_not(None),
            Document.project_id != "",
        )

    if org_clause is not None and project_clause is not None:
        return or_(org_clause, project_clause)
    if org_clause is not None:
        return org_clause
    if project_clause is not None:
        return project_clause
    # No scope → see nothing (admin does not bypass).
    return Document.id == "__none__"


def build_visibility_expr(principal: Principal) -> str:
    """Milvus boolean expr ANDed with tenant_id by the caller."""
    parts: list[str] = []
    if principal.org_unit_ids:
        orgs = ", ".join(f'"{_esc(oid)}"' for oid in principal.org_unit_ids)
        allowed = [
            code
            for code, rank in CLEARANCE_RANK.items()
            if rank <= principal.clearance_rank()
        ]
        classes = ", ".join(f'"{_esc(c)}"' for c in allowed)
        parts.append(f"(org_unit_id in [{orgs}] and classification in [{classes}])")
    if principal.project_ids and principal.domains:
        projects = ", ".join(f'"{_esc(pid)}"' for pid in principal.project_ids)
        domains = ", ".join(f'"{_esc(d)}"' for d in principal.domains)
        parts.append(
            f'(project_id in [{projects}] and domain in [{domains}] and project_id != "")'
        )
    if not parts:
        return 'id == "__none__"'
    return "(" + " or ".join(parts) + ")"


def can_upload_to(
    principal: Principal,
    *,
    org_unit_id: str | None,
    project_id: str | None,
    domain: str | None,
) -> bool:
    if project_id:
        if project_id not in principal.project_ids:
            return False
        if not domain or domain not in principal.domains:
            return False
        return True
    if not org_unit_id:
        return False
    return org_unit_id in principal.org_unit_ids


def _esc(value: str) -> str:
    return str(value).replace("\\", "").replace('"', "")
