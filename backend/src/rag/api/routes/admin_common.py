"""Shared helpers for admin route modules."""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from ...auth.dependencies import require_current_user
from ...auth.refresh_sessions import RefreshSessionStore
from ...auth.permissions import (
    can_assign_account_type,
    can_assign_clearance_level,
    can_assign_group_paths,
    can_manage_group_path,
    can_manage_target_user,
    can_manage_users,
    filter_group_paths_for_user,
    is_global_admin,
)
from ...repositories.identity import GroupRecord, IdentityRepository, UserRecord
from ...schemas.admin import Group, UserAdmin


def require_admin_if_users_exist(request: Request, repo: IdentityRepository, sessions: RefreshSessionStore) -> UserRecord | None:
    if repo.count_users() == 0:
        return None
    user = require_current_user(request, repo, sessions)
    if not can_manage_users(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "user_manager_required", "message": "User management account type required."},
        )
    return user


def user_to_admin(user: UserRecord) -> UserAdmin:
    return UserAdmin(
        id=user.id,
        email=user.email,
        name=user.name,
        account_type=user.account_type,
        group_paths=list(user.group_paths),
        clearance_level=user.clearance_level,
        last_login_at=user.last_login_at,
        is_active=user.is_active,
        permission_version=user.permission_version,
    )


def group_to_schema(group: GroupRecord) -> Group:
    return Group(path=group.path, name=group.name)


def visible_groups_for_user(user: UserRecord, groups: list[GroupRecord]) -> list[GroupRecord]:
    if is_global_admin(user):
        return groups
    visible_paths = set(filter_group_paths_for_user(user, [group.path for group in groups]))
    return [group for group in groups if group.path in visible_paths]


def visible_users_for_manager(actor: UserRecord, users: list[UserRecord]) -> list[UserRecord]:
    if is_global_admin(actor):
        return users
    return [user for user in users if can_manage_target_user(actor, user)]


def require_can_manage_target_user(actor: UserRecord, target: UserRecord) -> None:
    if can_manage_target_user(actor, target):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "user_scope_forbidden", "message": "User is outside the manager's account type or Knowledge Space scope."},
    )


def require_can_assign_user(actor: UserRecord, account_type: str, group_paths: list[str], clearance_level: str) -> None:
    if (
        can_assign_account_type(actor, account_type)
        and can_assign_group_paths(actor, group_paths)
        and can_assign_clearance_level(actor, clearance_level)
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "user_assignment_forbidden", "message": "Account type or Knowledge Space assignment is outside the manager's scope."},
    )


def require_can_manage_group(actor: UserRecord, group_path: str) -> None:
    if can_manage_group_path(actor, group_path):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "group_scope_forbidden", "message": "Knowledge Space is outside the manager's scope."},
    )
