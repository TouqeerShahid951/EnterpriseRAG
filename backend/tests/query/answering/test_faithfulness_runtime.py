from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from rag.auth.context import UserContext
from rag.query.answering.entailment import EntailmentScore
from rag.query.answering.faithfulness import (
    build_faithfulness_prompt,
    cited_claims,
    ordered_answer_covers_question,
    parse_faithfulness_result,
    reconcile_enumerated_list_counts,
    verify_cited_claims,
)
from rag.query.http import ServiceRequestError
from rag.query.ollama import LONG_ANSWER_NUM_PREDICT, OllamaClient
from rag.query.openai_compatible import OpenAICompatibleClient
from rag.query.schemas import (
    RAGResponse,
    SourceAnchor,
)


def _grounded_response() -> RAGResponse:
    return RAGResponse(
        trace_id="trace",
        answer="Grounded answer.",
        sources=[
            SourceAnchor(
                doc_id="doc",
                doc_title="Policy.pdf",
                chunk_id="doc:1",
                page=1,
                excerpt="Grounded answer.",
                group_path="/admin",
            )
        ],
        conflict_flag=False,
        faithfulness_score=1.0,
        faithfulness_status="pending",
        intent="factual_simple",
        session_id="session",
        latency_ms=0,
        degraded=False,
    )


def test_enumerated_list_count_is_reconciled_from_numbering() -> None:
    answer = (
        "The manual lists 12 repair tools:\n"
        + "\n".join(f"{number}. Tool {number}" for number in range(1, 14))
        + "\nNote: 13 items were found."
    )

    reconciled = reconcile_enumerated_list_counts(answer)

    assert reconciled.startswith("The manual lists 13 repair tools:\n")
    assert "Note: 13 items were found." in reconciled


def _user() -> UserContext:
    return UserContext(
        user_id="user",
        email="user@example.com",
        group_paths=("/admin",),
    )


class FaithfulnessRuntimeTests(unittest.TestCase):
    def test_ordered_list_projection_verifies_source_aligned_sequence(self) -> None:
        response = _grounded_response().model_copy(
            update={
                "answer": (
                    "The four maturity stages from least to most mature are: "
                    "**Traditional, Initial, Advanced, and Optimal**. [doc:1]"
                ),
                "sources": [
                    _grounded_response().sources[0].model_copy(
                        update={
                            "excerpt": (
                                "The three stages of the journey that advance from a "
                                "Traditional starting point to Initial, Advanced, and "
                                "Optimal facilitate implementation."
                            )
                        }
                    )
                ],
            }
        )
        nli = Mock(
            return_value=[
                EntailmentScore(0.42, 0.01, 0.57),
                EntailmentScore(0.01, 0.98, 0.01),
            ]
        )

        with (
            patch(
                "rag.query.answering.faithfulness.rank_passages",
                return_value=[(0, 0.85)],
            ),
            patch(
                "rag.query.answering.faithfulness.score_entailment",
                nli,
            ),
        ):
            result = verify_cited_claims(response)

        self.assertIsNotNone(result)
        self.assertEqual(result.score, 1.0)
        pairs = nli.call_args.args[0]
        self.assertEqual(
            pairs[1][1],
            "Traditional is followed by Initial, Advanced, and Optimal.",
        )

    def test_ordered_list_projection_accepts_are_without_colon(self) -> None:
        response = _grounded_response().model_copy(
            update={
                "answer": (
                    "The four maturity stages from least to most mature are "
                    "Traditional, Initial, Advanced, and Optimal. [doc:1]"
                ),
                "sources": [
                    _grounded_response().sources[0].model_copy(
                        update={
                            "excerpt": (
                                "The journey advances from a Traditional starting "
                                "point to Initial, Advanced, and Optimal."
                            )
                        }
                    )
                ],
            }
        )
        nli = Mock(
            return_value=[
                EntailmentScore(0.42, 0.01, 0.57),
                EntailmentScore(0.01, 0.98, 0.01),
            ]
        )

        with (
            patch(
                "rag.query.answering.faithfulness.rank_passages",
                return_value=[(0, 0.85)],
            ),
            patch(
                "rag.query.answering.faithfulness.score_entailment",
                nli,
            ),
        ):
            result = verify_cited_claims(response)

        self.assertIsNotNone(result)
        self.assertEqual(result.score, 1.0)
        self.assertEqual(
            nli.call_args.args[0][1][1],
            "Traditional is followed by Initial, Advanced, and Optimal.",
        )

    def test_near_verbatim_claim_allows_small_in_order_insertions(self) -> None:
        response = _grounded_response().model_copy(
            update={
                "answer": (
                    "The two core principles identified by the WHO Expert Group "
                    "are: [doc:1]\n"
                    "1. Protect autonomy [doc:1]\n"
                    "2. Ensure inclusiveness and equity [doc:1]"
                ),
                "sources": [
                    _grounded_response().sources[0].model_copy(
                        update={
                            "excerpt": (
                                "The two core principles identified by the WHO Expert "
                                "Group are the following: (1) Protect autonomy; "
                                "(2) Ensure inclusiveness and equity."
                            )
                        }
                    )
                ],
            }
        )

        relation_nli = Mock(
            return_value=[EntailmentScore(0.01, 0.98, 0.01)]
        )
        with (
            patch(
                "rag.query.answering.faithfulness.rank_passages",
                return_value=[(0, 0.85)],
            ),
            patch(
                "rag.query.answering.faithfulness.score_entailment",
                relation_nli,
            ),
        ):
            result = verify_cited_claims(response)

        self.assertIsNotNone(result)
        self.assertEqual(result.score, 1.0)
        self.assertEqual(
            relation_nli.call_args.args[0][0][1],
            (
                "The two core principles identified by the WHO Expert Group are "
                "Protect autonomy; Ensure inclusiveness and equity."
            ),
        )

    def test_deterministic_verifier_excludes_an_orphaned_next_list_marker(
        self,
    ) -> None:
        response = _grounded_response().model_copy(
            update={
                "answer": (
                    "The employee is entitled to an annual period of leave of "
                    "42 business days. [doc:1]"
                ),
                "sources": [
                    _grounded_response().sources[0].model_copy(
                        update={
                            "excerpt": (
                                "CLAUSE SEVEN\n\n"
                                "(ANNUAL PERIOD OF LEAVE)\n\n"
                                "1. Without prejudice to the following paragraphs, "
                                "the annual period of leave has the duration of "
                                "42(forty-two) business days.\n\n"
                                "2. In the year of hire, the employee accrues leave."
                            )
                        }
                    )
                ],
            }
        )

        def rank_matching_passage(_query: str, passages: list[str], **_kwargs):
            index = next(
                index
                for index, passage in enumerate(passages)
                if "duration of 42" in passage
            )
            return [(index, 0.85)]

        entailment = Mock(
            return_value=[EntailmentScore(0.01, 0.98, 0.01)]
        )
        with (
            patch(
                "rag.query.answering.faithfulness.rank_passages",
                side_effect=rank_matching_passage,
            ),
            patch(
                "rag.query.answering.faithfulness.score_entailment",
                entailment,
            ),
        ):
            result = verify_cited_claims(response)

        self.assertIsNotNone(result)
        premise = entailment.call_args.args[0][0][0]
        self.assertTrue(premise.endswith("business days."))
        self.assertNotIn("\n\n2.", premise)

    def test_incomplete_counted_list_is_not_deterministically_approved(self) -> None:
        response = _grounded_response().model_copy(
            update={
                "answer": (
                    "The six core principles identified by the WHO Expert Group "
                    "are: [doc:1]\n"
                    "1. Protect autonomy [doc:1]\n"
                    "2. Ensure inclusiveness and equity [doc:1]"
                ),
                "sources": [
                    _grounded_response().sources[0].model_copy(
                        update={
                            "excerpt": (
                                "The six core principles include protect autonomy "
                                "and ensure inclusiveness and equity."
                            )
                        }
                    )
                ],
            }
        )

        with (
            patch(
                "rag.query.answering.faithfulness.rank_passages",
                side_effect=AssertionError("incomplete list should fail before ranking"),
            ),
            patch(
                "rag.query.answering.faithfulness.score_entailment",
                side_effect=AssertionError("incomplete list should fail before NLI"),
            ),
        ):
            result = verify_cited_claims(response)

        self.assertIsNone(result)

    def test_counted_list_structure_and_short_labels_are_verified_safely(
        self,
    ) -> None:
        response = _grounded_response().model_copy(
            update={
                "answer": (
                    "The two trustworthy system characteristics are: [doc:1]\n"
                    "- Safe [doc:1]\n"
                    "- Bias managed transparently [doc:1]"
                ),
                "sources": [
                    _grounded_response().sources[0].model_copy(
                        update={
                            "excerpt": (
                                "Trustworthy system characteristics include Safe; "
                                "biases are managed transparently."
                            )
                        }
                    )
                ],
            }
        )

        relation_nli = Mock(
            return_value=[EntailmentScore(0.01, 0.98, 0.01)]
        )
        with (
            patch(
                "rag.query.answering.faithfulness.rank_passages",
                return_value=[(0, 0.85)],
            ),
            patch(
                "rag.query.answering.faithfulness.score_entailment",
                relation_nli,
            ),
        ):
            result = verify_cited_claims(response)

        self.assertIsNotNone(result)
        self.assertEqual(result.score, 1.0)

    def test_counted_list_stops_before_supported_trailing_prose(self) -> None:
        response = _grounded_response().model_copy(
            update={
                "answer": (
                    "The two policy stages are: [doc:1]\n"
                    "- Alpha review [doc:1]\n"
                    "- Beta approval [doc:1]\n"
                    "A related control is Gamma. [doc:1]"
                ),
                "sources": [
                    _grounded_response().sources[0].model_copy(
                        update={
                            "excerpt": (
                                "The policy stages are Alpha review and Beta approval. "
                                "A related control is Gamma."
                            )
                        }
                    )
                ],
            }
        )

        claims = cited_claims(response.answer)
        self.assertEqual(
            [claim.is_list_item for claim in claims],
            [False, True, True, False],
        )

        relation_nli = Mock(
            return_value=[EntailmentScore(0.01, 0.98, 0.01)]
        )
        with (
            patch(
                "rag.query.answering.faithfulness.rank_passages",
                return_value=[(0, 0.85)],
            ),
            patch(
                "rag.query.answering.faithfulness.score_entailment",
                relation_nli,
            ),
        ):
            result = verify_cited_claims(response)

        self.assertIsNotNone(result)
        self.assertEqual(result.score, 1.0)
        self.assertEqual(
            relation_nli.call_args.args[0][0][1],
            "The two policy stages are Alpha review; Beta approval.",
        )

    def test_trailing_prose_cannot_fill_a_missing_counted_list_item(self) -> None:
        response = _grounded_response().model_copy(
            update={
                "answer": (
                    "The two policy stages are: [doc:1]\n"
                    "- Alpha review [doc:1]\n"
                    "A related control is Gamma. [doc:1]"
                ),
                "sources": [
                    _grounded_response().sources[0].model_copy(
                        update={
                            "excerpt": (
                                "The policy includes Alpha review. "
                                "A related control is Gamma."
                            )
                        }
                    )
                ],
            }
        )

        with (
            patch(
                "rag.query.answering.faithfulness.rank_passages",
                side_effect=AssertionError(
                    "incomplete list should fail before ranking"
                ),
            ),
            patch(
                "rag.query.answering.faithfulness.score_entailment",
                side_effect=AssertionError(
                    "incomplete list should fail before NLI"
                ),
            ),
        ):
            result = verify_cited_claims(response)

        self.assertIsNone(result)

    def test_person_initial_cannot_fill_a_missing_counted_list_item(self) -> None:
        response = _grounded_response().model_copy(
            update={
                "answer": (
                    "The two policy stages are: [doc:1]\n"
                    "- Alpha review [doc:1]\n"
                    "A. Smith approved the policy. [doc:1]"
                ),
                "sources": [
                    _grounded_response().sources[0].model_copy(
                        update={
                            "excerpt": (
                                "The policy stages include Alpha review. "
                                "A. Smith approved the policy."
                            )
                        }
                    )
                ],
            }
        )

        with (
            patch(
                "rag.query.answering.faithfulness.rank_passages",
                side_effect=AssertionError(
                    "ambiguous initial should fail before ranking"
                ),
            ),
            patch(
                "rag.query.answering.faithfulness.score_entailment",
                side_effect=AssertionError(
                    "ambiguous initial should fail before NLI"
                ),
            ),
        ):
            result = verify_cited_claims(response)

        self.assertIsNone(result)

    def test_abbreviation_does_not_merge_uncited_prose_across_newline(self) -> None:
        response = _grounded_response().model_copy(
            update={
                "answer": (
                    "The two policy stages are: [doc:1]\n"
                    "- Alpha review [doc:1]\n"
                    "Related prose etc.\n"
                    "- Beta approval [doc:1]"
                )
            }
        )

        self.assertEqual(
            [claim.text for claim in cited_claims(response.answer)],
            [
                "The two policy stages are:",
                "Alpha review",
                "Beta approval",
            ],
        )
        with patch(
            "rag.query.answering.faithfulness.rank_passages",
            side_effect=AssertionError(
                "uncited prose should fail before ranking"
            ),
        ):
            result = verify_cited_claims(response)

        self.assertIsNone(result)

    def test_citation_boundary_does_not_merge_independent_claims(self) -> None:
        claims = cited_claims(
            "Examples etc. [doc:1] It expires in 2025. [appendix:2]"
        )

        self.assertEqual(
            [(claim.text, claim.source_labels) for claim in claims],
            [
                ("Examples etc.", ("[doc:1]",)),
                ("It expires in 2025.", ("[appendix:2]",)),
            ],
        )

    def test_invalid_numbering_cannot_complete_a_counted_list(self) -> None:
        item_blocks = (
            "1. Alpha review [doc:1]\n3. Beta approval [doc:1]",
            "1. Alpha review [doc:1]\n1. Beta approval [doc:1]",
            "- Alpha review [doc:1]\n2. Beta approval [doc:1]",
            "- Alpha review [doc:1]\n99. Gamma control exists [doc:1]",
        )
        for item_block in item_blocks:
            with self.subTest(item_block=item_block):
                response = _grounded_response().model_copy(
                    update={
                        "answer": (
                            "The two policy stages are: [doc:1]\n"
                            f"{item_block}"
                        )
                    }
                )
                with patch(
                    "rag.query.answering.faithfulness.rank_passages",
                    side_effect=AssertionError(
                        "invalid numbering should fail before ranking"
                    ),
                ):
                    result = verify_cited_claims(response)

                self.assertIsNone(result)

    def test_supported_but_unrelated_item_is_not_accepted_as_list_member(
        self,
    ) -> None:
        response = _grounded_response().model_copy(
            update={
                "answer": (
                    "The two policy stages are: [doc:1]\n"
                    "- Alpha review [doc:1]\n"
                    "- Gamma control exists [doc:1]"
                ),
                "sources": [
                    _grounded_response().sources[0].model_copy(
                        update={
                            "excerpt": (
                                "The two policy stages are Alpha review and "
                                "Beta approval. Gamma control exists."
                            )
                        }
                    )
                ],
            }
        )
        relation_nli = Mock(
            return_value=[EntailmentScore(0.98, 0.01, 0.01)]
        )

        with (
            patch(
                "rag.query.answering.faithfulness.rank_passages",
                return_value=[(0, 0.85)],
            ),
            patch(
                "rag.query.answering.faithfulness.score_entailment",
                relation_nli,
            ),
        ):
            result = verify_cited_claims(response)

        self.assertIsNone(result)
        self.assertEqual(
            relation_nli.call_args.args[0][0][1],
            "The two policy stages are Alpha review; Gamma control exists.",
        )

    def test_counted_list_requires_shared_relational_evidence(self) -> None:
        base_source = _grounded_response().sources[0]
        response = _grounded_response().model_copy(
            update={
                "answer": (
                    "The two policy stages are: [header:1]\n"
                    "- Alpha review [items:1]\n"
                    "- Gamma control exists [items:1]"
                ),
                "sources": [
                    base_source.model_copy(
                        update={
                            "doc_id": "header",
                            "chunk_id": "header:1",
                            "excerpt": "The two policy stages are:",
                        }
                    ),
                    base_source.model_copy(
                        update={
                            "doc_id": "items",
                            "chunk_id": "items:1",
                            "excerpt": (
                                "Alpha review is documented. "
                                "Gamma control exists."
                            ),
                        }
                    ),
                ],
            }
        )

        with patch(
            "rag.query.answering.faithfulness.rank_passages",
            side_effect=AssertionError(
                "cross-source list should fail before ranking"
            ),
        ):
            result = verify_cited_claims(response)

        self.assertIsNone(result)

    def test_same_line_cited_continuation_does_not_end_counted_list(self) -> None:
        response = _grounded_response().model_copy(
            update={
                "answer": (
                    "The two policy stages are: [doc:1]\n"
                    "1. Alpha review [doc:1] with rationale [doc:1]\n"
                    "2. Beta approval [doc:1]"
                ),
                "sources": [
                    _grounded_response().sources[0].model_copy(
                        update={
                            "excerpt": (
                                "The policy stages are Alpha review with rationale "
                                "and Beta approval."
                            )
                        }
                    )
                ],
            }
        )

        relation_nli = Mock(
            return_value=[EntailmentScore(0.01, 0.98, 0.01)]
        )
        with (
            patch(
                "rag.query.answering.faithfulness.rank_passages",
                return_value=[(0, 0.85)],
            ),
            patch(
                "rag.query.answering.faithfulness.score_entailment",
                relation_nli,
            ),
        ):
            result = verify_cited_claims(response)

        self.assertIsNotNone(result)
        self.assertEqual(result.score, 1.0)

    def test_adjacent_citations_remain_attached_to_one_claim(self) -> None:
        claims = cited_claims(
            "The policy applies. [doc:1] [appendix:2]"
        )

        self.assertEqual(len(claims), 1)
        self.assertEqual(
            claims[0].source_labels,
            ("[doc:1]", "[appendix:2]"),
        )

    def test_short_list_label_is_not_supported_through_negation(self) -> None:
        response = _grounded_response().model_copy(
            update={
                "answer": (
                    "The two trustworthy system characteristics are: [doc:1]\n"
                    "- Safe [doc:1]\n"
                    "- Bias managed transparently [doc:1]"
                ),
                "sources": [
                    _grounded_response().sources[0].model_copy(
                        update={
                            "excerpt": (
                                "Trustworthy system characteristics include not "
                                "Safe; biases are managed transparently."
                            )
                        }
                    )
                ],
            }
        )

        with (
            patch(
                "rag.query.answering.faithfulness.rank_passages",
                return_value=[(0, 0.85)],
            ),
            patch(
                "rag.query.answering.faithfulness.score_entailment",
                side_effect=lambda pairs, **_: [
                    EntailmentScore(0.98, 0.01, 0.01) for _ in pairs
                ],
            ),
        ):
            result = verify_cited_claims(response)

        self.assertIsNone(result)

    def test_near_verbatim_claim_does_not_ignore_negation(self) -> None:
        response = _grounded_response().model_copy(
            update={
                "answer": "The policy does not permit remote work. [doc:1]",
                "sources": [
                    _grounded_response().sources[0].model_copy(
                        update={"excerpt": "The policy does permit remote work."}
                    )
                ],
            }
        )

        with (
            patch(
                "rag.query.answering.faithfulness.rank_passages",
                return_value=[(0, 0.85)],
            ),
            patch(
                "rag.query.answering.faithfulness.score_entailment",
                return_value=[EntailmentScore(0.98, 0.01, 0.01)],
            ),
        ):
            result = verify_cited_claims(response)

        self.assertIsNone(result)

    def test_near_verbatim_claim_does_not_ignore_evidence_negation(self) -> None:
        response = _grounded_response().model_copy(
            update={
                "answer": "The policy permits remote work. [doc:1]",
                "sources": [
                    _grounded_response().sources[0].model_copy(
                        update={"excerpt": "The policy does not permit remote work."}
                    )
                ],
            }
        )

        with (
            patch(
                "rag.query.answering.faithfulness.rank_passages",
                return_value=[(0, 0.85)],
            ),
            patch(
                "rag.query.answering.faithfulness.score_entailment",
                return_value=[EntailmentScore(0.98, 0.01, 0.01)],
            ),
        ):
            result = verify_cited_claims(response)

        self.assertIsNone(result)

    def test_date_range_is_not_treated_as_ordered_list_question(self) -> None:
        response = _grounded_response().model_copy(
            update={
                "answer": (
                    "The changes from 2020 to 2024 were: Alpha, Beta, and Gamma. "
                    "[doc:1]"
                )
            }
        )

        self.assertFalse(
            ordered_answer_covers_question(
                response,
                "What changed from 2020 to 2024?",
            )
        )

    def test_ordered_projection_rejects_date_ranges_and_count_free_prose(
        self,
    ) -> None:
        cases = (
            "The four changes from 2020 to 2024 are Alpha, Beta, Gamma, and Delta.",
            (
                "Controls in ascending order are discussed in policy, with "
                "exceptions, and reviewed annually."
            ),
            (
                "The three stages in ascending order are discussed in policy, "
                "reviewed annually, and revised when needed."
            ),
        )
        for claim in cases:
            with self.subTest(claim=claim):
                response = _grounded_response().model_copy(
                    update={
                        "answer": f"{claim} [doc:1]",
                        "sources": [
                            _grounded_response().sources[0].model_copy(
                                update={
                                    "excerpt": (
                                        "Alpha is followed by Beta, Gamma, and Delta."
                                    )
                                }
                            )
                        ],
                    }
                )
                nli = Mock(
                    side_effect=lambda pairs, **_: [
                        EntailmentScore(0.01, 0.98, 0.01) for _ in pairs
                    ]
                )

                with (
                    patch(
                        "rag.query.answering.faithfulness.rank_passages",
                        return_value=[(0, 0.85)],
                    ),
                    patch(
                        "rag.query.answering.faithfulness.score_entailment",
                        nli,
                    ),
                ):
                    verify_cited_claims(response)

                self.assertEqual(len(nli.call_args.args[0]), 1)

    def test_ordered_list_projection_does_not_override_wrong_count(self) -> None:
        response = _grounded_response().model_copy(
            update={
                "answer": (
                    "The five maturity stages from least to most mature are: "
                    "Traditional, Initial, Advanced, and Optimal. [doc:1]"
                ),
                "sources": [
                    _grounded_response().sources[0].model_copy(
                        update={
                            "excerpt": (
                                "Traditional is followed by Initial, Advanced, and "
                                "Optimal."
                            )
                        }
                    )
                ],
            }
        )
        nli = Mock(return_value=[EntailmentScore(0.95, 0.01, 0.04)])

        with (
            patch(
                "rag.query.answering.faithfulness.rank_passages",
                return_value=[(0, 0.85)],
            ),
            patch(
                "rag.query.answering.faithfulness.score_entailment",
                nli,
            ),
        ):
            result = verify_cited_claims(response)

        self.assertIsNone(result)
        self.assertEqual(len(nli.call_args.args[0]), 1)

    def test_ordered_list_projection_keeps_reversed_order_unverified(self) -> None:
        response = _grounded_response().model_copy(
            update={
                "answer": (
                    "The four maturity stages from least to most mature are: "
                    "Optimal, Advanced, Initial, and Traditional. [doc:1]"
                ),
                "sources": [
                    _grounded_response().sources[0].model_copy(
                        update={
                            "excerpt": (
                                "Traditional is followed by Initial, Advanced, and "
                                "Optimal."
                            )
                        }
                    )
                ],
            }
        )
        nli = Mock(
            return_value=[
                EntailmentScore(0.98, 0.01, 0.01),
                EntailmentScore(0.94, 0.02, 0.04),
            ]
        )

        with (
            patch(
                "rag.query.answering.faithfulness.rank_passages",
                return_value=[(0, 0.85)],
            ),
            patch(
                "rag.query.answering.faithfulness.score_entailment",
                nli,
            ),
        ):
            result = verify_cited_claims(response)

        self.assertIsNone(result)
        self.assertEqual(
            nli.call_args.args[0][1][1],
            "Optimal is followed by Advanced, Initial, and Traditional.",
        )


    def test_ollama_faithfulness_caps_configured_json_budget(self) -> None:
        client = OllamaClient(
            base_url="http://ollama.local",
            chat_model="chat-model",
            embed_model="embed-model",
            timeout_seconds=45,
            json_num_predict=4096,
            num_ctx=16384,
        )

        with patch(
            "rag.query.ollama.request_json",
            return_value={"message": {"content": '{"score": 1.0, "unfounded_claims": [], "attributions": []}'}},
        ) as request_json:
            client.judge_faithfulness(prompt="prompt", model=None)

        payload = request_json.call_args.kwargs["payload"]
        self.assertEqual(payload["options"]["num_predict"], 1024)
        self.assertEqual(payload["options"]["num_ctx"], 16384)

    def test_ollama_faithfulness_sends_schema_on_first_request(self) -> None:
        client = OllamaClient(
            base_url="http://ollama.local",
            chat_model="chat-model",
            embed_model="embed-model",
            timeout_seconds=45,
        )
        schema = {
            "type": "object",
            "properties": {"score": {"type": "number"}},
            "required": ["score"],
        }

        with patch(
            "rag.query.ollama.request_json",
            return_value={"message": {"content": '{"score": 1.0}'}},
        ) as request_json:
            client.judge_faithfulness(
                prompt="prompt",
                model=None,
                json_schema=schema,
            )

        self.assertIs(request_json.call_args.kwargs["payload"]["format"], schema)

    def test_ollama_answer_includes_context_limit(self) -> None:
        client = OllamaClient(
            base_url="http://ollama.local",
            chat_model="chat-model",
            embed_model="embed-model",
            timeout_seconds=45,
            num_ctx=16384,
        )

        with patch(
            "rag.query.ollama.request_json",
            return_value={"message": {"content": "answer"}},
        ) as request_json:
            client.answer(question="question", contexts=["context"])

        payload = request_json.call_args.kwargs["payload"]
        self.assertEqual(payload["options"]["num_ctx"], 16384)
        self.assertEqual(payload["options"]["num_predict"], LONG_ANSWER_NUM_PREDICT)

    def test_ollama_answer_rejects_output_that_reached_token_limit(self) -> None:
        client = OllamaClient(
            base_url="http://ollama.local",
            chat_model="chat-model",
            embed_model="embed-model",
            timeout_seconds=45,
        )

        with (
            patch(
                "rag.query.ollama.request_json",
                return_value={
                    "message": {"content": "truncated answer"},
                    "done_reason": "stop",
                    "eval_count": 1024,
                },
            ),
            self.assertRaisesRegex(
                ServiceRequestError,
                "reached its output token limit",
            ),
        ):
            client.answer(
                question="question",
                contexts=["context"],
                profile="factual_simple",
            )

    def test_ollama_stream_rejects_terminal_output_at_token_limit(self) -> None:
        client = OllamaClient(
            base_url="http://ollama.local",
            chat_model="chat-model",
            embed_model="embed-model",
            timeout_seconds=45,
        )

        with (
            patch(
                "rag.query.ollama.stream_json_lines",
                return_value=iter(
                    [
                        {"message": {"content": "partial answer"}},
                        {
                            "message": {"content": ""},
                            "done_reason": "stop",
                            "eval_count": 1024,
                        },
                    ]
                ),
            ),
            self.assertRaisesRegex(
                ServiceRequestError,
                "reached its output token limit",
            ),
        ):
            list(
                client.stream_answer(
                    question="question",
                    contexts=["context"],
                    profile="factual_simple",
                )
            )

    def test_openai_compatible_faithfulness_caps_configured_json_budget(self) -> None:
        client = OpenAICompatibleClient(
            base_url="http://vllm.local",
            embedding_base_url="http://embed.local",
            chat_model="chat-model",
            embed_model="embed-model",
            timeout_seconds=45,
            json_num_predict=4096,
        )

        with patch(
            "rag.query.openai_compatible.request_json",
            return_value={
                "choices": [
                    {"message": {"content": '{"score": 1.0, "unfounded_claims": [], "attributions": []}'}}
                ]
            },
        ) as request_json:
            client.judge_faithfulness(prompt="prompt", model=None)

        payload = request_json.call_args.kwargs["payload"]
        self.assertEqual(payload["max_tokens"], 1024)

    def test_openai_compatible_faithfulness_sends_schema_on_first_request(
        self,
    ) -> None:
        client = OpenAICompatibleClient(
            base_url="http://vllm.local",
            embedding_base_url="http://embed.local",
            chat_model="chat-model",
            embed_model="embed-model",
            timeout_seconds=45,
        )
        schema = {
            "type": "object",
            "properties": {"score": {"type": "number"}},
            "required": ["score"],
        }

        with patch(
            "rag.query.openai_compatible.request_json",
            return_value={
                "choices": [{"message": {"content": '{"score": 1.0}'}}]
            },
        ) as request_json:
            client.judge_faithfulness(
                prompt="prompt",
                model=None,
                json_schema=schema,
            )

        response_format = request_json.call_args.kwargs["payload"][
            "response_format"
        ]
        self.assertEqual(response_format["type"], "json_schema")
        self.assertIs(response_format["json_schema"]["schema"], schema)
        self.assertTrue(response_format["json_schema"]["strict"])

    def test_openai_answer_rejects_output_that_reached_token_limit(self) -> None:
        client = OpenAICompatibleClient(
            base_url="http://vllm.local",
            embedding_base_url="http://embed.local",
            chat_model="chat-model",
            embed_model="embed-model",
            timeout_seconds=45,
        )

        with (
            patch(
                "rag.query.openai_compatible.request_json",
                return_value={
                    "choices": [
                        {
                            "message": {"content": "truncated answer"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"completion_tokens": 1024},
                },
            ),
            self.assertRaisesRegex(
                ServiceRequestError,
                "reached its output token limit",
            ),
        ):
            client.answer(
                question="question",
                contexts=["context"],
                profile="factual_simple",
            )

    def test_openai_stream_rejects_length_finish_reason(self) -> None:
        client = OpenAICompatibleClient(
            base_url="http://vllm.local",
            embedding_base_url="http://embed.local",
            chat_model="chat-model",
            embed_model="embed-model",
            timeout_seconds=45,
        )

        with (
            patch(
                "rag.query.openai_compatible.stream_sse_json",
                return_value=iter(
                    [
                        {
                            "choices": [
                                {
                                    "delta": {"content": "partial answer"},
                                    "finish_reason": None,
                                }
                            ]
                        },
                        {
                            "choices": [
                                {
                                    "delta": {},
                                    "finish_reason": "length",
                                }
                            ]
                        },
                    ]
                ),
            ),
            self.assertRaisesRegex(
                ServiceRequestError,
                "reached its output token limit",
            ),
        ):
            list(
                client.stream_answer(
                    question="question",
                    contexts=["context"],
                    profile="factual_simple",
                )
            )

    def test_faithfulness_prompt_uses_verdict_only_output_contract(self) -> None:
        excerpt = (
            ("Irrelevant opening sentence. " * 80)
            + "Legal Action: This FIR is registered under Section 302 PPC for Qatl-e-Amd. "
            + ("Irrelevant trailing sentence. " * 80)
        )
        source = SourceAnchor(
            doc_id="doc",
            doc_title="FIR.pdf",
            chunk_id="doc:1",
            page=1,
            excerpt=excerpt,
            group_path="/admin",
        )

        prompt = build_faithfulness_prompt(
            question="Which law applies?",
            answer="Murder is registered under Section 302 PPC. [doc:1]",
            sources=[source],
        )

        self.assertIn("Section 302 PPC", prompt)
        self.assertIn("Which law applies?", prompt)
        self.assertIn("responsive, and missing_aspects", prompt)
        self.assertIn("Evidence:", prompt)
        self.assertNotIn("attributions", prompt)
        self.assertNotIn("shortest exact quote", prompt)

    def test_parser_normalizes_claim_ids_and_citation_suffixes(self) -> None:
        result = parse_faithfulness_result(
            '{"score": 0.5, "unfounded_claims": '
            '["claim-1: Murder claim | cited sources: [doc:1]"], '
            '"responsive": true, "missing_aspects": []}'
        )

        self.assertEqual(result.unfounded_claims, ["Murder claim"])

    def test_parser_reads_responsiveness_and_missing_aspects(self) -> None:
        result = parse_faithfulness_result(
            '{"score": 1.0, "unfounded_claims": [], "responsive": false, '
            '"missing_aspects": ["reference number"]}'
        )

        self.assertFalse(result.responsive)
        self.assertEqual(result.missing_aspects, ["reference number"])

    def test_parser_rejects_missing_responsiveness_verdict(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid object shape"):
            parse_faithfulness_result(
                '{"score": 1.0, "unfounded_claims": []}'
            )


if __name__ == "__main__":
    unittest.main()
