from __future__ import annotations

import json
from time import perf_counter
from types import SimpleNamespace

from rag.auth.context import UserContext
from rag.query.adapters.chat_history_memory import InMemoryChatHistoryRepository
from rag.query.http import ServiceRequestError
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
        timeout_seconds: float | None = None,
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
        return _model_output(self.payload)


class FailIfCalledResolverClient:
    def generate_routing_json(self, **kwargs) -> str:
        _ = kwargs
        raise AssertionError("standalone query unexpectedly invoked the resolver")


class TimeoutResolverClient:
    def generate_routing_json(self, **kwargs) -> str:
        _ = kwargs
        try:
            raise TimeoutError("routing deadline exceeded")
        except TimeoutError as exc:
            raise ServiceRequestError("routing", "request failed") from exc


def _model_output(payload: dict[str, object] | str) -> str:
    if isinstance(payload, str):
        return payload
    normalized = dict(payload)
    relation = normalized.get("relation")
    normalized.setdefault(
        "dependency_targets",
        ["query"] if relation in {"follow_up", "ambiguous"} else [],
    )
    normalized.setdefault("ambiguity_candidates", [])
    return json.dumps(normalized)


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


def test_unresolved_pronoun_without_history_asks_for_clarification() -> None:
    client = ResolverClient("unused")

    result = resolve_conversation(
        "What did she do?",
        [],
        client=client,
        model="routing",
    )

    assert result.relation == "ambiguous"
    assert result.decision_reason == "rules_missing_history"
    assert client.prompts == []


def test_explicit_document_scope_resolves_without_history_or_model() -> None:
    client = ResolverClient("unused")

    result = resolve_conversation(
        "Summarize this document",
        [],
        client=client,
        model="routing",
        has_explicit_scope=True,
    )

    assert result.relation == "new_topic"
    assert result.decision_reason == "rules_explicit_scope"
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
    assert client.calls[0]["timeout_seconds"] is None
    assert client.calls[0]["max_tokens"] == 512
    assert result.decision_reason == "ai_valid"
    assert result.model_attempt_count == 1


def test_clarification_selection_preserves_the_pending_question_intent() -> None:
    client = ResolverClient(
        {
            "relation": "follow_up",
            "standalone_query": "How can Touqeer exit the job offered to him?",
            "antecedent_turn_ids": ["turn-3"],
            "clarification_question": None,
        }
    )

    result = resolve_conversation(
        "Touqeer's job mentioned in turn 3",
        [
            {
                "turn_id": "turn-2",
                "query": "Who is Touqeer?",
                "answer": "Touqeer was offered a Jnr. Data Engineer role.",
            },
            {
                "turn_id": "turn-3",
                "query": "How can he exit this contract or job?",
                "answer": (
                    "Which do you mean: the employment contract or Touqeer's job offer?"
                ),
            },
        ],
        client=client,
        model="routing",
    )

    assert result.effective_query == "How can Touqeer exit the job offered to him?"
    assert "Which do you mean" in client.prompts[0]
    assert "preserve the intent of the preceding user question" in client.prompts[0]


def test_unique_context_dependencies_rewrite_without_clarification() -> None:
    cases = (
        (
            "What does it cover?",
            "Explain HR Policy 2026.",
            "HR Policy 2026 covers annual leave.",
            "What does HR Policy 2026 cover?",
            ["query", "answer"],
        ),
        (
            "What happened there?",
            "Where was the incident?",
            "The incident happened in Karachi.",
            "What happened in Karachi?",
            ["answer"],
        ),
        (
            "What changed then?",
            "When was the policy revised?",
            "The policy was revised in 2025.",
            "What changed in the policy in 2025?",
            ["query", "answer"],
        ),
        (
            "Show the second one",
            "Which projects are available?",
            "The available projects are Alpha and Beta.",
            "Show project Beta",
            ["answer", "result"],
        ),
        (
            "Only Islamabad",
            "Show all active contracts.",
            "There are active contracts in Islamabad and Karachi.",
            "Show only active contracts in Islamabad.",
            ["query", "result"],
        ),
    )

    for current, previous_query, previous_answer, standalone, dependencies in cases:
        client = ResolverClient(
            {
                "relation": "follow_up",
                "standalone_query": standalone,
                "antecedent_turn_ids": ["recent-1"],
                "dependency_targets": dependencies,
                "ambiguity_candidates": [],
                "clarification_question": None,
            }
        )

        result = resolve_conversation(
            current,
            [{"query": previous_query, "answer": previous_answer}],
            client=client,
            model="routing",
        )

        assert result.relation == "follow_up", current
        assert result.effective_query == standalone, current
        assert result.dependency_targets == tuple(dependencies), current


def test_single_ambiguity_candidate_fails_safe_without_retry() -> None:
    client = ResolverClient(
        {
            "relation": "ambiguous",
            "standalone_query": "",
            "antecedent_turn_ids": ["recent-1"],
            "dependency_targets": ["query", "answer"],
            "ambiguity_candidates": ["Touqeer Shahid Abbasi"],
            "clarification_question": "Who does he refer to?",
        }
    )

    result = resolve_conversation(
        "How can he exit this contract or job?",
        [
            {
                "query": "Who is Touqeer?",
                "answer": (
                    "Touqeer Shahid Abbasi is the employee named in the employment contract."
                ),
            }
        ],
        client=client,
        model="routing",
    )

    assert result.relation == "ambiguous"
    assert result.method == "fallback"
    assert result.fallback_error_code == "invalid_output"
    assert len(client.calls) == 1


def test_rewrite_that_drops_a_constraint_fails_safe_without_retry() -> None:
    client = ResolverClient(
        {
            "relation": "follow_up",
            "standalone_query": "Show active contracts from 2025.",
            "antecedent_turn_ids": ["recent-1"],
            "dependency_targets": ["query", "result"],
            "ambiguity_candidates": [],
            "clarification_question": None,
        }
    )

    result = resolve_conversation(
        "Before 2025",
        [
            {
                "query": "Show all active contracts.",
                "answer": "There are active contracts from 2024 and 2025.",
            }
        ],
        client=client,
        model="routing",
    )

    assert result.relation == "ambiguous"
    assert result.method == "fallback"
    assert result.fallback_error_code == "invalid_output"
    assert len(client.calls) == 1


def test_rewrite_that_drops_the_requested_action_fails_safe() -> None:
    result = resolve_conversation(
        "How can he exit this contract or job?",
        [
            {
                "query": "Who is Touqeer?",
                "answer": (
                    "Touqeer Shahid Abbasi is the employee named in the employment contract."
                ),
            }
        ],
        client=ResolverClient(
            {
                "relation": "follow_up",
                "standalone_query": "What is Touqeer Shahid Abbasi's job?",
                "antecedent_turn_ids": ["recent-1"],
                "dependency_targets": ["query", "answer"],
                "ambiguity_candidates": [],
                "clarification_question": None,
            }
        ),
        model="routing",
    )

    assert result.relation == "ambiguous"
    assert result.method == "fallback"


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


def test_prefaced_standalone_requests_do_not_invoke_conversation_resolution() -> None:
    history = [{"query": "What is parental leave?", "answer": "Leave policy."}]
    queries = (
        (
            "According to the Samsung repair manual, what precautions should be "
            "followed when using a suction cup?"
        ),
        (
            "Based on the Samsung repair manual, what precautions should be "
            "followed when using a suction cup?"
        ),
        "Regarding Samsung repair procedures, explain the suction-cup precautions.",
        "Please explain the suction-cup precautions in the Samsung repair manual.",
    )

    for query in queries:
        result = resolve_conversation(
            query,
            history,
            client=FailIfCalledResolverClient(),
            model="routing",
        )

        assert result.relation == "new_topic", query
        assert result.effective_query == query, query
        assert result.method == "rules", query
        assert result.decision_reason == "rules_self_contained", query
        assert result.model_attempt_count == 0, query


def test_prefaced_history_references_still_use_conversation_resolution() -> None:
    history = [{"query": "Explain suction cups.", "answer": "Use them carefully."}]
    queries = (
        "According to what you said earlier, what precautions should be followed?",
        "In turn 3, what precautions should be followed?",
        "Regarding that, what precautions should be followed?",
    )

    for query in queries:
        client = ResolverClient(
            {
                "relation": "ambiguous",
                "standalone_query": "",
                "antecedent_turn_ids": ["recent-1"],
                "clarification_question": "Which earlier guidance do you mean?",
            }
        )

        result = resolve_conversation(
            query,
            history,
            client=client,
            model="routing",
        )

        assert result.relation == "ambiguous", query
        assert result.method == "ai_assisted", query
        assert result.model_attempt_count == 1, query
        assert len(client.calls) == 1, query


def test_short_request_without_a_local_topic_still_uses_resolution() -> None:
    client = ResolverClient(
        {
            "relation": "follow_up",
            "standalone_query": "What changed in the parental leave policy in 2025?",
            "antecedent_turn_ids": ["recent-1"],
            "clarification_question": None,
        }
    )

    result = resolve_conversation(
        "In 2025, what changed?",
        [{"query": "Explain the parental leave policy.", "answer": "Policy."}],
        client=client,
        model="routing",
    )

    assert result.relation == "follow_up"
    assert result.effective_query == (
        "What changed in the parental leave policy in 2025?"
    )
    assert len(client.calls) == 1


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


def test_pronoun_with_a_local_antecedent_does_not_use_conversation_history() -> None:
    client = ResolverClient("unused")
    query = 'What is "op sec" and how was it maintained during the operation described?'

    result = resolve_conversation(
        query,
        [
            {
                "query": "Is GPS always about satellite navigation in this document?",
                "answer": "GPS means General Problem Solver in this document.",
            }
        ],
        client=client,
        model="routing",
    )

    assert result.relation == "new_topic"
    assert result.effective_query == query
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


def test_existential_there_is_self_contained_with_history() -> None:
    for query in (
        "How many cases are there in each region?",
        "Are there any cases in Europe?",
        "Have there been any cases in Europe?",
        "Will there be cases in Europe?",
    ):
        client = ResolverClient("unused")

        result = resolve_conversation(
            query,
            [{"query": "What happened in Karachi?", "answer": "An earlier answer."}],
            client=client,
            model="routing",
        )

        assert result.relation == "new_topic", query
        assert result.effective_query == query
        assert result.method == "rules", query
        assert client.prompts == [], query


def test_locative_there_still_uses_conversation_resolution() -> None:
    client = ResolverClient(
        {
            "relation": "follow_up",
            "standalone_query": "How many cases happened in Karachi?",
            "antecedent_turn_ids": ["recent-1"],
            "clarification_question": None,
        }
    )

    result = resolve_conversation(
        "How many cases happened there?",
        [{"query": "What happened in Karachi?", "answer": "An earlier answer."}],
        client=client,
        model="routing",
    )

    assert result.relation == "follow_up"
    assert result.effective_query == "How many cases happened in Karachi?"
    assert len(client.prompts) == 1


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


def test_invalid_model_output_records_bounded_fallback_diagnostics() -> None:
    result = resolve_conversation(
        "Tell me more",
        [{"query": "What is parental leave?", "answer": "Leave policy."}],
        client=ResolverClient("not-json"),
        model="routing",
    )

    assert result.relation == "ambiguous"
    assert result.method == "fallback"
    assert result.decision_reason == "fallback"
    assert result.model_attempt_count == 1
    assert result.fallback_error_code == "invalid_output"


def test_provider_timeout_records_timeout_without_retry() -> None:
    result = resolve_conversation(
        "Tell me more",
        [{"query": "What is parental leave?", "answer": "Leave policy."}],
        client=TimeoutResolverClient(),
        model="routing",
    )

    assert result.relation == "ambiguous"
    assert result.method == "fallback"
    assert result.model_attempt_count == 1
    assert result.fallback_error_code == "timeout"


def test_explicit_reply_timeout_keeps_the_selected_exchange() -> None:
    result = resolve_conversation(
        "Who was the petitioner in this case?",
        [
            {
                "turn_id": "user-turn-1",
                "query": "Summarize the Acme court case.",
                "answer": "The case was filed by Jordan Lee against Acme.",
            }
        ],
        client=TimeoutResolverClient(),
        model="routing",
        reply_to_turn_id="user-turn-1",
    )

    assert result.relation == "follow_up"
    assert result.method == "fallback"
    assert result.decision_reason == "reply_fallback"
    assert result.antecedent_turn_ids == ("user-turn-1",)
    assert result.fallback_error_code == "timeout"
    assert "Summarize the Acme court case" in result.effective_query
    assert "Jordan Lee" in result.effective_query
    assert "Who was the petitioner" in result.effective_query


def test_explicit_reply_is_identified_in_the_resolver_prompt() -> None:
    client = ResolverClient(
        {
            "relation": "follow_up",
            "standalone_query": "Who was the petitioner in the Acme court case?",
            "antecedent_turn_ids": ["user-turn-1"],
            "dependency_targets": ["query", "answer"],
            "clarification_question": None,
        }
    )

    result = resolve_conversation(
        "Who was the petitioner in this case?",
        [
            {
                "turn_id": "user-turn-1",
                "query": "Summarize the Acme court case.",
                "answer": "The case was filed by Jordan Lee against Acme.",
            }
        ],
        client=client,
        model="routing",
        reply_to_turn_id="user-turn-1",
    )

    assert result.relation == "follow_up"
    assert 'Explicit reply target:\n"user-turn-1"' in client.prompts[0]
    assert "The case was filed by Jordan Lee" in client.prompts[0]


def test_disabled_resolver_treats_implicit_follow_up_as_standalone() -> None:
    client = FailIfCalledResolverClient()

    result = resolve_conversation(
        "What is its duration?",
        [{"turn_id": "user-turn-1", "query": "Describe the contract.", "answer": "It lasts 12 months."}],
        client=client,
        model="routing",
        enabled=False,
    )

    assert result.relation == "new_topic"
    assert result.effective_query == "What is its duration?"
    assert result.decision_reason == "resolver_disabled"


def test_disabled_resolver_keeps_explicit_reply_without_model_call() -> None:
    client = FailIfCalledResolverClient()

    result = resolve_conversation(
        "What is its duration?",
        [{"turn_id": "user-turn-1", "query": "Describe the contract.", "answer": "It lasts 12 months."}],
        client=client,
        model="routing",
        enabled=False,
        reply_to_turn_id="user-turn-1",
    )

    assert result.relation == "follow_up"
    assert result.method == "rules"
    assert result.antecedent_turn_ids == ("user-turn-1",)
    assert "Describe the contract" in result.effective_query
    assert "It lasts 12 months" in result.effective_query


def test_missing_resolver_records_unavailable_without_model_attempt() -> None:
    result = resolve_conversation(
        "Tell me more",
        [{"query": "What is parental leave?", "answer": "Leave policy."}],
        client=object(),
        model="routing",
    )

    assert result.relation == "ambiguous"
    assert result.method == "fallback"
    assert result.model_attempt_count == 0
    assert result.fallback_error_code == "unavailable"


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
        document_repo=None,
        chat_history_repo=history,
        ollama=client,
        routing_model="routing",
        context_resolver_enabled=True,
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


def test_routing_node_pins_an_explicit_assistant_reply_target() -> None:
    history = InMemoryChatHistoryRepository()
    for index in range(9):
        history.append_completed_turn(
            user_id="user-1",
            permission_version=2,
            session_id="session-1",
            title="Cases",
            user_turn={
                "id": f"user-turn-{index}",
                "role": "user",
                "content": f"Question {index}",
            },
            assistant_turn={
                "id": f"assistant-turn-{index}",
                "role": "assistant",
                "response": {"answer": f"Answer {index}", "sources": []},
            },
        )
    node = SimpleNamespace(
        document_repo=None,
        chat_history_repo=history,
        context_resolver_enabled=True,
    )
    ctx = initial_state(
        trace_id="trace",
        session_id="session-1",
        request=QueryRequest(
            query="Who was the petitioner in this case?",
            session_id="session-1",
            reply_to_turn_id="assistant-turn-0",
        ),
        user=UserContext(
            user_id="user-1",
            email="user@example.test",
            group_paths=("/ops",),
            permission_version=2,
        ),
        started=perf_counter(),
    )

    RoutingNodes.session_memory(node, ctx)

    assert ctx["reply_context_turn_id"] == "user-turn-0"
    assert ctx["session_turns"][-1]["answer"] == "Answer 0"


def test_disabled_routing_node_skips_history_but_keeps_explicit_reply() -> None:
    history = InMemoryChatHistoryRepository()
    history.append_completed_turn(
        user_id="user-1",
        permission_version=2,
        session_id="session-1",
        title="Contract",
        user_turn={"id": "user-turn-1", "role": "user", "content": "Describe the contract."},
        assistant_turn={"id": "assistant-turn-1", "role": "assistant", "response": {"answer": "It lasts 12 months.", "sources": []}},
    )
    node = SimpleNamespace(
        document_repo=None,
        chat_history_repo=history,
        ollama=FailIfCalledResolverClient(),
        routing_model="routing",
        context_resolver_enabled=False,
    )
    ctx = initial_state(
        trace_id="trace",
        session_id="session-1",
        request=QueryRequest(
            query="What is its duration?",
            session_id="session-1",
            reply_to_turn_id="assistant-turn-1",
        ),
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

    assert len(ctx["session_turns"]) == 1
    assert ctx["reply_context_turn_id"] == "user-turn-1"
    assert ctx["conversation_resolution"].decision_reason == "resolver_disabled_explicit_reply"
    assert "It lasts 12 months" in ctx["effective_query"]
