"""First-deployment platform administrator bootstrap."""

from __future__ import annotations

import logging

from ..auth.passwords import hash_password
from ..auth.identity_models import IdentityRepository, UserRecord


logger = logging.getLogger(__name__)


def ensure_initial_platform_admin(
    repo: IdentityRepository,
    *,
    email: str,
    name: str,
    password: str,
) -> UserRecord | None:
    if repo.count_users() != 0:
        return None

    created = repo.create_initial_admin_if_empty(
        email=email,
        name=name,
        password_hash=hash_password(password),
    )
    if created is not None:
        logger.info("Created initial platform administrator account for %s.", created.email)
    return created
