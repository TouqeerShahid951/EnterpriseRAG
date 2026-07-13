from rag.auth.context import UserContext
from rag.query.qdrant import SearchHit
from rag.query.query_retrieval import retrieve_candidates
from rag.query.routing_models import RoutePlan
from rag.query.state import initial_retrieval_state, initial_state
from rag.query.schemas import QueryRequest


class FakeConfig:
    rag_top_k = 10
    rag_sparse_model = ""
    rag_sparse_cache_dir = ""


def test_initial_retrieval_state_preserves_artifact_job_query_scope() -> None:
    user = UserContext(
        user_id="user",
        email="user@example.com",
        group_paths=("/admin",),
    )

    ctx = initial_retrieval_state(
        trace_id="trace-1",
        session_id="session-1",
        query="quarterly risk",
        group_path="/finance",
        document_ids=("doc-2", "doc-1"),
        user=user,
        token_budget=4321,
    )

    assert ctx["trace_id"] == "trace-1"
    assert ctx["session_id"] == "session-1"
    assert ctx["request"] == QueryRequest(
        query="quarterly risk",
        session_id="session-1",
        group_path="/finance",
        document_ids=["doc-2", "doc-1"],
    )
    assert ctx["user"] is user
    assert ctx["token_budget"] == 4321
    assert ctx["wall_time_start"] == 0.0


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


class FakeBroadDocumentQdrant:
    def prepare_for_query(self, _vector_size: int) -> bool:
        return True

    def search(self, _vector: list[float], *, limit: int, qdrant_filter: dict[str, object]) -> list[SearchHit]:
        return [
            hit(
                "policy:table",
                doc_id="policy",
                doc_title="Policy.pdf",
                text="A table about document review schedules.",
                chunk_type="table",
            ),
            hit(
                "image:0",
                doc_id="image",
                doc_title="images.jpg",
                text=(
                    "Image description:\n"
                    "A soldier is kneeling and handling ammunition while another soldier operates artillery."
                ),
                doc_summary="Soldiers handling ammunition and operating artillery.",
                topics=["soldier", "artillery"],
            ),
        ][:limit]

    def retrieve_authorized_chunks(
        self,
        *,
        qdrant_filter: dict[str, object],
        structured_only: bool,
        limit: int,
    ) -> list[SearchHit]:
        return [
            hit("policy:table", doc_id="policy", doc_title="Policy.pdf", text="A table about document review schedules.", chunk_type="table"),
            hit("climate:1", doc_id="climate", doc_title="Climate.pdf", text="Climate report summary."),
            hit(
                "image:0",
                doc_id="image",
                doc_title="images.jpg",
                text=(
                    "Image description:\n"
                    "A soldier is kneeling and handling ammunition while another soldier operates artillery."
                ),
                doc_summary="Soldiers handling ammunition and operating artillery.",
                topics=["soldier", "artillery"],
            ),
        ][:limit]


class FakeBroadSummaryQdrant(FakeBroadDocumentQdrant):
    def search(self, _vector: list[float], *, limit: int, qdrant_filter: dict[str, object]) -> list[SearchHit]:
        return []


class RecallEmbedder:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def embed(self, query: str) -> list[float]:
        self.queries.append(query)
        return [float(len(self.queries) - 1)]


class FakeDefinitionQdrant:
    def prepare_for_query(self, _vector_size: int) -> bool:
        return True

    def search(self, vector: list[float], *, limit: int, qdrant_filter: dict[str, object]) -> list[SearchHit]:
        query_index = int(vector[0])
        if query_index == 0:
            return [
                hit(
                    "ztmm:100",
                    doc_id="ztmm",
                    doc_title="ztmm.pdf",
                    text="Table 3 lists functions in the Devices Pillar.",
                    page=16,
                )
            ][:limit]
        return [
            hit(
                "ztmm:98",
                doc_id="ztmm",
                doc_title="ztmm.pdf",
                text="A device refers to any asset, including hardware, software, and firmware, that can connect to a network.",
                page=16,
            )
        ][:limit]


class FakeDefinitionAlreadyFoundQdrant(FakeDefinitionQdrant):
    def search(self, vector: list[float], *, limit: int, qdrant_filter: dict[str, object]) -> list[SearchHit]:
        return [
            hit(
                "ztmm:98",
                doc_id="ztmm",
                doc_title="ztmm.pdf",
                text="A device refers to any asset, including hardware, software, and firmware, that can connect to a network.",
                page=16,
            )
        ][:limit]


class FakeDefinitionFalsePositiveQdrant(FakeDefinitionQdrant):
    def search(self, vector: list[float], *, limit: int, qdrant_filter: dict[str, object]) -> list[SearchHit]:
        query_index = int(vector[0])
        if query_index == 0:
            return [
                hit(
                    "ztmm:45",
                    doc_id="ztmm",
                    doc_title="ztmm.pdf",
                    text="The Zero Trust Maturity Model is a maturity model. Its pillars include Identity, Devices, Networks, Applications, and Data.",
                    page=6,
                )
            ][:limit]
        return super().search(vector, limit=limit, qdrant_filter=qdrant_filter)


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


def definition_plan(query: str) -> RoutePlan:
    return RoutePlan(
        original_query=query,
        resolved_query=query,
        intent="factual_simple",
        public_intent="factual_simple",
        top_k=4,
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


def test_broad_document_scope_focuses_on_subject_tokens() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="What are all the soldiers doing in all the documents?"),
        user=UserContext(user_id="user", email="user@example.com", group_paths=("/admin",)),
        started=0.0,
    )
    ctx["route_plan"] = route_plan(ctx["request"].query)

    hits = retrieve_candidates(ctx, config=FakeConfig(), ollama=FakeEmbedder(), qdrant=FakeBroadDocumentQdrant())

    doc_ids = {item.payload["doc_id"] for item in hits}
    assert doc_ids == {"image"}
    assert hits[0].payload.get("exhaustive_scope_origin") == "document_class_scope"
    assert "soldier" in hits[0].payload["text"].lower()


def test_broad_document_summary_scope_still_keeps_all_documents() -> None:
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query="Summarize all documents"),
        user=UserContext(user_id="user", email="user@example.com", group_paths=("/admin",)),
        started=0.0,
    )
    ctx["route_plan"] = route_plan(ctx["request"].query)

    hits = retrieve_candidates(ctx, config=FakeConfig(), ollama=FakeEmbedder(), qdrant=FakeBroadSummaryQdrant())

    doc_ids = {item.payload["doc_id"] for item in hits}
    assert doc_ids == {"policy", "climate", "image"}
    assert all(item.payload.get("exhaustive_scope_origin") == "document_class_scope" for item in hits)


def test_definition_query_runs_bounded_recall_expansion_when_top_evidence_is_incomplete() -> None:
    query = "How does ZTMM define devices?"
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query=query),
        user=UserContext(user_id="user", email="user@example.com", group_paths=("/admin",)),
        started=0.0,
    )
    ctx["route_plan"] = definition_plan(query)
    embedder = RecallEmbedder()

    hits = retrieve_candidates(ctx, config=FakeConfig(), ollama=embedder, qdrant=FakeDefinitionQdrant())

    assert [item.payload["chunk_id"] for item in hits[:2]] == ["ztmm:98", "ztmm:100"]
    assert hits[0].payload["recall_origin"] == "answer_type_expansion"
    assert embedder.queries[:2] == [query, "ztmm devices definition"]


def test_definition_query_skips_recall_expansion_when_definition_is_already_present() -> None:
    query = "How does ZTMM define devices?"
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query=query),
        user=UserContext(user_id="user", email="user@example.com", group_paths=("/admin",)),
        started=0.0,
    )
    ctx["route_plan"] = definition_plan(query)
    embedder = RecallEmbedder()

    hits = retrieve_candidates(ctx, config=FakeConfig(), ollama=embedder, qdrant=FakeDefinitionAlreadyFoundQdrant())

    assert [item.payload["chunk_id"] for item in hits] == ["ztmm:98"]
    assert embedder.queries == [query]


def test_definition_recall_ignores_generic_overview_cues() -> None:
    query = "How does the Zero Trust Maturity Model define a device?"
    ctx = initial_state(
        trace_id="trace",
        session_id="session",
        request=QueryRequest(query=query),
        user=UserContext(user_id="user", email="user@example.com", group_paths=("/admin",)),
        started=0.0,
    )
    ctx["route_plan"] = definition_plan(query)
    embedder = RecallEmbedder()

    hits = retrieve_candidates(ctx, config=FakeConfig(), ollama=embedder, qdrant=FakeDefinitionFalsePositiveQdrant())

    assert [item.payload["chunk_id"] for item in hits[:2]] == ["ztmm:98", "ztmm:45"]
    assert embedder.queries[:2] == [query, "zero trust device definition"]
