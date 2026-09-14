"""add document_images table

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-14
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS document_images (
            id VARCHAR(32) PRIMARY KEY,
            tenant_id VARCHAR(64) NOT NULL,
            doc_id VARCHAR(32) NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            version_id VARCHAR(32) NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
            page INTEGER NOT NULL DEFAULT 0,
            bbox VARCHAR(200),
            storage_key VARCHAR(1000) NOT NULL,
            sha256 VARCHAR(64) NOT NULL,
            mime VARCHAR(64) NOT NULL,
            width INTEGER NOT NULL DEFAULT 0,
            height INTEGER NOT NULL DEFAULT 0,
            caption TEXT,
            description TEXT,
            source VARCHAR(16) NOT NULL DEFAULT 'local',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_document_images_tenant_id ON document_images (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_document_images_doc_id ON document_images (doc_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_document_images_version_id ON document_images (version_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_document_images_sha256 ON document_images (sha256)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS document_images")