"""chat tools: conversation.tool_state + chat attachments support

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-23
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS tool_state JSONB"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS tool_state")
