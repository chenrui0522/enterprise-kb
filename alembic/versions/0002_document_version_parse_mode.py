"""add parse_mode to document_versions

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-05
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE document_versions "
        "ADD COLUMN IF NOT EXISTS parse_mode VARCHAR(16) NOT NULL DEFAULT 'auto'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE document_versions DROP COLUMN IF EXISTS parse_mode")
