from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from rag.query.faithfulness import build_faithfulness_prompt, parse_faithfulness_result
from rag.query.ollama import OllamaClient
from rag.query.openai_compatible import OpenAICompatibleClient
from rag.query.query_stream import _faithfulness_warnings
from rag.schemas.query import RAGResponse, SourceAnchor


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


class FaithfulnessRuntimeTests(unittest.TestCase):
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
