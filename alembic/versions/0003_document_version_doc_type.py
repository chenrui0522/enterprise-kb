"""add doc_type and chunker_version to document_versions

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-12
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE document_versions "
        "ADD COLUMN IF NOT EXISTS doc_type VARCHAR(16) NOT NULL DEFAULT 'auto'"
    )
    op.execute(
        "ALTER TABLE document_versions "
        "ADD COLUMN IF NOT EXISTS chunker_version VARCHAR(64) NOT NULL DEFAULT ''"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE document_versions DROP COLUMN IF EXISTS chunker_version")
    op.execute("ALTER TABLE document_versions DROP COLUMN IF EXISTS doc_type")