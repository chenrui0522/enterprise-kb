"""chat conversation title_source for auto-title vs user rename

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-23
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS "
        "title_source VARCHAR(16) NOT NULL DEFAULT 'default'"
    )
    # Existing non-default titles treated as user so polish won't overwrite.
    op.execute(
        "UPDATE conversations SET title_source = 'default' "
        "WHERE title = '新对话' OR title IS NULL OR btrim(title) = ''"
    )
    op.execute(
        "UPDATE conversations SET title_source = 'user' "
        "WHERE title_source = 'default' AND title IS DISTINCT FROM '新对话'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS title_source")
