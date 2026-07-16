"""Aggregate public query HTTP routes in their compatibility order."""

from fastapi import APIRouter

from . import execution_routes, history_routes
from .sources import source_routes


router = APIRouter(tags=["query"])
router.include_router(history_routes.session_list_router, prefix="/query")
router.include_router(source_routes.router, prefix="/query")
router.include_router(history_routes.session_detail_router, prefix="/query")
router.include_router(execution_routes.router, prefix="/query")
