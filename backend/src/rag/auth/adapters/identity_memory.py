"""In-memory identity repository for tests and local fallback."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock
from uuid import uuid4

from ...shared.contracts.clearance import ClearanceLevel, normalize_clearance_level
from ...shared.contracts.group_paths import normalize_group_path, require_flat_group_path
from ..identity_models import GroupRecord, UserRecord
from ..permissions import AccountType, effective_clearance_level, normalize_account_type


class InMemoryIdentityRepository:
    def __init__(self) -> None:
        self._groups: dict[str, GroupRecord] = {}
        self._users: dict[str, UserRecord] = {}
        self._lock = RLock()

    def count_users(self) -> int:
        with self._lock:
            return len(self._users)

    def create_initial_admin_if_empty(
        self,
        *,
        email: str,
        name: str,
        password_hash: str,
    ) -> UserRecord | None:
        with self._lock:
            if self._users:
                return None
            return self.create_user(
                email=email,
                name=name,
                password_hash=password_hash,
                group_paths=[],
                is_active=True,
                account_type="platform_admin",
            )

    def get_user_by_email(self, email: str) -> UserRecord | None:
        normalized = email.strip().lower()
        with self._lock:
            return next((user for user in self._users.values() if user.email.lower() == normalized), None)

    def get_user_by_id(self, user_id: str) -> UserRecord | None:
        return self._users.get(user_id)

    def list_users(self) -> list[UserRecord]:
        return sorted(self._users.values(), key=lambda user: user.email.lower())

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
    ) -> UserRecord:
        with self._lock:
            if self.get_user_by_email(email):
                raise ValueError("email already exists")
            groups = self._normalize_existing_groups(group_paths)
            normalized_account_type = normalize_account_type(account_type, groups)
            normalized_clearance = effective_clearance_level(normalized_account_type, clearance_level)
            user = UserRecord(
                id=str(uuid4()),
                email=email.strip().lower(),
                name=name.strip(),
                password_hash=password_hash,
                is_active=is_active,
                account_type=normalized_account_type,
                clearance_level=normalized_clearance,
                must_change_password=True,
                permission_version=1,
                group_paths=tuple(groups),
            )
            self._users[user.id] = user
            return user

    def update_user(
        self,
        user_id: str,
        *,
        name: str | None = None,
        group_paths: list[str] | None = None,
        is_active: bool | None = None,
        account_type: AccountType | None = None,
        clearance_level: ClearanceLevel | None = None,
    ) -> UserRecord | None:
        user = self._users.get(user_id)
        if user is None:
            return None
        next_groups = user.group_paths if group_paths is None else tuple(self._normalize_existing_groups(group_paths))
        next_account_type = user.account_type if account_type is None else normalize_account_type(account_type, next_groups)
        next_clearance = (
            effective_clearance_level(next_account_type, user.clearance_level)
            if clearance_level is None
            else effective_clearance_level(next_account_type, normalize_clearance_level(clearance_level))
        )
        permission_changed = next_groups != user.group_paths or (
            is_active is not None and is_active != user.is_active
        ) or next_account_type != user.account_type or next_clearance != user.clearance_level
        updated = UserRecord(
            id=user.id,
            email=user.email,
            name=user.name if name is None else name.strip(),
            password_hash=user.password_hash,
            is_active=user.is_active if is_active is None else is_active,
            account_type=next_account_type,
            clearance_level=next_clearance,
            must_change_password=user.must_change_password,
            permission_version=user.permission_version + 1 if permission_changed else user.permission_version,
            group_paths=next_groups,
            last_login_at=user.last_login_at,
        )
        self._users[user_id] = updated
        return updated

    def delete_user(self, user_id: str) -> bool:
        return self._users.pop(user_id, None) is not None

    def set_user_password(self, user_id: str, password_hash: str, *, must_change_password: bool = False) -> UserRecord | None:
        user = self._users.get(user_id)
        if user is None:
            return None
        updated = UserRecord(
            id=user.id,
            email=user.email,
            name=user.name,
            password_hash=password_hash,
            is_active=user.is_active,
            account_type=user.account_type,
            clearance_level=user.clearance_level,
            must_change_password=must_change_password,
            permission_version=user.permission_version,
            group_paths=user.group_paths,
            last_login_at=user.last_login_at,
        )
        self._users[user_id] = updated
        return updated

    def set_last_login(self, user_id: str) -> None:
        user = self._users.get(user_id)
        if user is None:
            return
        self._users[user_id] = UserRecord(
            id=user.id,
            email=user.email,
            name=user.name,
            password_hash=user.password_hash,
            is_active=user.is_active,
            account_type=user.account_type,
            clearance_level=user.clearance_level,
            must_change_password=user.must_change_password,
            permission_version=user.permission_version,
            group_paths=user.group_paths,
            last_login_at=datetime.now(UTC),
        )

    def list_groups(self) -> list[GroupRecord]:
        return sorted(self._groups.values(), key=lambda group: group.path)

    def create_group(self, *, path: str, name: str) -> GroupRecord:
        normalized = require_flat_group_path(path)
        if normalized in self._groups:
            raise ValueError("group already exists")
        group = GroupRecord(path=normalized, name=name.strip())
        self._groups[normalized] = group
        return group

    def update_group(self, *, path: str, name: str) -> GroupRecord | None:
        normalized = require_flat_group_path(path)
        if normalized not in self._groups:
            return None
        group = GroupRecord(path=normalized, name=name.strip())
        self._groups[normalized] = group
        return group

    def delete_group(self, path: str) -> bool:
        normalized = normalize_group_path(path)
        if normalized not in self._groups:
            return False
        if any(normalized in user.group_paths for user in self._users.values()):
            raise ValueError("group has assigned users")
        del self._groups[normalized]
        return True

    def add_user_group(self, user_id: str, group_path: str) -> UserRecord | None:
        user = self._users.get(user_id)
        if user is None:
            return None
        normalized = self._normalize_existing_groups([group_path])[0]
        return self.update_user(user_id, group_paths=sorted({*user.group_paths, normalized}))

    def remove_user_group(self, user_id: str, group_path: str) -> UserRecord | None:
        user = self._users.get(user_id)
        if user is None:
            return None
        normalized = normalize_group_path(group_path)
        return self.update_user(user_id, group_paths=[path for path in user.group_paths if path != normalized])

    def _normalize_existing_groups(self, group_paths: list[str]) -> list[str]:
        normalized = sorted({require_flat_group_path(path) for path in group_paths})
        missing = [path for path in normalized if path not in self._groups]
        if missing:
            raise ValueError(f"group does not exist: {missing[0]}")
        return normalized
