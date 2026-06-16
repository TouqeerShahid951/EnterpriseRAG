from types import SimpleNamespace

from rag.auth.permissions import (
    can_assign_account_type,
    can_manage_group_path,
    can_manage_spaces,
    can_manage_target_user,
    can_manage_users,
    can_manage_workspace_config,
    can_query,
    can_read_document_metadata,
    can_review,
    can_view_audit,
    can_write_document_scope,
    effective_clearance_level,
    filter_group_paths_for_user,
    is_global_admin,
)
from rag.shared.contracts.clearance import MAX_CLEARANCE_LEVEL


def test_system_admin_has_global_operational_permissions_without_config_access() -> None:
    user = _user("system_admin")

    assert is_global_admin(user)
    assert can_query(user)
    assert can_review(user)
    assert can_manage_users(user)
    assert can_manage_spaces(user)
    assert can_view_audit(user)
    assert can_read_document_metadata(user)
    assert can_write_document_scope(user, "/engineering")
    assert can_manage_group_path(user, "/engineering")
    assert not can_manage_workspace_config(user)
    assert effective_clearance_level("system_admin") == MAX_CLEARANCE_LEVEL
    assert filter_group_paths_for_user(user, ["/finance", "/engineering"]) == ["/engineering", "/finance"]


def test_system_admin_cannot_manage_or_assign_platform_admins() -> None:
    system_admin = _user("system_admin")

    assert not can_assign_account_type(system_admin, "platform_admin")
    assert can_assign_account_type(system_admin, "system_admin")
    assert can_manage_target_user(system_admin, _user("member"))
    assert not can_manage_target_user(system_admin, _user("platform_admin"))


def test_user_manager_cannot_assign_global_admin_roles() -> None:
    user_manager = _user("user_manager")

    assert not can_assign_account_type(user_manager, "platform_admin")
    assert not can_assign_account_type(user_manager, "system_admin")
    assert can_assign_account_type(user_manager, "space_admin")


def _user(account_type: str):
    return SimpleNamespace(
        account_type=account_type,
        group_paths=("/finance",),
        clearance_level=MAX_CLEARANCE_LEVEL,
    )
