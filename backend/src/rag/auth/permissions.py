"""Central account-type and permission helpers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, Protocol

from rag.shared.contracts.clearance import MAX_CLEARANCE_LEVEL, clearance_rank, normalize_clearance_level
from rag.shared.contracts.group_paths import normalize_group_path

AccountType = Literal[
    "platform_admin",
    "system_admin",
    "user_manager",
    "space_admin",
    "contributor",
    "reviewer",
    "auditor",
    "member",
]

ACCOUNT_TYPES: tuple[AccountType, ...] = (
    "platform_admin",
    "system_admin",
    "user_manager",
    "space_admin",
    "contributor",
    "reviewer",
    "auditor",
    "member",
)

LEGACY_ADMIN_GROUP = "/admin"
LEGACY_REVIEW_GROUP = "/review"
GLOBAL_ADMIN_ACCOUNT_TYPES = {"platform_admin", "system_admin"}
SCOPED_USER_MANAGER_ACCOUNT_TYPES = {"user_manager", "space_admin"}
SCOPED_MANAGED_ACCOUNT_TYPES = {"contributor", "reviewer", "member"}
SCOPED_ASSIGNABLE_ACCOUNT_TYPES = {"contributor", "member"}


class PermissionUser(Protocol):
    account_type: AccountType
    group_paths: Sequence[str]
    clearance_level: str


def normalize_account_type(value: str | None, group_paths: Sequence[str] = ()) -> AccountType:
    if value is None or not value.strip():
        return account_type_from_legacy_groups(group_paths)
    candidate = value.strip()
    if candidate not in ACCOUNT_TYPES:
        allowed = ", ".join(ACCOUNT_TYPES)
        raise ValueError(f"account_type must be one of: {allowed}")
    return candidate  # type: ignore[return-value]


def account_type_from_legacy_groups(group_paths: Sequence[str]) -> AccountType:
    normalized = {normalize_group_path(path) for path in group_paths}
    if LEGACY_ADMIN_GROUP in normalized:
        return "platform_admin"
    if LEGACY_REVIEW_GROUP in normalized:
        return "reviewer"
    return "member"


def is_global_admin(user: PermissionUser) -> bool:
    return user.account_type in GLOBAL_ADMIN_ACCOUNT_TYPES


def can_query(user: PermissionUser) -> bool:
    return user.account_type in {*GLOBAL_ADMIN_ACCOUNT_TYPES, "space_admin", "contributor", "member"}


def can_review(user: PermissionUser) -> bool:
    return user.account_type in {*GLOBAL_ADMIN_ACCOUNT_TYPES, "space_admin", "contributor", "reviewer"}


def can_manage_workspace_config(user: PermissionUser) -> bool:
    return user.account_type == "platform_admin"


def can_manage_users(user: PermissionUser) -> bool:
    return user.account_type in {*GLOBAL_ADMIN_ACCOUNT_TYPES, *SCOPED_USER_MANAGER_ACCOUNT_TYPES}


def can_manage_spaces(user: PermissionUser) -> bool:
    return user.account_type in {*GLOBAL_ADMIN_ACCOUNT_TYPES, "space_admin"}


def can_view_audit(user: PermissionUser) -> bool:
    return user.account_type in {*GLOBAL_ADMIN_ACCOUNT_TYPES, "auditor"}


def can_read_document_metadata(user: PermissionUser) -> bool:
    return user.account_type in {*GLOBAL_ADMIN_ACCOUNT_TYPES, "space_admin", "contributor", "reviewer", "auditor", "member"}


def can_write_document_scope(user: PermissionUser, group_path: str) -> bool:
    if is_global_admin(user):
        return True
    if user.account_type in {"space_admin", "contributor", "reviewer"}:
        return has_exact_group_scope(user, group_path)
    return False


def can_upload_to_group(user: PermissionUser, group_path: str) -> bool:
    return can_write_document_scope(user, group_path)


def can_manage_group_path(user: PermissionUser, group_path: str) -> bool:
    if is_global_admin(user):
        return True
    return user.account_type == "space_admin" and has_exact_group_scope(user, group_path)


def can_assign_account_type(actor: PermissionUser, account_type: AccountType) -> bool:
    if actor.account_type == "platform_admin":
        return True
    if actor.account_type == "system_admin":
        return account_type != "platform_admin"
    return actor.account_type in SCOPED_USER_MANAGER_ACCOUNT_TYPES and account_type in SCOPED_ASSIGNABLE_ACCOUNT_TYPES


def can_assign_group_paths(actor: PermissionUser, group_paths: Sequence[str]) -> bool:
    if is_global_admin(actor):
        return True
    if actor.account_type not in SCOPED_USER_MANAGER_ACCOUNT_TYPES:
        return False
    return bool(group_paths) and all(has_exact_group_scope(actor, path) for path in group_paths)


def can_assign_clearance_level(actor: PermissionUser, clearance_level: str) -> bool:
    if is_global_admin(actor):
        return True
    if actor.account_type not in SCOPED_USER_MANAGER_ACCOUNT_TYPES:
        return False
    return clearance_rank(clearance_level) <= clearance_rank(actor.clearance_level)


def can_manage_target_user(actor: PermissionUser, target: PermissionUser) -> bool:
    if actor.account_type == "platform_admin":
        return True
    if actor.account_type == "system_admin":
        return target.account_type != "platform_admin"
    if actor.account_type not in SCOPED_USER_MANAGER_ACCOUNT_TYPES or target.account_type not in SCOPED_MANAGED_ACCOUNT_TYPES:
        return False
    return can_assign_group_paths(actor, target.group_paths) and can_assign_clearance_level(actor, target.clearance_level)


def has_exact_group_scope(user: PermissionUser, group_path: str) -> bool:
    normalized = normalize_group_path(group_path)
    return any(normalize_group_path(scope) == normalized for scope in user.group_paths)


def filter_group_paths_for_user(user: PermissionUser, group_paths: Sequence[str]) -> list[str]:
    if is_global_admin(user):
        return sorted({normalize_group_path(path) for path in group_paths})
    return sorted({normalize_group_path(path) for path in group_paths if has_exact_group_scope(user, path)})


def effective_clearance_level(account_type: AccountType, clearance_level: str | None = None) -> str:
    if account_type in GLOBAL_ADMIN_ACCOUNT_TYPES:
        return MAX_CLEARANCE_LEVEL
    return normalize_clearance_level(clearance_level)
