"""leave ledger tables

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-24
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_ledger_jobs (
            id VARCHAR(32) PRIMARY KEY,
            tenant_id VARCHAR(64) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'collecting',
            created_by VARCHAR(32) NOT NULL DEFAULT '',
            warnings JSONB,
            compute_result JSONB,
            resolved_warnings JSONB,
            confirmed_at TIMESTAMPTZ,
            confirmed_by VARCHAR(32),
            voided_at TIMESTAMPTZ,
            voided_by VARCHAR(32),
            void_reason VARCHAR(128),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_leave_ledger_jobs_tenant_id "
        "ON leave_ledger_jobs (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_leave_ledger_jobs_status "
        "ON leave_ledger_jobs (status)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_ledger_sources (
            id VARCHAR(32) PRIMARY KEY,
            tenant_id VARCHAR(64) NOT NULL,
            job_id VARCHAR(32) NOT NULL
                REFERENCES leave_ledger_jobs(id) ON DELETE CASCADE,
            role VARCHAR(32) NOT NULL,
            filename VARCHAR(500) NOT NULL DEFAULT '',
            storage_key VARCHAR(1000) NOT NULL DEFAULT '',
            parse_preview JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_leave_ledger_source_job_role UNIQUE (job_id, role)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_leave_ledger_sources_tenant_id "
        "ON leave_ledger_sources (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_leave_ledger_sources_job_id "
        "ON leave_ledger_sources (job_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_ledger_snapshots (
            id VARCHAR(32) PRIMARY KEY,
            tenant_id VARCHAR(64) NOT NULL,
            job_id VARCHAR(32) NOT NULL UNIQUE
                REFERENCES leave_ledger_jobs(id) ON DELETE CASCADE,
            rows JSONB,
            source_roles JSONB,
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_leave_ledger_snapshots_tenant_id "
        "ON leave_ledger_snapshots (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_leave_ledger_snapshots_job_id "
        "ON leave_ledger_snapshots (job_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS leave_ledger_snapshots")
    op.execute("DROP TABLE IF EXISTS leave_ledger_sources")
    op.execute("DROP TABLE IF EXISTS leave_ledger_jobs")
