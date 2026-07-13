"""AI-assisted connector schema catalog enrichment routes."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..auth.dependencies import require_csrf, require_current_user
from ..auth.identity_models import IdentityRepository, UserRecord
from ..auth.identity_repository import get_identity_repository
from ..core.config import settings
from ..query.inference import build_inference_client
from ..query.rag_config_repository import effective_rag_config
from ..schemas.connectors import (
    ConnectorSchemaCatalog,
    ConnectorSchemaCatalogAiDraftRequest,
    ConnectorSchemaCatalogTableEnrichRequest,
)
from .http_presenters import catalog_to_schema
from .repositories import ConnectorProfileRepository, get_connector_profile_repository
from .route_support import (
    current_schema_catalog,
    require_connector_admin,
    require_profile,
    update_schema_catalog_or_404,
    validated_catalog_access_group_paths,
)
from .schema_catalog import (
    build_default_schema_catalog,
    schema_catalog_with_shared_group_paths,
)
from .schema_enrichment import (
    SchemaEnrichmentError,
    enrich_schema_table_with_llm,
    initialize_schema_catalog_enrichment,
    schema_catalog_table_keys,
    schema_catalog_with_table_enrichment_failure,
)

router = APIRouter(prefix="/connectors", tags=["connectors"])
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SchemaEnrichmentRuntime:
    llm: object
    model: str | None


def get_schema_enrichment_runtime() -> SchemaEnrichmentRuntime:
    rag_config = effective_rag_config(config=settings)
    return SchemaEnrichmentRuntime(
        llm=build_inference_client(rag_config, settings=settings),
        model=rag_config.effective_reasoning_model or rag_config.chat_model,
    )


@router.post(
    "/profiles/{profile_id}/schema-catalogs/ai-draft",
    status_code=status.HTTP_201_CREATED,
    response_model=ConnectorSchemaCatalog,
    summary="Create an AI-enriched draft schema catalog for admin review",
)
def create_ai_schema_catalog_draft(
    profile_id: str,
    request: Request,
    payload: ConnectorSchemaCatalogAiDraftRequest,
    user: UserRecord = Depends(require_current_user),
    repo: ConnectorProfileRepository = Depends(get_connector_profile_repository),
    identity_repo: IdentityRepository = Depends(get_identity_repository),
) -> ConnectorSchemaCatalog:
    require_csrf(request)
    require_connector_admin(user)
    profile = require_profile(repo, profile_id)
    snapshot = repo.latest_introspection(profile_id)
    if snapshot is None or snapshot.status != "ok":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "connector_schema_snapshot_required",
                "message": "Run connector introspection before creating an AI schema draft.",
            },
        )
    catalog_json = initialize_schema_catalog_enrichment(
        build_default_schema_catalog(snapshot.schema_json)
    )
    current = current_schema_catalog(repo.list_schema_catalogs(profile_id))
    access_group_paths = validated_catalog_access_group_paths(
        payload.group_path,
        payload.group_paths,
        current=current,
        user=user,
        identity_repo=identity_repo,
    )
    catalog_json = schema_catalog_with_shared_group_paths(
        catalog_json,
        access_group_paths[1:],
    )
    if current is not None:
        catalog = update_schema_catalog_or_404(
            repo,
            current.id,
            catalog_json=catalog_json,
            status="draft",
            group_path=access_group_paths[0],
            clearance_level=payload.clearance_level,
            approved_by=None,
        )
    else:
        catalog = repo.save_schema_catalog(
            profile_id=profile.id,
            connector_type=profile.connector_type,
            catalog_json=catalog_json,
            status="draft",
            group_path=access_group_paths[0],
            clearance_level=payload.clearance_level,
            created_by=user.id,
            approved_by=None,
        )
    return catalog_to_schema(catalog)


@router.post(
    "/profiles/{profile_id}/schema-catalogs/{catalog_id}/ai-enrich-table",
    response_model=ConnectorSchemaCatalog,
    summary="Enrich one table in a draft schema catalog",
)
def enrich_connector_schema_catalog_table(
    profile_id: str,
    catalog_id: str,
    request: Request,
    payload: ConnectorSchemaCatalogTableEnrichRequest,
    user: UserRecord = Depends(require_current_user),
    repo: ConnectorProfileRepository = Depends(get_connector_profile_repository),
    runtime: SchemaEnrichmentRuntime = Depends(get_schema_enrichment_runtime),
) -> ConnectorSchemaCatalog:
    require_csrf(request)
    require_connector_admin(user)
    profile = require_profile(repo, profile_id)
    current = repo.get_schema_catalog(catalog_id)
    if current is None or current.profile_id != profile_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "connector_schema_catalog_not_found",
                "message": "Connector schema catalog was not found.",
            },
        )
    if current.status not in {"draft", "reviewed"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "connector_schema_catalog_not_editable",
                "message": "Only draft or reviewed catalogs can be AI-enriched.",
            },
        )
    if payload.table_key.strip().lower() not in schema_catalog_table_keys(
        current.catalog_json
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "connector_schema_table_not_found",
                "message": "The requested table is not part of this schema catalog.",
            },
        )
    try:
        catalog_json = enrich_schema_table_with_llm(
            current.catalog_json,
            table_key=payload.table_key,
            connector_type=profile.connector_type,
            profile_name=profile.name,
            llm=runtime.llm,
            model=runtime.model,
        )
    except SchemaEnrichmentError as exc:
        logger.info(
            "Schema table enrichment failed for catalog %s table %s: %s",
            current.id,
            payload.table_key,
            exc,
        )
        catalog_json = schema_catalog_with_table_enrichment_failure(
            current.catalog_json,
            table_key=payload.table_key,
            error_message=str(exc) or "Schema table enrichment failed.",
        )
    except Exception:
        logger.exception(
            "Schema table enrichment failed for catalog %s table %s",
            current.id,
            payload.table_key,
        )
        catalog_json = schema_catalog_with_table_enrichment_failure(
            current.catalog_json,
            table_key=payload.table_key,
            error_message="Schema table enrichment failed.",
        )
    updated = repo.update_schema_catalog(catalog_id, catalog_json=catalog_json)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "connector_schema_catalog_not_found",
                "message": "Connector schema catalog was not found.",
            },
        )
    return catalog_to_schema(updated)
