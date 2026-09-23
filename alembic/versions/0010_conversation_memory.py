"""conversation memory: message compression flags + summaries

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-22
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_summaries (
            id VARCHAR(32) PRIMARY KEY,
            tenant_id VARCHAR(64) NOT NULL,
            conversation_id VARCHAR(32) NOT NULL
                REFERENCES conversations(id) ON DELETE CASCADE,
            covered_from_message_id VARCHAR(32),
            covered_to_message_id VARCHAR(32),
            content TEXT NOT NULL DEFAULT '',
            token_count INTEGER NOT NULL DEFAULT 0,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_conversation_summaries_tenant_id "
        "ON conversation_summaries (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_conversation_summaries_conversation_id "
        "ON conversation_summaries (conversation_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_conversation_summaries_conv_version "
        "ON conversation_summaries (conversation_id, version)"
    )

    op.execute(
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS compressed BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS token_count INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        """
        ALTER TABLE messages ADD COLUMN IF NOT EXISTS summary_id VARCHAR(32)
            REFERENCES conversation_summaries(id) ON DELETE SET NULL
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_messages_summary_id ON messages (summary_id)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS summary_id")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS token_count")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS compressed")
    op.execute("DROP TABLE IF EXISTS conversation_summaries")
