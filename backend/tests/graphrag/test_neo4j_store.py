from rag.graphrag.models import CommunitySummary, SourceRef
from rag.graphrag.neo4j_store import Neo4jConfig, Neo4jGraphStore


class FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def data(self):
        return self._rows

    def consume(self):
        return None


class FakeSession:
    def __init__(self, calls):
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, query, **params):
        self.calls.append((query, params))
        return FakeResult()


class FakeDriver:
    def __init__(self):
        self.calls = []

    def session(self, *, database):
        self.database = database
        return FakeSession(self.calls)


def test_ensure_schema_runs_constraints_and_indexes() -> None:
    driver = FakeDriver()
    store = Neo4jGraphStore(
        config=Neo4jConfig(uri="bolt://neo4j:7687", user="neo4j", password="pw"),
        driver=driver,
    )

    store.ensure_schema()

    queries = "\n".join(query for query, _params in driver.calls)
    assert "CREATE CONSTRAINT graph_document_id" in queries
    assert "CREATE CONSTRAINT graph_entity_id" in queries
    assert "CREATE INDEX graph_summary_partition" in queries
    assert driver.database == "neo4j"


def test_replace_partition_summaries_deletes_old_partition_and_upserts_sources() -> None:
    driver = FakeDriver()
    store = Neo4jGraphStore(
        config=Neo4jConfig(uri="bolt://neo4j:7687", user="neo4j", password="pw"),
        driver=driver,
    )
    summary = CommunitySummary(
        id="summary-1",
        community_id="community-1",
        partition_key="/ops|clearance:2",
        group_path="/ops",
        clearance_level="NATO_CONFIDENTIAL",
        clearance_rank=2,
        level=0,
        title="Risk pattern",
        summary="A risk pattern is present.",
        source_refs=[SourceRef(doc_id="doc-1", chunk_id="chunk-1")],
    )

    store.replace_partition_summaries(partition="/ops|clearance:2", summaries=[summary])

    queries = [query for query, _params in driver.calls]
    assert "MATCH (summary:CommunitySummary" in queries[0]
    assert "MATCH (community:Community" in queries[1]
    upsert_params = driver.calls[-1][1]
    assert upsert_params["partition_key"] == "/ops|clearance:2"
    assert upsert_params["source_doc_ids"] == ["doc-1"]
    assert upsert_params["source_chunk_ids"] == ["chunk-1"]
    assert '"doc_id": "doc-1"' in upsert_params["source_refs_json"]


def test_gds_projection_is_undirected_for_leiden() -> None:
    driver = FakeDriver()
    store = Neo4jGraphStore(
        config=Neo4jConfig(uri="bolt://neo4j:7687", user="neo4j", password="pw"),
        driver=driver,
    )

    store.detect_communities_with_gds("/ops|clearance:2")

    queries = "\n".join(query for query, _params in driver.calls)
    assert "gds.graph.project(" in queries
    assert "undirectedRelationshipTypes: ['*']" in queries


def test_delete_document_graph_removes_graph_records_and_scrubs_entity_sources() -> None:
    driver = FakeDriver()
    store = Neo4jGraphStore(
        config=Neo4jConfig(uri="bolt://neo4j:7687", user="neo4j", password="pw"),
        driver=driver,
    )

    store.delete_document_graph("doc-1")

    queries = "\n".join(query for query, _params in driver.calls)
    assert "CREATE CONSTRAINT graph_document_id" in queries
    assert "MATCH (doc:Document {id: $doc_id})" in queries
    assert "RELATES_TO {doc_id: $doc_id}" in queries
    assert "GraphClaim {doc_id: $doc_id}" in queries
    assert "entity.source_doc_ids = [value IN coalesce(entity.source_doc_ids, []) WHERE value <> $doc_id]" in queries
    assert "entity.source_chunk_ids = [" in queries
    assert "entity.community_id = null" in queries
    assert "DETACH DELETE entity" in queries


def test_entity_upsert_unions_existing_provenance() -> None:
    driver = FakeDriver()
    store = Neo4jGraphStore(
        config=Neo4jConfig(uri="bolt://neo4j:7687", user="neo4j", password="pw"),
        driver=driver,
    )

    store._upsert_entities([], partition="/ops|clearance:1")

    query = driver.calls[-1][0]
    assert "coalesce(entity.source_doc_ids, [])" in query
    assert "coalesce(entity.source_chunk_ids, [])" in query
    assert "CASE WHEN value IN acc THEN acc ELSE acc + value END" in query
