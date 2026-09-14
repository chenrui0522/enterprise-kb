"""add heading_path to document_images

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-14
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE document_images ADD COLUMN IF NOT EXISTS heading_path VARCHAR(1000) NOT NULL DEFAULT ''"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE document_images DROP COLUMN IF EXISTS heading_path")