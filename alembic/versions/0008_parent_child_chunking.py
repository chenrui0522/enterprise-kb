"""add chunk_parents and document_tables for parent-child chunking

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-15
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE document_versions ADD COLUMN IF NOT EXISTS parent_count INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE document_versions ADD COLUMN IF NOT EXISTS table_count INTEGER NOT NULL DEFAULT 0")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chunk_parents (
            id VARCHAR(64) PRIMARY KEY,
            tenant_id VARCHAR(64) NOT NULL,
            doc_id VARCHAR(32) NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            version_id VARCHAR(32) NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL DEFAULT 0,
            heading_path VARCHAR(1000) NOT NULL DEFAULT '',
            section VARCHAR(500) NOT NULL DEFAULT '',
            page INTEGER NOT NULL DEFAULT 0,
            doc_type VARCHAR(16) NOT NULL DEFAULT '',
            text TEXT NOT NULL,
            char_count INTEGER NOT NULL DEFAULT 0,
            child_count INTEGER NOT NULL DEFAULT 0,
            chunker_version VARCHAR(64) NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_chunk_parents_tenant_id ON chunk_parents (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_chunk_parents_doc_id ON chunk_parents (doc_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_chunk_parents_version_id ON chunk_parents (version_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS document_tables (
            id VARCHAR(64) PRIMARY KEY,
            tenant_id VARCHAR(64) NOT NULL,
            doc_id VARCHAR(32) NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            version_id VARCHAR(32) NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
            name VARCHAR(500) NOT NULL DEFAULT '',
            page INTEGER NOT NULL DEFAULT 0,
            section VARCHAR(500) NOT NULL DEFAULT '',
            heading_path VARCHAR(1000) NOT NULL DEFAULT '',
            header JSONB NOT NULL DEFAULT '[]'::jsonb,
            row_count INTEGER NOT NULL DEFAULT 0,
            storage_key VARCHAR(1000) NOT NULL DEFAULT '',
            source VARCHAR(32) NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            chunker_version VARCHAR(64) NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_document_tables_tenant_id ON document_tables (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_document_tables_doc_id ON document_tables (doc_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_document_tables_version_id ON document_tables (version_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS document_tables")
    op.execute("DROP TABLE IF EXISTS chunk_parents")
    op.execute("ALTER TABLE document_versions DROP COLUMN IF EXISTS parent_count")
    op.execute("ALTER TABLE document_versions DROP COLUMN IF EXISTS table_count")