"""Authorization and scope validation for folder-ingestion schedules."""

from __future__ import annotations

from ...auth.abac import normalize_group_path
from ...auth.identity_models import IdentityRepository, UserRecord
from ...auth.permissions import (
    can_manage_group_path,
    can_manage_spaces,
    filter_group_paths_for_user,
    is_global_admin,
)
from ...shared.contracts.clearance import (
    can_access_clearance,
    clearance_rank,
    normalize_clearance_level,
)
from .errors import FolderIngestionRejected
from .models import FolderScheduleRecord, FolderScheduleRepository


def require_schedule_admin(user: UserRecord) -> None:
    if not can_manage_spaces(user):
        raise FolderIngestionRejected(
            category="forbidden",
            code="folder_schedule_admin_required",
            message=("Folder ingestion scheduling requires a platform or space admin."),
        )


def visible_schedules(
    user: UserRecord,
    schedules: list[FolderScheduleRecord],
) -> list[FolderScheduleRecord]:
    require_schedule_admin(user)
    if is_global_admin(user):
        return [
            schedule
            for schedule in schedules
            if can_access_clearance(user.clearance_level, schedule.clearance_level)
        ]
    visible_paths = set(
        filter_group_paths_for_user(
            user,
            [schedule.group_path for schedule in schedules],
        )
    )
    return [
        schedule
        for schedule in schedules
        if schedule.group_path in visible_paths
        and can_access_clearance(user.clearance_level, schedule.clearance_level)
    ]


def require_visible_schedule(
    user: UserRecord,
    schedule_repo: FolderScheduleRepository,
    schedule_id: str,
) -> FolderScheduleRecord:
    require_schedule_admin(user)
    schedule = schedule_repo.get_schedule(schedule_id)
    if schedule is None:
        raise FolderIngestionRejected(
            category="not_found",
            code="schedule_not_found",
            message="Folder schedule was not found.",
        )
    if not can_manage_group_path(user, schedule.group_path) or not can_access_clearance(
        user.clearance_level, schedule.clearance_level
    ):
        raise FolderIngestionRejected(
            category="forbidden",
            code="folder_schedule_forbidden",
            message=("Folder schedule is outside this user's Knowledge Space scope."),
        )
    return schedule

def require_folder_schedule_scope(
    user: UserRecord, group_path: str, identity_repo: IdentityRepository
) -> str:
    normalized = normalize_group_path(group_path)
    known = {group.path for group in identity_repo.list_groups()}
    if normalized not in known:
        raise FolderIngestionRejected(
            category="invalid",
            code="group_not_found",
            message="Folder schedule group does not exist.",
        )
    if not can_manage_group_path(user, normalized):
        raise FolderIngestionRejected(
            category="forbidden",
            code="folder_schedule_forbidden",
            message="User cannot manage folder ingestion for this Knowledge Space.",
        )
    return normalized


def require_folder_schedule_clearance(user: UserRecord, clearance_level: str) -> str:
    try:
        normalized = normalize_clearance_level(clearance_level)
    except ValueError as exc:
        raise FolderIngestionRejected(
            category="invalid",
            code="invalid_clearance_level",
            message=str(exc),
        ) from exc
    if clearance_rank(normalized) > clearance_rank(user.clearance_level):
        raise FolderIngestionRejected(
            category="forbidden",
            code="folder_schedule_clearance_forbidden",
            message="User cannot schedule ingestion above their clearance level.",
        )
    return normalized
