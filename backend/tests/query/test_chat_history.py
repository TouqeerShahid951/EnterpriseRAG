from __future__ import annotations

import unittest

from rag.query.adapters.chat_history_memory import InMemoryChatHistoryRepository
from rag.query.chat_history_models import ChatHistoryRequestConflict


class ChatHistoryRepositoryTests(unittest.TestCase):
    def test_list_sessions_paginates_summaries_without_full_turns(self) -> None:
        repo = InMemoryChatHistoryRepository()
        for index in range(5):
            repo.append_completed_turn(
                user_id="user-1",
                permission_version=1,
                session_id=f"session-{index}",
                title=f"Question {index}",
                user_turn={"id": f"user-{index}", "role": "user", "content": f"Question {index}", "createdAt": "2026-06-18T00:00:00Z"},
                assistant_turn={
                    "id": f"assistant-{index}",
                    "role": "assistant",
                    "status": "complete",
                    "question": f"Question {index}",
                    "createdAt": "2026-06-18T00:00:00Z",
                    "progress": [],
                },
            )

        first_page = repo.list_sessions(user_id="user-1", permission_version=1, limit=2, offset=0)
        second_page = repo.list_sessions(user_id="user-1", permission_version=1, limit=2, offset=2)
        final_page = repo.list_sessions(user_id="user-1", permission_version=1, limit=2, offset=4)
        first_page_with_total = repo.list_sessions_page(
            user_id="user-1",
            permission_version=1,
            limit=2,
            offset=0,
        )

        self.assertEqual(repo.count_sessions(user_id="user-1", permission_version=1), 5)
        self.assertEqual(first_page_with_total[1], 5)
        self.assertEqual(first_page_with_total[0], first_page)
        self.assertEqual(len(first_page), 2)
        self.assertEqual(len(second_page), 2)
        self.assertEqual(len(final_page), 1)
        self.assertTrue({session.id for session in first_page}.isdisjoint({session.id for session in second_page}))
        self.assertTrue(all(session.turns == () for session in [*first_page, *second_page, *final_page]))
        self.assertTrue(all(session.question_count == 1 for session in [*first_page, *second_page, *final_page]))

        full_session = repo.get_session(session_id=first_page[0].id, user_id="user-1", permission_version=1)
        self.assertIsNotNone(full_session)
        self.assertEqual(len(full_session.turns), 2)

    def test_recent_context_contains_only_complete_scoped_exchanges(self) -> None:
        repo = InMemoryChatHistoryRepository()
        for index in range(3):
            repo.append_completed_turn(
                user_id="user-1",
                permission_version=2,
                session_id="session-1",
                title="Policy",
                user_turn={
                    "role": "user",
                    "content": f"Question {index}",
                },
                assistant_turn={
                    "role": "assistant",
                    "response": {
                        "answer": f"Answer {index}",
                        "intent": "factual_simple",
                        "sources": [],
                    },
                },
            )

        assert repo.load_recent_context_turns(
            user_id="user-1",
            permission_version=2,
            session_id="session-1",
            limit=2,
        ) == [
            {
                "query": "Question 1",
                "answer": "Answer 1",
                "intent": "factual_simple",
                "sources": [],
                "source_mode": None,
                "source_decision_reason": None,
                "group_path": None,
                "document_ids": [],
                "query_source_id": None,
                "faithfulness_score": None,
                "faithfulness_status": None,
                "degraded": None,
            },
            {
                "query": "Question 2",
                "answer": "Answer 2",
                "intent": "factual_simple",
                "sources": [],
                "source_mode": None,
                "source_decision_reason": None,
                "group_path": None,
                "document_ids": [],
                "query_source_id": None,
                "faithfulness_score": None,
                "faithfulness_status": None,
                "degraded": None,
            },
        ]
        assert repo.load_recent_context_turns(
            user_id="user-1",
            permission_version=3,
            session_id="session-1",
        ) == []

    def test_duplicate_request_updates_one_assistant_turn(self) -> None:
        repo = InMemoryChatHistoryRepository()
        common = {
            "user_id": "user-1",
            "permission_version": 1,
            "session_id": "session-1",
            "title": "Policy",
            "user_turn": {"role": "user", "content": "Question"},
            "client_request_id": "request-1",
            "request_fingerprint": "fingerprint-1",
        }
        repo.append_completed_turn(
            **common,
            assistant_turn={"role": "assistant", "response": {"answer": "First"}},
        )
        session = repo.append_completed_turn(
            **common,
            assistant_turn={"role": "assistant", "response": {"answer": "Retried"}},
        )

        self.assertEqual(len(session.turns), 2)
        self.assertEqual(session.turns[1]["response"]["answer"], "Retried")

    def test_request_id_reuse_with_different_fingerprint_is_rejected(self) -> None:
        repo = InMemoryChatHistoryRepository()
        repo.append_completed_turn(
            user_id="user-1",
            permission_version=1,
            session_id="session-1",
            title="Policy",
            user_turn={"role": "user", "content": "Question"},
            assistant_turn={"role": "assistant", "response": {"answer": "First"}},
            client_request_id="request-1",
            request_fingerprint="fingerprint-1",
        )

        with self.assertRaises(ChatHistoryRequestConflict):
            repo.append_completed_turn(
                user_id="user-1",
                permission_version=1,
                session_id="session-1",
                title="Policy",
                user_turn={"role": "user", "content": "Different"},
                assistant_turn={"role": "assistant", "response": {"answer": "Other"}},
                client_request_id="request-1",
                request_fingerprint="fingerprint-2",
            )


if __name__ == "__main__":
    unittest.main()
