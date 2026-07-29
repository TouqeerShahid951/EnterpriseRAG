from __future__ import annotations

import json
from time import perf_counter
from types import SimpleNamespace

from rag.auth.context import UserContext
from rag.query.adapters.chat_history_memory import InMemoryChatHistoryRepository
from rag.query.nodes.routing_nodes import RoutingNodes
from rag.query.routing.conversation_resolution import resolve_conversation
from rag.query.schemas import QueryRequest
from rag.query.state import initial_state


class ResolverClient:
    def __init__(self, payload: dict[str, object] | str) -> None:
        self.payload = payload
        self.prompts: list[str] = []
        self.calls: list[dict[str, object]] = []

    def generate_routing_json(
        self,
        *,
        prompt: str,
        model: str | None,
        system: str,
        max_tokens: int,
        timeout_seconds: float,
    ) -> str:
        self.prompts.append(prompt)
        self.calls.append(
            {
                "model": model,
                "system": system,
                "max_tokens": max_tokens,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.payload if isinstance(self.payload, str) else json.dumps(self.payload)


def test_self_contained_first_message_is_a_new_topic_without_model_call() -> None:
    client = ResolverClient("unused")

    result = resolve_conversation(
        "How do I reset MFA?",
        [],
        client=client,
        model="routing",
    )

    assert result.relation == "new_topic"
    assert result.effective_query == "How do I reset MFA?"
    assert result.method == "rules"
    assert client.prompts == []


def test_referential_message_without_history_asks_for_clarification() -> None:
    client = ResolverClient("unused")
    result = resolve_conversation(
        "Why?",
        [],
        client=client,
        model="routing",
    )

    assert result.relation == "ambiguous"
    assert result.clarification_question == "What topic or earlier answer are you referring to?"
    assert client.prompts == []


def test_uppercase_it_without_history_is_not_mistaken_for_a_pronoun() -> None:
    client = ResolverClient("unused")

    result = resolve_conversation(
        "What is the IT policy?",
        [],
        client=client,
        model="routing",
    )

    assert result.relation == "new_topic"
    assert result.effective_query == "What is the IT policy?"
    assert client.prompts == []


def test_relative_pronoun_without_history_does_not_force_clarification() -> None:
    client = ResolverClient("unused")

    result = resolve_conversation(
        "Which policies cover employees that travel?",
        [],
        client=client,
        model="routing",
    )

    assert result.relation == "new_topic"
    assert result.effective_query == "Which policies cover employees that travel?"
    assert client.prompts == []


def test_follow_up_uses_user_and_assistant_context_to_build_standalone_query() -> None:
    client = ResolverClient(
        {
            "relation": "follow_up",
            "standalone_query": "Why does the parental leave policy exclude contractors?",
            "antecedent_turn_ids": ["recent-1"],
            "clarification_question": None,
        }
    )

    result = resolve_conversation(
        "Why?",
        [
            {
                "query": "Does parental leave apply to contractors?",
                "answer": "The policy applies only to employees.",
            }
        ],
        client=client,
        model="routing",
    )

    assert result.relation == "follow_up"
    assert result.effective_query == (
        "Why does the parental leave policy exclude contractors?"
    )
    assert result.antecedent_turn_ids == ("recent-1",)
    assert "The policy applies only to employees." in client.prompts[0]
    assert client.calls[0]["timeout_seconds"] == 10.0
    assert client.calls[0]["max_tokens"] == 512


def test_self_contained_new_topic_with_history_is_confirmed_without_rewriting() -> None:
    client = ResolverClient("unused")
    result = resolve_conversation(
        "How do I reset MFA?",
        [{"query": "What is parental leave?", "answer": "Leave policy."}],
        client=client,
        model="routing",
    )

    assert result.relation == "new_topic"
    assert result.effective_query == "How do I reset MFA?"
    assert result.method == "rules"
    assert client.prompts == []


def test_relative_pronoun_with_history_does_not_trigger_resolution() -> None:
    client = ResolverClient("unused")

    result = resolve_conversation(
        "Which policies cover employees that travel?",
        [{"query": "What is parental leave?", "answer": "Leave policy."}],
        client=client,
        model="routing",
    )

    assert result.relation == "new_topic"
    assert result.method == "rules"
    assert client.prompts == []


def test_short_question_with_named_topic_skips_resolution() -> None:
    client = ResolverClient("unused")

    result = resolve_conversation(
        "Where is Karachi?",
        [{"query": "What is parental leave?", "answer": "Leave policy."}],
        client=client,
        model="routing",
    )

    assert result.relation == "new_topic"
    assert result.method == "rules"
    assert client.prompts == []


def test_uncertain_fragments_with_history_use_resolution_model() -> None:
    for query in (
        "Does that apply to contractors?",
        "Do the same for Europe",
        "Now for Europe",
        "In 2025?",
        "Only contractors",
        "The second one",
        "What happened then?",
        "What are the exceptions?",
        "Does the policy still apply?",
    ):
        client = ResolverClient(
            {
                "relation": "ambiguous",
                "standalone_query": "",
                "antecedent_turn_ids": ["recent-1"],
                "clarification_question": "Which earlier topic are you referring to?",
            }
        )

        result = resolve_conversation(
            query,
            [{"query": "Explain parental leave.", "answer": "Leave policy."}],
            client=client,
            model="routing",
        )

        assert result.method == "ai_assisted", query
        assert len(client.prompts) == 1, query


def test_explicit_document_scope_resolves_this_document_without_history_model() -> None:
    client = ResolverClient("unused")

    result = resolve_conversation(
        "Summarize this document",
        [{"query": "What is parental leave?", "answer": "Leave policy."}],
        client=client,
        model="routing",
        has_explicit_scope=True,
    )

    assert result.relation == "new_topic"
    assert result.method == "rules"
    assert client.prompts == []


def test_implicit_ellipsis_with_history_still_uses_model() -> None:
    client = ResolverClient(
        {
            "relation": "follow_up",
            "standalone_query": "What is the parental leave retention period?",
            "antecedent_turn_ids": ["recent-1"],
            "clarification_question": None,
        }
    )

    result = resolve_conversation(
        "What is the retention period?",
        [{"query": "Explain the parental leave records policy.", "answer": "Policy."}],
        client=client,
        model="routing",
    )

    assert result.relation == "follow_up"
    assert result.effective_query == "What is the parental leave retention period?"
    assert len(client.prompts) == 1


def test_pronoun_follow_up_with_history_still_uses_model() -> None:
    client = ResolverClient(
        {
            "relation": "follow_up",
            "standalone_query": "What government position did Shirley Temple hold?",
            "antecedent_turn_ids": ["recent-1"],
            "clarification_question": None,
        }
    )

    result = resolve_conversation(
        "What government position did she hold?",
        [{"query": "Who was Shirley Temple?", "answer": "An actor and diplomat."}],
        client=client,
        model="routing",
    )

    assert result.relation == "follow_up"
    assert result.method == "ai_assisted"
    assert len(client.prompts) == 1


def test_invalid_model_output_fails_safe_for_referential_message() -> None:
    result = resolve_conversation(
        "Tell me more",
        [{"query": "What is parental leave?", "answer": "Leave policy."}],
        client=ResolverClient("not-json"),
        model="routing",
    )

    assert result.relation == "ambiguous"
    assert result.method == "fallback"


def test_multiple_possible_antecedents_ask_one_targeted_question() -> None:
    result = resolve_conversation(
        "Why?",
        [
            {"query": "Does parental leave cover contractors?", "answer": "No."},
            {"query": "Is the retention period seven years?", "answer": "Yes."},
        ],
        client=ResolverClient(
            {
                "relation": "ambiguous",
                "standalone_query": "",
                "antecedent_turn_ids": ["recent-1", "recent-2"],
                "clarification_question": (
                    "Are you asking why contractors are excluded or why retention is seven years?"
                ),
            }
        ),
        model="routing",
    )

    assert result.relation == "ambiguous"
    assert result.method == "ai_assisted"
    assert result.antecedent_turn_ids == ("recent-1", "recent-2")
    assert "contractors" in (result.clarification_question or "")


def test_unavailable_antecedent_id_fails_safe() -> None:
    result = resolve_conversation(
        "Tell me more",
        [{"query": "What is parental leave?", "answer": "Leave policy."}],
        client=ResolverClient(
            {
                "relation": "follow_up",
                "standalone_query": "Explain the parental leave policy in more detail.",
                "antecedent_turn_ids": ["missing-turn"],
                "clarification_question": None,
            }
        ),
        model="routing",
    )

    assert result.relation == "ambiguous"
    assert result.method == "fallback"


def test_invalid_model_output_does_not_block_a_self_contained_query() -> None:
    result = resolve_conversation(
        "How do I reset MFA?",
        [{"query": "What is parental leave?", "answer": "Leave policy."}],
        client=ResolverClient("not-json"),
        model="routing",
    )

    assert result.relation == "new_topic"
    assert result.effective_query == "How do I reset MFA?"
    assert result.method == "rules"


def test_rewrite_with_an_invented_value_fails_safe() -> None:
    result = resolve_conversation(
        "What about 2025?",
        [
            {
                "query": "What changed in the parental leave policy?",
                "answer": "The 2024 policy changed eligibility.",
            }
        ],
        client=ResolverClient(
            {
                "relation": "follow_up",
                "standalone_query": "What changed in the parental leave policy in 2025 and 2026?",
                "antecedent_turn_ids": ["recent-1"],
                "clarification_question": None,
            }
        ),
        model="routing",
    )

    assert result.relation == "ambiguous"
    assert result.method == "fallback"


def test_rewrite_with_an_invented_entity_fails_safe() -> None:
    result = resolve_conversation(
        "What about contractors?",
        [{"query": "Who receives parental leave?", "answer": "Employees."}],
        client=ResolverClient(
            {
                "relation": "follow_up",
                "standalone_query": "Does Acme provide parental leave to contractors?",
                "antecedent_turn_ids": ["recent-1"],
                "clarification_question": None,
            }
        ),
        model="routing",
    )

    assert result.relation == "ambiguous"
    assert result.method == "fallback"


def test_routing_node_loads_saved_history_before_resolving_follow_up() -> None:
    history = InMemoryChatHistoryRepository()
    history.append_completed_turn(
        user_id="user-1",
        permission_version=2,
        session_id="session-1",
        title="Leave",
        user_turn={
            "id": "user-turn-1",
            "role": "user",
            "content": "What is parental leave?",
        },
        assistant_turn={
            "role": "assistant",
            "response": {
                "answer": "Employees receive parental leave.",
                "sources": [],
            },
        },
    )
    client = ResolverClient(
        {
            "relation": "follow_up",
            "standalone_query": "Does parental leave apply to contractors?",
            "antecedent_turn_ids": ["user-turn-1"],
            "clarification_question": None,
        }
    )
    node = SimpleNamespace(
        chat_history_repo=history,
        ollama=client,
        routing_model="routing",
    )
    ctx = initial_state(
        trace_id="trace",
        session_id="session-1",
        request=QueryRequest(query="What about contractors?", session_id="session-1"),
        user=UserContext(
            user_id="user-1",
            email="user@example.test",
            group_paths=("/ops",),
            permission_version=2,
        ),
        started=perf_counter(),
    )

    RoutingNodes.session_memory(node, ctx)
    RoutingNodes.conversation_resolver(node, ctx)

    assert ctx["session_turns"][0]["answer"] == "Employees receive parental leave."
    assert ctx["session_turns"][0]["turn_id"] == "user-turn-1"
    assert ctx["effective_query"] == "Does parental leave apply to contractors?"
    assert ctx["conversation_resolution"].relation == "follow_up"
