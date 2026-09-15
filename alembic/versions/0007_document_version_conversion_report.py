"""add conversion_report to document_versions

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-15
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE document_versions ADD COLUMN IF NOT EXISTS conversion_report JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE document_versions DROP COLUMN IF EXISTS conversion_report")