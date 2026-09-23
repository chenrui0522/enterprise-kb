"""staffing facts unique key includes person_kind

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-23
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE staffing_attendance_facts "
        "DROP CONSTRAINT IF EXISTS uq_staffing_fact_batch_person_day"
    )
    op.execute(
        """
        ALTER TABLE staffing_attendance_facts
        ADD CONSTRAINT uq_staffing_fact_batch_person_day_kind
        UNIQUE (batch_id, work_date, person_name, person_kind)
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE staffing_attendance_facts "
        "DROP CONSTRAINT IF EXISTS uq_staffing_fact_batch_person_day_kind"
    )
    op.execute(
        """
        ALTER TABLE staffing_attendance_facts
        ADD CONSTRAINT uq_staffing_fact_batch_person_day
        UNIQUE (batch_id, work_date, person_name)
        """
    )
