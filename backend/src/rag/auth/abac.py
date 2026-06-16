from typing import Any

from rag.shared.contracts.clearance import clearance_rank
from rag.shared.contracts.group_paths import normalize_group_path

from .context import UserContext


def build_abac_filter(user: UserContext, is_current_only: bool = True) -> dict[str, Any]:
    """Build the Qdrant filter used before any chunks leave vector storage."""
    if not isinstance(user, UserContext):
        raise TypeError("user must be a UserContext")
    if not isinstance(is_current_only, bool):
        raise TypeError("is_current_only must be a bool")

    user_group_paths = sorted({normalize_group_path(path) for path in user.group_paths})
    if not user_group_paths:
        return {
            "must": [
                {"key": "doc_id", "match": {"value": "__no_visible_docs__"}},
            ]
        }

    must: list[dict[str, Any]] = [
        {
            "should": [
                {"key": "group_path", "match": {"value": group_path}}
                for group_path in user_group_paths
            ]
        },
        {"key": "clearance_rank", "range": {"lte": clearance_rank(user.clearance_level)}},
    ]

    if is_current_only:
        must.append({"key": "is_current", "match": {"value": True}})
    return {"must": must}
