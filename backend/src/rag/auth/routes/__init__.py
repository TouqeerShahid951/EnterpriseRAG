"""Authentication and identity administration HTTP routes."""

from fastapi import APIRouter

from . import admin_groups, admin_users, session

router = APIRouter()
router.include_router(session.router)
router.include_router(admin_groups.router)
router.include_router(admin_users.router)
