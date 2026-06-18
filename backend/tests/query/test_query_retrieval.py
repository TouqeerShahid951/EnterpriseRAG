from rag.auth.context import UserContext
from rag.query.qdrant import SearchHit
from rag.query.query_retrieval import retrieve_candidates
from rag.query.routing_models import RoutePlan
from rag.query.state import initial_state
from rag.schemas.query import QueryRequest


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

    def search(self, _vector: list[float], *, limit: int, qdrant_filter: dict[str, object]) -> list[SearchHit]:
        return [
            hit("fir-04:detail", doc_id="fir-04", doc_title="FIR_04_cybercrime.pdf", text="Cyber crime details."),
            hit("manual:1", doc_id="manual", doc_title="Server Manual.pdf", text="Server maintenance details."),
        ][:limit]

    def retrieve_authorized_chunks(
        self,
        *,
        qdrant_filter: dict[str, object],
        structured_only: bool,
        limit: int,
    ) -> list[SearchHit]:
        return [
            hit("fir-02:offence", doc_id="fir-02", doc_title="FIR_02_kidnapping.pdf", text="Nature of Offence: Kidnapping for ransom."),
            hit("fir-03:offence", doc_id="fir-03", doc_title="FIR_03_robbery.pdf", text="Nature of Offence: Robbery."),
            hit("fir-04:detail", doc_id="fir-04", doc_title="FIR_04_cybercrime.pdf", text="Cyber crime details."),
            hit("fir-05:offence", doc_id="fir-05", doc_title="FIR_05_narcotics.pdf", text="Nature of Offence: Narcotics trafficking."),
            hit("fir-01:offence", doc_id="fir-01", doc_title="FIR_fictitious.pdf", text="Nature of Offence: Murder."),
            hit("manual:1", doc_id="manual", doc_title="Server Manual.pdf", text="Legal safety details."),
        ][:limit]


class FakeManualQdrant:
    def prepare_for_query(self, _vector_size: int) -> bool:
        return True

    def search(self, _vector: list[float], *, limit: int, qdrant_filter: dict[str, object]) -> list[SearchHit]:
        return [
            hit("policy:1", doc_id="policy", doc_title="Maintenance Policy.pdf", doc_type="policy", text="Maintenance details."),
            hit("manual-a:1", doc_id="manual-a", doc_title="Operations Guide.pdf", doc_type="manual", text="Pump details."),
        ][:limit]

    def retrieve_authorized_chunks(
        self,
        *,
        qdrant_filter: dict[str, object],
        structured_only: bool,
        limit: int,
    ) -> list[SearchHit]:
        return [
            hit("manual-a:1", doc_id="manual-a", doc_title="Operations Guide.pdf", doc_type="manual", text="Pump details."),
            hit("manual-b:1", doc_id="manual-b", doc_title="Equipment Handbook.pdf", generated_doc_type="manual", text="Valve details."),
            hit("policy:1", doc_id="policy", doc_title="Maintenance Policy.pdf", doc_type="policy", text="Maintenance details."),
        ][:limit]


def hit(point_id: str, *, doc_id: str, doc_title: str, text: str, **payload: object) -> SearchHit:
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
        public_intent="aggregation",
        use_structured_query=True,
        search_mode="structured_first",
        top_k=24,
    )


def test_exhaustive_aggregation_expands_named_document_scope() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="List All the Crime Commited with details in the all FIRs"),
        user=UserContext(user_id="user", email="user@example.com", group_paths=("/admin",)),
        started=0.0,
    )
    ctx["route_plan"] = route_plan(ctx["request"].query)

    hits = retrieve_candidates(ctx, config=FakeConfig(), ollama=FakeEmbedder(), qdrant=FakeQdrant())

    doc_ids = {item.payload["doc_id"] for item in hits}
    assert {"fir-01", "fir-02", "fir-03", "fir-04", "fir-05"} <= doc_ids
    assert "manual" not in doc_ids
    assert all(
        item.payload.get("exhaustive_scope_origin") == "document_class_scope"
        for item in hits
        if item.payload["doc_id"].startswith("fir-")
    )


def test_exhaustive_document_scope_is_doc_type_agnostic() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="List all maintenance details from all manuals"),
        user=UserContext(user_id="user", email="user@example.com", group_paths=("/admin",)),
        started=0.0,
    )
    ctx["route_plan"] = route_plan(ctx["request"].query)

    hits = retrieve_candidates(ctx, config=FakeConfig(), ollama=FakeEmbedder(), qdrant=FakeManualQdrant())

    doc_ids = {item.payload["doc_id"] for item in hits}
    assert doc_ids == {"manual-a", "manual-b"}
    assert all(item.payload.get("exhaustive_scope_origin") == "document_class_scope" for item in hits)
