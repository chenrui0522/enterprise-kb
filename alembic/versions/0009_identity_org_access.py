"""add identity, org tree, positions, projects, and document access labels

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-20
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Seeded once; tenant-scoped role codes for the default Autley tenant.
_SEED_TENANT = "autley"

_PERMISSIONS = [
    ("documents:read", "Read documents and search"),
    ("documents:write", "Upload and manage documents"),
    ("chat:use", "Use knowledge QA"),
    ("audit:read", "Read audit events"),
    ("users:manage", "Manage users and bindings"),
    ("orgs:manage", "Manage org units and positions"),
    ("projects:manage", "Manage projects and members"),
]

_ROLE_PERMS = {
    "admin": [p[0] for p in _PERMISSIONS],
    "editor": ["documents:read", "documents:write", "chat:use"],
    "reader": ["documents:read", "chat:use"],
    "auditor": ["documents:read", "audit:read"],
}


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS org_units (
            id VARCHAR(32) PRIMARY KEY,
            tenant_id VARCHAR(64) NOT NULL,
            parent_id VARCHAR(32) REFERENCES org_units(id) ON DELETE SET NULL,
            type VARCHAR(32) NOT NULL,
            code VARCHAR(64) NOT NULL,
            name VARCHAR(200) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            default_site VARCHAR(32),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_org_units_tenant_code UNIQUE (tenant_id, code)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_org_units_tenant_id ON org_units (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_org_units_parent_id ON org_units (parent_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id VARCHAR(32) PRIMARY KEY,
            tenant_id VARCHAR(64) NOT NULL,
            username VARCHAR(64) NOT NULL,
            display_name VARCHAR(128) NOT NULL DEFAULT '',
            password_hash VARCHAR(255) NOT NULL,
            site VARCHAR(32) NOT NULL DEFAULT 'taiyuan',
            clearance VARCHAR(16) NOT NULL DEFAULT 'general',
            is_active BOOLEAN NOT NULL DEFAULT true,
            must_change_password BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_users_tenant_username UNIQUE (tenant_id, username)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_tenant_id ON users (tenant_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS positions (
            id VARCHAR(32) PRIMARY KEY,
            tenant_id VARCHAR(64) NOT NULL,
            org_unit_id VARCHAR(32) NOT NULL REFERENCES org_units(id) ON DELETE RESTRICT,
            code VARCHAR(64) NOT NULL,
            name VARCHAR(200) NOT NULL,
            domain VARCHAR(32),
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_positions_tenant_org_code UNIQUE (tenant_id, org_unit_id, code)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_positions_tenant_id ON positions (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_positions_org_unit_id ON positions (org_unit_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_positions (
            id VARCHAR(32) PRIMARY KEY,
            user_id VARCHAR(32) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            position_id VARCHAR(32) NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_user_positions UNIQUE (user_id, position_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_positions_user_id ON user_positions (user_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_positions_position_id ON user_positions (position_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS roles (
            id VARCHAR(32) PRIMARY KEY,
            tenant_id VARCHAR(64) NOT NULL,
            code VARCHAR(64) NOT NULL,
            name VARCHAR(128) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_roles_tenant_code UNIQUE (tenant_id, code)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_roles_tenant_id ON roles (tenant_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS permissions (
            code VARCHAR(64) PRIMARY KEY,
            description VARCHAR(255) NOT NULL DEFAULT ''
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS role_permissions (
            id VARCHAR(32) PRIMARY KEY,
            role_id VARCHAR(32) NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
            permission_code VARCHAR(64) NOT NULL REFERENCES permissions(code) ON DELETE CASCADE,
            CONSTRAINT uq_role_permissions UNIQUE (role_id, permission_code)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_role_permissions_role_id ON role_permissions (role_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS position_roles (
            id VARCHAR(32) PRIMARY KEY,
            position_id VARCHAR(32) NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
            role_id VARCHAR(32) NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
            CONSTRAINT uq_position_roles UNIQUE (position_id, role_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_position_roles_position_id ON position_roles (position_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_org_relations (
            id VARCHAR(32) PRIMARY KEY,
            user_id VARCHAR(32) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            org_unit_id VARCHAR(32) NOT NULL REFERENCES org_units(id) ON DELETE CASCADE,
            relation VARCHAR(32) NOT NULL DEFAULT 'establishment',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_user_org_relations UNIQUE (user_id, org_unit_id, relation)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_org_relations_user_id ON user_org_relations (user_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id VARCHAR(32) PRIMARY KEY,
            user_id VARCHAR(32) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash VARCHAR(64) NOT NULL UNIQUE,
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            user_agent VARCHAR(500),
            ip VARCHAR(64)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_sessions_user_id ON sessions (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sessions_token_hash ON sessions (token_hash)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id VARCHAR(32) PRIMARY KEY,
            tenant_id VARCHAR(64) NOT NULL,
            code VARCHAR(64) NOT NULL,
            name VARCHAR(200) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_projects_tenant_code UNIQUE (tenant_id, code)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_projects_tenant_id ON projects (tenant_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS project_members (
            id VARCHAR(32) PRIMARY KEY,
            project_id VARCHAR(32) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            user_id VARCHAR(32) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_project_members UNIQUE (project_id, user_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_project_members_project_id ON project_members (project_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_project_members_user_id ON project_members (user_id)"
    )

    for col_table in ("documents", "document_versions"):
        op.execute(f"ALTER TABLE {col_table} ADD COLUMN IF NOT EXISTS org_unit_id VARCHAR(32)")
        op.execute(f"ALTER TABLE {col_table} ADD COLUMN IF NOT EXISTS project_id VARCHAR(32)")
        op.execute(f"ALTER TABLE {col_table} ADD COLUMN IF NOT EXISTS domain VARCHAR(32)")
        op.execute(
            f"ALTER TABLE {col_table} ADD COLUMN IF NOT EXISTS classification "
            f"VARCHAR(16) NOT NULL DEFAULT 'general'"
        )
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_{col_table}_org_unit_id ON {col_table} (org_unit_id)"
        )
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_{col_table}_project_id ON {col_table} (project_id)"
        )

    # Mark legacy conversations / audit without inventing fake owners until admin exists.
    op.execute(
        """
        UPDATE conversations
        SET created_by = 'legacy:' || created_by
        WHERE created_by = 'local-user'
        """
    )
    op.execute(
        """
        UPDATE audit_events
        SET actor = 'legacy:' || actor
        WHERE actor = 'local-user'
        """
    )

    for code, desc in _PERMISSIONS:
        op.execute(
            f"""
            INSERT INTO permissions (code, description)
            VALUES ('{code}', '{desc}')
            ON CONFLICT (code) DO NOTHING
            """
        )

    import uuid

    for role_code, perms in _ROLE_PERMS.items():
        role_id = uuid.uuid4().hex
        op.execute(
            f"""
            INSERT INTO roles (id, tenant_id, code, name)
            SELECT '{role_id}', '{_SEED_TENANT}', '{role_code}', '{role_code}'
            WHERE NOT EXISTS (
                SELECT 1 FROM roles WHERE tenant_id = '{_SEED_TENANT}' AND code = '{role_code}'
            )
            """
        )
        for perm in perms:
            rp_id = uuid.uuid4().hex
            op.execute(
                f"""
                INSERT INTO role_permissions (id, role_id, permission_code)
                SELECT '{rp_id}', r.id, '{perm}'
                FROM roles r
                WHERE r.tenant_id = '{_SEED_TENANT}' AND r.code = '{role_code}'
                  AND NOT EXISTS (
                    SELECT 1 FROM role_permissions rp
                    WHERE rp.role_id = r.id AND rp.permission_code = '{perm}'
                  )
                """
            )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS project_members")
    op.execute("DROP TABLE IF EXISTS projects")
    op.execute("DROP TABLE IF EXISTS sessions")
    op.execute("DROP TABLE IF EXISTS user_org_relations")
    op.execute("DROP TABLE IF EXISTS position_roles")
    op.execute("DROP TABLE IF EXISTS role_permissions")
    op.execute("DROP TABLE IF EXISTS permissions")
    op.execute("DROP TABLE IF EXISTS roles")
    op.execute("DROP TABLE IF EXISTS user_positions")
    op.execute("DROP TABLE IF EXISTS positions")
    op.execute("DROP TABLE IF EXISTS users")
    op.execute("DROP TABLE IF EXISTS org_units")
    for col_table in ("documents", "document_versions"):
        for col in ("org_unit_id", "project_id", "domain", "classification"):
            op.execute(f"ALTER TABLE {col_table} DROP COLUMN IF EXISTS {col}")
