"""Public HTTP route for query source discovery."""

from fastapi import APIRouter, Depends, Query

from ..auth.dependencies import require_current_user
from ..auth.identity_models import IdentityRepository, UserRecord
from ..auth.identity_repository import get_identity_repository
from ..connectors.repositories import (
    ConnectorProfileRepository,
    get_connector_profile_repository,
)
from ..ingestion.folders.dependencies import get_folder_schedule_repository
from ..ingestion.folders.models import FolderScheduleRepository
from .route_access import (
    require_query_user,
    user_context,
    validated_query_group_path,
)
from .schemas import QuerySourceListResponse
from .source_resolution import list_visible_query_sources, public_query_source


router = APIRouter()


@router.get(
    "/sources",
    response_model=QuerySourceListResponse,
    summary="List visible approved query sources for source-scoped chat",
)
async def list_query_sources(
    group_path: str | None = Query(default=None, min_length=1),
    user: UserRecord = Depends(require_current_user),
    identity_repo: IdentityRepository = Depends(get_identity_repository),
    schedule_repo: FolderScheduleRepository = Depends(get_folder_schedule_repository),
    connector_profile_repo: ConnectorProfileRepository = Depends(
        get_connector_profile_repository
    ),
) -> QuerySourceListResponse:
    require_query_user(user)
    group_path = validated_query_group_path(group_path, user, identity_repo)
    scoped_user = user_context(user, identity_repo)
    if group_path:
        scoped_user = scoped_user.__class__(
            user_id=scoped_user.user_id,
            email=scoped_user.email,
            account_type=scoped_user.account_type,
            group_paths=(group_path,),
            clearance_level=scoped_user.clearance_level,
            permission_version=scoped_user.permission_version,
        )
    sources = list_visible_query_sources(
        scoped_user,
        schedule_repo=schedule_repo,
        connector_profile_repo=connector_profile_repo,
    )
    return QuerySourceListResponse(
        items=[public_query_source(source) for source in sources],
        total=len(sources),
    )
