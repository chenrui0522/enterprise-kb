"""add image_id to message_citations

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-14
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE message_citations ADD COLUMN IF NOT EXISTS image_id VARCHAR(32)")


def downgrade() -> None:
    op.execute("ALTER TABLE message_citations DROP COLUMN IF EXISTS image_id")