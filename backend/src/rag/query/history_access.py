"""Apply current source access to saved answers and conversation context."""

from pydantic import ValidationError

from rag.auth.context import UserContext
from rag.documents.models import DocumentRepository
from rag.shared.contracts.evidence import SourceAnchor
from .source_revision import sources_still_available

UNAVAILABLE_HISTORY = "The cited sources for this saved answer are no longer available."


def context_is_available(
    turn: dict, *, user: UserContext, documents: DocumentRepository | None
) -> bool:
    raw_sources = turn.get("sources", [])
    if not isinstance(raw_sources, list):
        return False
    try:
        sources = [SourceAnchor.model_validate(source) for source in raw_sources]
    except (ValidationError, TypeError):
        return False
    return sources_still_available(sources, user=user, documents=documents)


def visible_history_turns(
    turns, *, user: UserContext, documents: DocumentRepository
) -> list[dict]:
    visible = []
    for turn in turns:
        response = turn.get("response")
        if isinstance(response, dict) and not context_is_available(
            response, user=user, documents=documents
        ):
            turn = {
                **turn,
                "response": {
                    **response,
                    "answer": UNAVAILABLE_HISTORY,
                    "sources": [],
                    "conflict_detail": None,
                    "conflict_flag": False,
                    "unfounded_claims": [],
                    "citation_verification": None,
                    "faithfulness_status": "skipped",
                    "faithfulness_score": 0,
                    "degraded": True,
                    "degraded_reason": "source_revision_unavailable",
                    "answer_status": "partial",
                },
            }
        visible.append(turn)
    return visible
