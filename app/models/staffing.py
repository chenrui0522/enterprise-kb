"""Staffing daily-import models: batches and attendance facts."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.core.db import Base
from app.models.entity import TimestampMixin, new_id


class StaffingImportBatch(Base, TimestampMixin):
    __tablename__ = "staffing_import_batches"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="parsed", index=True
    )  # parsed|needs_review|confirmed|voided
    filename: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    storage_key: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    uploaded_by: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    warnings: Mapped[list | None] = mapped_column(JSON, nullable=True)
    parse_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    resolved_warnings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    match_info: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(String(32), nullable=True)


class StaffingAttendanceFact(Base, TimestampMixin):
    __tablename__ = "staffing_attendance_facts"
    __table_args__ = (
        UniqueConstraint(
            "batch_id",
            "work_date",
            "person_name",
            "person_kind",
            name="uq_staffing_fact_batch_person_day_kind",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    batch_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("staffing_import_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    work_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    person_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    person_kind: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # internal_formal | internal_contract
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", index=True
    )  # active | voided
    void_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    voided_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
