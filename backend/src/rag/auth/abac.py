from typing import Any

from rag.shared.contracts.clearance import clearance_rank
from rag.shared.contracts.group_paths import normalize_group_path
from rag.shared.contracts.abbreviations import ABBREVIATION_GLOSSARY_DOC_TYPE

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
            ],
            "must_not": [_glossary_document_condition()],
        }

    must: list[dict[str, Any]] = [
        {
            "should": [
                matcher
                for group_path in user_group_paths
                for matcher in (
                    {"key": "acl_group_paths", "match": {"value": group_path}},
                    {"key": "group_path", "match": {"value": group_path}},
                )
            ]
        },
        {"key": "clearance_rank", "range": {"lte": clearance_rank(user.clearance_level)}},
    ]

    if is_current_only:
        must.append({"key": "is_current", "match": {"value": True}})
    return {"must": must, "must_not": [_glossary_document_condition()]}


def _glossary_document_condition() -> dict[str, Any]:
    return {
        "key": "doc_type",
        "match": {"value": ABBREVIATION_GLOSSARY_DOC_TYPE},
    }
