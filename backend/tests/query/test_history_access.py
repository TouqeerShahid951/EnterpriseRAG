from types import SimpleNamespace
from unittest.mock import Mock

from rag.auth.context import UserContext
from rag.query.history_access import (
    context_is_available,
    visible_history_turns,
    UNAVAILABLE_HISTORY,
)


def test_revoked_saved_evidence_is_removed_from_ui_and_conversation_context():
    user = UserContext(user_id="user", email="user@test.com", group_paths=("/allowed",))
    source = {
        "doc_id": "doc",
        "chunk_id": "doc:1",
        "doc_title": "Private document",
        "excerpt": "Private passage",
        "group_path": "/allowed",
    }
    response = {"answer": "Private fact", "sources": [source]}
    repo = Mock(
        get_document=Mock(
            return_value=SimpleNamespace(
                access_group_paths=("/revoked",), clearance_level="NATO_UNCLASSIFIED"
            )
        )
    )
    assert not context_is_available(response, user=user, documents=repo)
    saved = [{"role": "assistant", "response": response}]
    visible = visible_history_turns(saved, user=user, documents=repo)
    assert visible[0]["response"]["answer"] == UNAVAILABLE_HISTORY
    assert visible[0]["response"]["sources"] == []
    assert saved[0]["response"]["answer"] == "Private fact"
