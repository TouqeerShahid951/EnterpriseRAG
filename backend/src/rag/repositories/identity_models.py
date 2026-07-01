"""Identity repository records and contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ..auth.permissions import AccountType
from ..shared.contracts.clearance import ClearanceLevel


@dataclass(frozen=True)
class GroupRecord:
    path: str
    name: str


@dataclass(frozen=True)
class UserRecord:
    id: str
    email: str
    name: str
    password_hash: str
    is_active: bool
    account_type: AccountType
    clearance_level: ClearanceLevel
    must_change_password: bool
    permission_version: int
    group_paths: tuple[str, ...]
    last_login_at: datetime | None = None


class IdentityRepository(Protocol):
    def count_users(self) -> int: ...
    def create_initial_admin_if_empty(
        self,
        *,
        email: str,
        name: str,
        password_hash: str,
    ) -> UserRecord | None: ...
    def get_user_by_email(self, email: str) -> UserRecord | None: ...
    def get_user_by_id(self, user_id: str) -> UserRecord | None: ...
    def list_users(self) -> list[UserRecord]: ...
    def create_user(
        self,
        *,
        email: str,
        name: str,
        password_hash: str,
        group_paths: list[str],
        is_active: bool,
        account_type: AccountType | None = None,
        clearance_level: ClearanceLevel | None = None,
    ) -> UserRecord: ...
    def update_user(
        self,
        user_id: str,
        *,
        name: str | None = None,
        group_paths: list[str] | None = None,
        is_active: bool | None = None,
        account_type: AccountType | None = None,
        clearance_level: ClearanceLevel | None = None,
    ) -> UserRecord | None: ...
    def delete_user(self, user_id: str) -> bool: ...
    def set_user_password(self, user_id: str, password_hash: str, *, must_change_password: bool = False) -> UserRecord | None: ...
    def set_last_login(self, user_id: str) -> None: ...
    def list_groups(self) -> list[GroupRecord]: ...
    def create_group(self, *, path: str, name: str) -> GroupRecord: ...
    def update_group(self, *, path: str, name: str) -> GroupRecord | None: ...
    def delete_group(self, path: str) -> bool: ...
    def add_user_group(self, user_id: str, group_path: str) -> UserRecord | None: ...
    def remove_user_group(self, user_id: str, group_path: str) -> UserRecord | None: ...
