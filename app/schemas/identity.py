from __future__ import annotations

from pydantic import BaseModel, Field

from app.identity.constants import CLEARANCES, DOMAINS, SITES


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class PrincipalOut(BaseModel):
    user_id: str
    tenant_id: str
    username: str
    display_name: str
    site: str
    clearance: str
    org_unit_ids: list[str]
    domains: list[str]
    project_ids: list[str]
    permissions: list[str]
    position_ids: list[str]
    establishment_org_unit_ids: list[str]
    can_staffing: bool = False
    can_leave_ledger: bool = False


class OrgUnitCreate(BaseModel):
    parent_id: str | None = None
    type: str
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    default_site: str | None = None


class OrgUnitOut(BaseModel):
    id: str
    parent_id: str | None
    type: str
    code: str
    name: str
    status: str
    default_site: str | None

    model_config = {"from_attributes": True}


class PositionCreate(BaseModel):
    org_unit_id: str
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    domain: str | None = None
    role_codes: list[str] = Field(default_factory=list)


class PositionOut(BaseModel):
    id: str
    org_unit_id: str
    code: str
    name: str
    domain: str | None
    status: str
    role_codes: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class BindPositionRequest(BaseModel):
    position_id: str
    clearance: str


class ClearanceUpdate(BaseModel):
    clearance: str


class EstablishmentRequest(BaseModel):
    org_unit_id: str


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    display_name: str = ""
    site: str = "taiyuan"
    clearance: str = "general"


class ProjectCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)


class ProjectMemberRequest(BaseModel):
    user_id: str


def validate_clearance(value: str) -> str:
    if value not in CLEARANCES:
        raise ValueError("clearance must be general or core")
    return value


def validate_site(value: str) -> str:
    if value not in SITES:
        raise ValueError("invalid site")
    return value


def validate_domain(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if value not in DOMAINS:
        raise ValueError("invalid domain")
    return value
