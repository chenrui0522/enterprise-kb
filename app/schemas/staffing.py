"""Staffing API schemas."""



from __future__ import annotations



from datetime import date, datetime

from typing import Any, Literal



from pydantic import BaseModel, Field





class StaffingBatchOut(BaseModel):

    id: str

    tenant_id: str

    project_id: str | None

    status: str

    filename: str

    warnings: list[dict[str, Any]] | None = None

    parse_result: dict[str, Any] | None = None

    resolved_warnings: dict[str, Any] | None = None

    match_info: dict[str, Any] | None = None

    confirmed_at: datetime | None = None

    created_at: datetime | None = None



    model_config = {"from_attributes": True}





class ReviewIn(BaseModel):

    project_id: str | None = None

    resolutions: dict[str, Any] | None = None

    person_renames: dict[str, str] | None = None





class VoidIn(BaseModel):

    scope: Literal["day", "day_person", "person", "batch"]

    dates: list[str] | None = None

    person_names: list[str] | None = None

    batch_id: str | None = None





class KindSubtotalOut(BaseModel):

    person_count: int = 0

    person_day_total: int = 0





class ByKindOut(BaseModel):

    formal: KindSubtotalOut = Field(default_factory=KindSubtotalOut)

    contract: KindSubtotalOut = Field(default_factory=KindSubtotalOut)





class StintOut(BaseModel):

    index: int

    entry_date: str

    exit_date: str

    days: int





class PersonSummaryOut(BaseModel):

    person_name: str

    person_kind: str

    person_kind_label: str = ""

    days_on_site: int

    dates: list[str] = Field(default_factory=list)

    stint_count: int = 0

    stints: list[StintOut] = Field(default_factory=list)





class ProjectSummaryOut(BaseModel):

    project_id: str

    project_code: str = ""

    project_name: str = ""

    people: list[PersonSummaryOut]

    person_count: int

    person_day_total: int = 0

    date_from: str | None = None

    date_to: str | None = None

    by_kind: ByKindOut = Field(default_factory=ByKindOut)

    label: str = "在场天数"





class FactOut(BaseModel):

    id: str

    project_id: str

    batch_id: str

    work_date: date

    person_name: str

    person_kind: str

    status: str

    stage: str | None = None

    void_reason: str | None = None



    model_config = {"from_attributes": True}





class VoidOut(BaseModel):

    voided_count: int


