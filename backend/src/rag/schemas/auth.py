from typing import Literal

from pydantic import Field

from ..auth.permissions import AccountType
from ..shared.contracts.clearance import ClearanceLevel, DEFAULT_CLEARANCE_LEVEL
from .common import ContractModel


class LoginRequest(ContractModel):
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=1)


class AuthUser(ContractModel):
    user_id: str
    email: str
    account_type: AccountType
    group_paths: list[str] = Field(default_factory=list)
    clearance_level: ClearanceLevel = DEFAULT_CLEARANCE_LEVEL
    permission_version: int = Field(..., ge=0)
    must_change_password: bool = False


class LoginResponse(ContractModel):
    user: AuthUser
    csrf_token: str = Field(..., min_length=1)


class RefreshResponse(ContractModel):
    user: AuthUser
    csrf_token: str = Field(..., min_length=1)


class ChangePasswordRequest(ContractModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)


class LogoutResponse(ContractModel):
    status: Literal["accepted"] = "accepted"
