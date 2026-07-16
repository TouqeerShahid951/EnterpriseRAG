from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from rag.auth.context import UserContext
from rag.query.answering.faithfulness import build_faithfulness_prompt, parse_faithfulness_result
from rag.query.nodes.response_nodes import ResponseNodes
from rag.query.ollama import LONG_ANSWER_NUM_PREDICT, OllamaClient
from rag.query.openai_compatible import OpenAICompatibleClient
from rag.query.query_stream import _faithfulness_warnings
from rag.query.schemas import QueryRequest, RAGResponse, SourceAnchor
from rag.query.service import LocalRagService
from rag.query.state import QueryContext, initial_state


def response_with_faithfulness(status: str, score: float) -> RAGResponse:
    return RAGResponse(
        trace_id="trace",
        answer="Answer [doc:1]",
        sources=[],
        artifacts=[],
        artifact_job=None,
        conflict_flag=False,
        conflict_detail=None,
        faithfulness_score=score,
        faithfulness_status=status,
        unfounded_claims=["faithfulness_check_failed"],
        intent="aggregation",
        session_id="session",
        latency_ms=0,
        node_timings=[],
        degraded=status == "failed",
        degraded_reason="faithfulness_check_failed" if status == "failed" else None,
    )


class _FakeFaithfulnessClient:
    def __init__(self) -> None:
        self.calls = 0

    def judge_faithfulness(self, *, prompt: str, model: str | None) -> str:
        self.calls += 1
        assert prompt
        assert model == "faithfulness-model"
        return '{"score": 1.0, "unfounded_claims": []}'


class _FaithfulnessGraph:
    def __init__(self, nodes: ResponseNodes) -> None:
        self.nodes = nodes
        self.force_flags: list[bool] = []

    def invoke(self, ctx: QueryContext) -> QueryContext:
        self.force_flags.append(ctx["force_faithfulness_check"])
        ctx["response"] = _grounded_response()
        return self.nodes.faithfulness_checker(ctx)


def _service_with_never_policy() -> tuple[LocalRagService, _FakeFaithfulnessClient, _FaithfulnessGraph]:
    client = _FakeFaithfulnessClient()
    nodes = ResponseNodes()
    nodes.config = SimpleNamespace(
        rag_faithfulness_policy="never",
        rag_faithfulness_threshold=0.8,
        rag_reranker_cache_dir="/models/fastembed",
    )
    nodes.ollama = client
    nodes.faithfulness_model = "faithfulness-model"
    nodes.reranker_model = "reranker-model"
    graph = _FaithfulnessGraph(nodes)
    service = object.__new__(LocalRagService)
    service.config = SimpleNamespace(artifact_pipeline_version="v1")
    service.rag_config = SimpleNamespace(retrieval_token_budget=12000)
    service.graph = graph
    return service, client, graph


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


def _user() -> UserContext:
    return UserContext(
        user_id="user",
        email="user@example.com",
        group_paths=("/admin",),
    )


class FaithfulnessRuntimeTests(unittest.TestCase):
    def test_policy_never_skips_normal_answer_query(self) -> None:
        service, client, graph = _service_with_never_policy()

        response = service.answer_query(QueryRequest(query="What is the policy?"), _user())

        self.assertEqual(response.faithfulness_status, "skipped")
        self.assertEqual(client.calls, 0)
        self.assertEqual(graph.force_flags, [False])

    def test_internal_execute_query_can_force_policy_never_faithfulness(self) -> None:
        service, client, graph = _service_with_never_policy()

        execution = service.execute_query(
            QueryRequest(query="What is the policy?"),
            _user(),
            force_faithfulness_check=True,
        )

        self.assertEqual(execution.response.faithfulness_status, "checked")
        self.assertEqual(client.calls, 1)
        self.assertEqual(graph.force_flags, [True])

    def test_forced_faithfulness_does_not_override_clarification_safety(self) -> None:
        _, _, graph = _service_with_never_policy()
        ctx = initial_state(
            trace_id="trace",
            session_id="session",
            request=QueryRequest(query="Create a PDF"),
            user=_user(),
            started=0.0,
            force_faithfulness_check=True,
        )
        ctx["response"] = _grounded_response()

        self.assertFalse(graph.nodes.should_run_faithfulness(ctx))

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
            answer="Murder is registered under Section 302 PPC. [doc:1]",
            sources=[source],
        )

        self.assertIn("Section 302 PPC", prompt)
        self.assertIn("score and unfounded_claims", prompt)
        self.assertIn("Evidence:", prompt)
        self.assertNotIn("attributions", prompt)
        self.assertNotIn("shortest exact quote", prompt)

    def test_failed_faithfulness_check_is_not_reported_as_low_faithfulness(self) -> None:
        nodes = SimpleNamespace(config=SimpleNamespace(rag_faithfulness_threshold=0.8))

        events = list(_faithfulness_warnings(response_with_faithfulness("failed", 0.0), nodes))

        self.assertEqual(events, [])

    def test_checked_low_faithfulness_still_reports_warning(self) -> None:
        nodes = SimpleNamespace(config=SimpleNamespace(rag_faithfulness_threshold=0.8))

        events = list(_faithfulness_warnings(response_with_faithfulness("checked", 0.5), nodes))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].data["code"], "low_faithfulness")

    def test_parser_normalizes_claim_ids_and_citation_suffixes(self) -> None:
        result = parse_faithfulness_result(
            '{"score": 0.5, "unfounded_claims": ["claim-1: Murder claim | cited sources: [doc:1]"]}'
        )

        self.assertEqual(result.unfounded_claims, ["Murder claim"])


if __name__ == "__main__":
    unittest.main()
