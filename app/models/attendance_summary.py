"""Attendance summary ledger jobs, sources, and tenant month config."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.core.db import Base
from app.models.entity import TimestampMixin, new_id


class AttendanceSummaryJob(Base, TimestampMixin):
    __tablename__ = "attendance_summary_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft", index=True
    )
    created_by: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    prior_job_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    roster: Mapped[list | None] = mapped_column(JSON, nullable=True)
    warnings: Mapped[list | None] = mapped_column(JSON, nullable=True)
    resolved_warnings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    compute_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    confirmed_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    voided_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    origin: Mapped[str] = mapped_column(String(32), nullable=False, default="workflow")
    period_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    calendar_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    non_work_dates: Mapped[list | None] = mapped_column(JSON, nullable=True)


class AttendanceSummarySource(Base, TimestampMixin):
    __tablename__ = "attendance_summary_sources"
    __table_args__ = (
        UniqueConstraint("job_id", "role", name="uq_attendance_summary_source_job_role"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    job_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("attendance_summary_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    storage_key: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    parse_preview: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class AttendanceSummaryConfig(Base, TimestampMixin):
    """Per-tenant calendar + overseas keywords (JSON blobs)."""

    __tablename__ = "attendance_summary_configs"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_attendance_summary_config_tenant"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    calendars: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    overseas_keywords: Mapped[list | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
