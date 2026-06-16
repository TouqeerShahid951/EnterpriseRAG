"""Admin route assembly."""

from __future__ import annotations

from fastapi import APIRouter

from . import admin_group_routes, admin_ingest_config_routes, admin_rag_config_routes, admin_user_routes

router = APIRouter()
router.include_router(admin_ingest_config_routes.router)
router.include_router(admin_rag_config_routes.router)
router.include_router(admin_group_routes.router)
router.include_router(admin_user_routes.router)
