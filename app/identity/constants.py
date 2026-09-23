"""Identity / access-control enumerations and permission catalog."""

from __future__ import annotations

SITES = frozenset({"taiyuan", "shuozhou", "suzhou"})

CLEARANCES = frozenset({"general", "core"})
CLEARANCE_RANK = {"general": 0, "core": 1}

DOMAINS = frozenset(
    {"software", "electrical", "mechanical", "procurement", "operations", "finance", "sales"}
)

ORG_UNIT_TYPES = frozenset({"company", "office", "center", "dept", "committee"})

RELATION_ESTABLISHMENT = "establishment"

# Permission strings (action only — never encode org/domain/clearance here).
PERM_DOCUMENTS_READ = "documents:read"
PERM_DOCUMENTS_WRITE = "documents:write"
PERM_CHAT_USE = "chat:use"
PERM_AUDIT_READ = "audit:read"
PERM_USERS_MANAGE = "users:manage"
PERM_ORGS_MANAGE = "orgs:manage"
PERM_PROJECTS_MANAGE = "projects:manage"
PERM_STAFFING_READ = "staffing:read"
PERM_STAFFING_WRITE = "staffing:write"

ALL_PERMISSIONS: tuple[str, ...] = (
    PERM_DOCUMENTS_READ,
    PERM_DOCUMENTS_WRITE,
    PERM_CHAT_USE,
    PERM_AUDIT_READ,
    PERM_USERS_MANAGE,
    PERM_ORGS_MANAGE,
    PERM_PROJECTS_MANAGE,
    PERM_STAFFING_READ,
    PERM_STAFFING_WRITE,
)

ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "admin": ALL_PERMISSIONS,
    "editor": (
        PERM_DOCUMENTS_READ,
        PERM_DOCUMENTS_WRITE,
        PERM_CHAT_USE,
        PERM_STAFFING_READ,
        PERM_STAFFING_WRITE,
    ),
    "reader": (PERM_DOCUMENTS_READ, PERM_CHAT_USE, PERM_STAFFING_READ),
    "auditor": (PERM_DOCUMENTS_READ, PERM_AUDIT_READ),
}

DEFAULT_TENANT_ID = "autley"
SESSION_COOKIE_NAME = "kb_session"
