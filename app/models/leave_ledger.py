"""Leave-ledger domain models: jobs, sources, snapshots."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.core.db import Base
from app.models.entity import TimestampMixin, new_id


class LeaveLedgerJob(Base, TimestampMixin):
    __tablename__ = "leave_ledger_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="collecting", index=True
    )  # collecting|parsed|needs_review|confirmed|voided
    created_by: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    warnings: Mapped[list | None] = mapped_column(JSON, nullable=True)
    compute_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    resolved_warnings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    voided_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)


class LeaveLedgerSource(Base, TimestampMixin):
    __tablename__ = "leave_ledger_sources"
    __table_args__ = (
        UniqueConstraint("job_id", "role", name="uq_leave_ledger_source_job_role"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    job_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("leave_ledger_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # travel|overtime|leave|punch
    filename: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    storage_key: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    parse_preview: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class LeaveLedgerSnapshot(Base, TimestampMixin):
    __tablename__ = "leave_ledger_snapshots"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    job_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("leave_ledger_jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    rows: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_roles: Mapped[list | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
