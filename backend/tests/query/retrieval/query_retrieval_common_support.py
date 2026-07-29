# ruff: noqa: F401

from rag.auth.context import UserContext

from rag.query.qdrant import SearchHit

from rag.query.retrieval.query_retrieval import retrieve_candidates

from rag.query.routing.routing_models import RoutePlan

from rag.query.state import initial_retrieval_state, initial_state

from rag.query.schemas import QueryRequest

class FakeConfig:
    rag_top_k = 10
    rag_sparse_model = ""
    rag_sparse_cache_dir = ""

class FakeEmbedder:
    def embed(self, _query: str) -> list[float]:
        return [0.1, 0.2, 0.3]

class FakeQdrant:
    def prepare_for_query(self, _vector_size: int) -> bool:
        return True

    def search(
        self, _vector: list[float], *, limit: int, qdrant_filter: dict[str, object]
    ) -> list[SearchHit]:
        return [
            hit(
                "fir-04:detail",
                doc_id="fir-04",
                doc_title="FIR_04_cybercrime.pdf",
                text="Cyber crime details.",
            ),
            hit(
                "manual:1",
                doc_id="manual",
                doc_title="Server Manual.pdf",
                text="Server maintenance details.",
            ),
        ][:limit]

    def retrieve_authorized_chunks(
        self,
        *,
        qdrant_filter: dict[str, object],
        structured_only: bool,
        limit: int,
        deadline: float | None = None,
    ) -> list[SearchHit]:
        return [
            hit(
                "fir-02:offence",
                doc_id="fir-02",
                doc_title="FIR_02_kidnapping.pdf",
                text="Nature of Offence: Kidnapping for ransom.",
            ),
            hit(
                "fir-03:offence",
                doc_id="fir-03",
                doc_title="FIR_03_robbery.pdf",
                text="Nature of Offence: Robbery.",
            ),
            hit(
                "fir-04:detail",
                doc_id="fir-04",
                doc_title="FIR_04_cybercrime.pdf",
                text="Cyber crime details.",
            ),
            hit(
                "fir-05:offence",
                doc_id="fir-05",
                doc_title="FIR_05_narcotics.pdf",
                text="Nature of Offence: Narcotics trafficking.",
            ),
            hit(
                "fir-01:offence",
                doc_id="fir-01",
                doc_title="FIR_fictitious.pdf",
                text="Nature of Offence: Murder.",
            ),
            hit(
                "manual:1",
                doc_id="manual",
                doc_title="Server Manual.pdf",
                text="Legal safety details.",
            ),
        ][:limit]

def hit(
    point_id: str, *, doc_id: str, doc_title: str, text: str, **payload: object
) -> SearchHit:
    return SearchHit(
        point_id=point_id,
        score=0.2,
        payload={
            "doc_id": doc_id,
            "chunk_id": point_id,
            "doc_title": doc_title,
            "text": text,
            "page": 1,
            **payload,
        },
    )

def route_plan(query: str) -> RoutePlan:
    return RoutePlan(
        original_query=query,
        resolved_query=query,
        intent="aggregation",
        capabilities=(
            "general_search",
            "structured_query",
            "document_search",
        ),
        scope="corpus",
        coverage="exhaustive",
        public_intent="aggregation",
        use_structured_query=True,
        search_mode="structured_first",
        top_k=24,
    )

def definition_plan(query: str) -> RoutePlan:
    return RoutePlan(
        original_query=query,
        resolved_query=query,
        intent="factual_simple",
        public_intent="factual_simple",
        top_k=4,
    )

__all__ = [name for name in globals() if not name.startswith("__")]
