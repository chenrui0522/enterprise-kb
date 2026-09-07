"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-05
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Fresh project: materialize the model metadata. The application models are
    # the source of truth for the schema; production can pin revisions later.
    import app.models.entity  # noqa: F401

    from app.core.db import Base

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    import app.models.entity  # noqa: F401

    from app.core.db import Base

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
