"""staffing daily import tables

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-22
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS staffing_import_batches (
            id VARCHAR(32) PRIMARY KEY,
            tenant_id VARCHAR(64) NOT NULL,
            project_id VARCHAR(32) REFERENCES projects(id) ON DELETE SET NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'parsed',
            filename VARCHAR(500) NOT NULL DEFAULT '',
            storage_key VARCHAR(1000) NOT NULL DEFAULT '',
            uploaded_by VARCHAR(32) NOT NULL DEFAULT '',
            warnings JSONB,
            parse_result JSONB,
            resolved_warnings JSONB,
            match_info JSONB,
            confirmed_at TIMESTAMPTZ,
            confirmed_by VARCHAR(32),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_staffing_import_batches_tenant_id "
        "ON staffing_import_batches (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_staffing_import_batches_project_id "
        "ON staffing_import_batches (project_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_staffing_import_batches_status "
        "ON staffing_import_batches (status)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS staffing_attendance_facts (
            id VARCHAR(32) PRIMARY KEY,
            tenant_id VARCHAR(64) NOT NULL,
            project_id VARCHAR(32) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            batch_id VARCHAR(32) NOT NULL
                REFERENCES staffing_import_batches(id) ON DELETE CASCADE,
            work_date DATE NOT NULL,
            person_name VARCHAR(64) NOT NULL,
            person_kind VARCHAR(32) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            void_reason VARCHAR(64),
            voided_by VARCHAR(32),
            voided_at TIMESTAMPTZ,
            stage VARCHAR(64),
            source_row INTEGER,
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_staffing_fact_batch_person_day
                UNIQUE (batch_id, work_date, person_name)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_staffing_attendance_facts_tenant_id "
        "ON staffing_attendance_facts (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_staffing_attendance_facts_project_id "
        "ON staffing_attendance_facts (project_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_staffing_attendance_facts_batch_id "
        "ON staffing_attendance_facts (batch_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_staffing_attendance_facts_work_date "
        "ON staffing_attendance_facts (work_date)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_staffing_attendance_facts_person_name "
        "ON staffing_attendance_facts (person_name)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_staffing_attendance_facts_status "
        "ON staffing_attendance_facts (status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_staffing_facts_project_active "
        "ON staffing_attendance_facts (project_id, status, work_date)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS staffing_attendance_facts")
    op.execute("DROP TABLE IF EXISTS staffing_import_batches")
