from types import SimpleNamespace

from rag.auth.context import UserContext
from rag.evaluations import execution
from rag.evaluations.execution import EvaluationRunExecutor
from rag.query.qdrant import SearchHit
from rag.schemas.evaluations import EvaluationCase


class FakeConfig:
    evaluation_diagnostic_top_k = 3
    rag_top_k = 2
    rag_sparse_model = "Qdrant/bm25"
    rag_sparse_cache_dir = "/models/fastembed"
    rag_reranker_max_candidates = 40
    rag_reranker_cache_dir = "/models/fastembed"


class FakeSparseVector:
    def as_qdrant(self) -> dict[str, list[int] | list[float]]:
        return {"indices": [1], "values": [0.5]}


class FakeEmbedder:
    def embed(self, _query: str) -> list[float]:
        return [0.1, 0.2, 0.3]


class FakeQdrant:
    def prepare_for_query(self, _vector_size: int) -> bool:
        return True

    def hybrid_search(
        self,
        *,
        dense_vector: list[float],
        sparse_vector: dict[str, object],
        limit: int,
        qdrant_filter: dict[str, object],
    ) -> list[SearchHit]:
        assert dense_vector == [0.1, 0.2, 0.3]
        assert sparse_vector == {"indices": [1], "values": [0.5]}
        assert limit == 3
        assert qdrant_filter
        return [
            hit("a", 0.4, "Doc A.pdf"),
            hit("b", 0.6, "Doc B.pdf"),
        ]


class FakeDocumentRepo:
    def list_documents(self, state: str) -> list[object]:
        assert state == "active"
        return []


def hit(point_id: str, score: float, doc_title: str, **payload: object) -> SearchHit:
    return SearchHit(
        point_id=point_id,
        score=score,
        payload={
            "doc_id": doc_title.removesuffix(".pdf").lower().replace(" ", "-"),
            "doc_title": doc_title,
            "chunk_id": point_id,
            "page": 4,
            "page_start": 4,
            "page_end": 5,
            "group_path": "/space",
            "text": f"{doc_title} evidence text",
            **payload,
        },
    )


def test_evaluation_diagnostic_records_reranked_candidates(monkeypatch) -> None:
    reranker_calls: dict[str, object] = {}

    def fake_sparse_embed(text: str, *, model_name: str, cache_dir: str | None) -> FakeSparseVector:
        assert text == "What insulin pen needle length should be used?"
        assert model_name == "Qdrant/bm25"
        assert cache_dir == "/models/fastembed"
        return FakeSparseVector()

    def fake_rerank(
        query: str,
        hits: list[SearchHit],
        *,
        top_k: int,
        max_candidates: int | None,
        model_name: str,
        cache_dir: str | None,
    ) -> list[SearchHit]:
        reranker_calls.update(
            query=query,
            top_k=top_k,
            max_candidates=max_candidates,
            model_name=model_name,
            cache_dir=cache_dir,
        )
        return [
            hit(
                "b",
                0.6,
                "Doc B.pdf",
                _rerank_score=0.91,
                _rerank_adjusted_score=0.56,
                _rerank_status="scored",
                _low_value_penalty=0.35,
                _low_value_reasons=["toc_or_index"],
            ),
            hit("a", 0.4, "Doc A.pdf", _rerank_score=0.22, _rerank_status="scored"),
        ]

    monkeypatch.setattr(execution, "embed_sparse_text", fake_sparse_embed)
    monkeypatch.setattr(execution, "rerank_hits", fake_rerank)
    service = SimpleNamespace(
        ollama=FakeEmbedder(),
        qdrant=FakeQdrant(),
        rag_config=SimpleNamespace(reranker_model="BAAI/bge-reranker-base"),
    )
    executor = EvaluationRunExecutor(
        repo_factory=lambda: None,
        document_repo_factory=lambda: FakeDocumentRepo(),
        rag_service_factory=lambda: service,
        config=FakeConfig(),
    )

    diagnostic = executor._diagnostic(
        EvaluationCase(id="case", question="What insulin pen needle length should be used?"),
        run=SimpleNamespace(group_path="/space", document_ids=["doc-a"]),
        user=UserContext(user_id="user", email="user@example.com", group_paths=("/space",)),
        service=service,
        document_repo=FakeDocumentRepo(),
    )

    assert diagnostic["status"] == "ok"
    assert diagnostic["retrieved_source_docs"] == ["Doc A.pdf", "Doc B.pdf"]
    assert diagnostic["reranked_source_docs"] == ["Doc B.pdf", "Doc A.pdf"]
    assert diagnostic["reranked_candidates"][0]["rerank_score"] == 0.91
    assert diagnostic["reranked_candidates"][0]["rerank_adjusted_score"] == 0.56
    assert diagnostic["reranked_candidates"][0]["rerank_status"] == "scored"
    assert diagnostic["reranked_candidates"][0]["low_value_penalty"] == 0.35
    assert diagnostic["reranked_candidates"][0]["low_value_reasons"] == ["toc_or_index"]
    assert diagnostic["reranker_model"] == "BAAI/bge-reranker-base"
    assert reranker_calls == {
        "query": "What insulin pen needle length should be used?",
        "top_k": 2,
        "max_candidates": 40,
        "model_name": "BAAI/bge-reranker-base",
        "cache_dir": "/models/fastembed",
    }
