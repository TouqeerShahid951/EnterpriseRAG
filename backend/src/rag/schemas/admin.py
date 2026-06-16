from datetime import datetime

from pydantic import Field

from ..auth.permissions import AccountType
from ..shared.contracts.clearance import ClearanceLevel, DEFAULT_CLEARANCE_LEVEL
from .common import ContractModel


class Group(ContractModel):
    path: str
    name: str


class GroupListResponse(ContractModel):
    items: list[Group] = Field(default_factory=list)


class GroupCreateRequest(ContractModel):
    path: str
    name: str


class GroupUpdateRequest(ContractModel):
    path: str
    name: str


class GroupDeleteRequest(ContractModel):
    path: str


class UserAdmin(ContractModel):
    id: str
    email: str
    name: str
    account_type: AccountType
    group_paths: list[str] = Field(default_factory=list)
    clearance_level: ClearanceLevel = DEFAULT_CLEARANCE_LEVEL
    last_login_at: datetime | None = None
    is_active: bool
    permission_version: int = Field(..., ge=0)


class UserListResponse(ContractModel):
    items: list[UserAdmin] = Field(default_factory=list)
    total: int = Field(..., ge=0)


class UserCreateRequest(ContractModel):
    email: str
    name: str
    initial_password: str = Field(..., min_length=8)
    account_type: AccountType | None = None
    group_paths: list[str] = Field(default_factory=list)
    clearance_level: ClearanceLevel | None = None
    is_active: bool = True


class UserUpdateRequest(ContractModel):
    name: str | None = None
    account_type: AccountType | None = None
    group_paths: list[str] | None = None
    clearance_level: ClearanceLevel | None = None
    is_active: bool | None = None


class UserGroupRequest(ContractModel):
    group_path: str
