from rag.graphrag.models import ChunkRecord, GraphEntity


def test_partition_key_includes_exact_group_path_and_clearance_rank() -> None:
    restricted = ChunkRecord(
        doc_id="doc-1",
        chunk_id="chunk-1",
        text="Acme",
        doc_title="Doc",
        group_path="/ops",
        clearance_level="NATO_RESTRICTED",
        clearance_rank=1,
    )
    secret = ChunkRecord(
        doc_id="doc-2",
        chunk_id="chunk-1",
        text="Acme",
        doc_title="Doc",
        group_path="/ops",
        clearance_level="NATO_SECRET",
        clearance_rank=3,
    )

    assert restricted.partition_key == "/ops|clearance:1"
    assert secret.partition_key == "/ops|clearance:3"
    assert restricted.partition_key != secret.partition_key


def test_same_entity_name_gets_distinct_ids_across_partitions() -> None:
    restricted = GraphEntity.from_name(
        name="Acme Corp",
        entity_type="organization",
        partition="/ops|clearance:1",
    )
    secret = GraphEntity.from_name(
        name="Acme Corp",
        entity_type="organization",
        partition="/ops|clearance:3",
    )

    assert restricted.normalized_name == secret.normalized_name
    assert restricted.id != secret.id
