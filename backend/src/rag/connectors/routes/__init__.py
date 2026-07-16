"""Connector HTTP route assembly."""

from __future__ import annotations

from fastapi import APIRouter

from . import catalogs as _catalog_routes
from . import enrichment as _enrichment_routes
from . import presenters as _http_presenters
from . import profiles as _profile_routes
from . import support as _route_support

router = APIRouter()
router.include_router(_profile_routes.router)
router.include_router(_catalog_routes.router)
router.include_router(_enrichment_routes.router)

# Keep direct imports stable while the connector feature owns the implementations.
SchemaEnrichmentRuntime = _enrichment_routes.SchemaEnrichmentRuntime
get_schema_enrichment_runtime = _enrichment_routes.get_schema_enrichment_runtime
list_connector_profiles = _profile_routes.list_connector_profiles
create_connector_profile = _profile_routes.create_connector_profile
update_connector_profile = _profile_routes.update_connector_profile
delete_connector_profile = _profile_routes.delete_connector_profile
test_connector_profile = _profile_routes.test_connector_profile
introspect_connector_profile = _profile_routes.introspect_connector_profile
list_connector_schema_catalogs = _catalog_routes.list_connector_schema_catalogs
create_connector_schema_catalog = _catalog_routes.create_connector_schema_catalog
create_ai_schema_catalog_draft = _enrichment_routes.create_ai_schema_catalog_draft
enrich_connector_schema_catalog_table = (
    _enrichment_routes.enrich_connector_schema_catalog_table
)
update_connector_schema_catalog = _catalog_routes.update_connector_schema_catalog

_require_connector_admin = _route_support.require_connector_admin
_require_profile = _route_support.require_profile
_current_schema_catalog = _route_support.current_schema_catalog
_current_schema_catalogs = _route_support.current_schema_catalogs
_validated_catalog_access_group_paths = (
    _route_support.validated_catalog_access_group_paths
)
_update_schema_catalog_or_404 = _route_support.update_schema_catalog_or_404
_profile_to_schema = _http_presenters.profile_to_schema
_schema_to_response = _http_presenters.schema_to_response
_catalog_to_schema = _http_presenters.catalog_to_schema
_secrets = _route_support.secrets
_keyring = _route_support.keyring

__all__ = [
    "SchemaEnrichmentRuntime",
    "create_ai_schema_catalog_draft",
    "create_connector_profile",
    "create_connector_schema_catalog",
    "delete_connector_profile",
    "enrich_connector_schema_catalog_table",
    "get_schema_enrichment_runtime",
    "introspect_connector_profile",
    "list_connector_profiles",
    "list_connector_schema_catalogs",
    "router",
    "test_connector_profile",
    "update_connector_profile",
    "update_connector_schema_catalog",
]
