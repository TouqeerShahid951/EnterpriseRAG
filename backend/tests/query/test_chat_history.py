from __future__ import annotations

import unittest

from rag.query.adapters.chat_history_memory import InMemoryChatHistoryRepository


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

        self.assertEqual(repo.count_sessions(user_id="user-1", permission_version=1), 5)
        self.assertEqual(len(first_page), 2)
        self.assertEqual(len(second_page), 2)
        self.assertEqual(len(final_page), 1)
        self.assertTrue({session.id for session in first_page}.isdisjoint({session.id for session in second_page}))
        self.assertTrue(all(session.turns == () for session in [*first_page, *second_page, *final_page]))
        self.assertTrue(all(session.question_count == 1 for session in [*first_page, *second_page, *final_page]))

        full_session = repo.get_session(session_id=first_page[0].id, user_id="user-1", permission_version=1)
        self.assertIsNotNone(full_session)
        self.assertEqual(len(full_session.turns), 2)


if __name__ == "__main__":
    unittest.main()
