from rag.graphrag.graph_extractor import GraphExtractor
from rag.graphrag.models import ChunkRecord


class FakeLLM:
    def generate_json(self, **kwargs):
        return """
        {
          "entities": [
            {"name": "Acme Corp", "type": "organization", "evidence_text": "Acme Corp", "confidence": 0.9},
            {"name": "New York", "type": "location", "evidence_text": "New York", "confidence": 0.8}
          ],
          "relationships": [
            {
              "source": "Acme   Corp",
              "target": "New York",
              "type": "operates_in",
              "description": "Acme Corp operates in New York.",
              "evidence_text": "Acme Corp operates in New York.",
              "confidence": 0.7
            }
          ],
          "claims": [
            {"entity": "Acme Corp", "claim": "operates in New York", "evidence_text": "Acme Corp operates in New York.", "confidence": 0.7}
          ]
        }
        """


def test_llm_extraction_reuses_normalized_entities_for_edges_and_claims() -> None:
    chunk = ChunkRecord(
        doc_id="doc-1",
        chunk_id="chunk-1",
        text="Acme Corp operates in New York.",
        doc_title="Doc",
        group_path="/ops",
        clearance_level="NATO_CONFIDENTIAL",
        clearance_rank=2,
    )

    result = GraphExtractor(FakeLLM()).extract(chunk)

    entities_by_name = {entity.normalized_name: entity for entity in result.entities}
    assert set(entities_by_name) == {"acme corp", "new york"}
    assert result.relationships[0].source_entity_id == entities_by_name["acme corp"].id
    assert result.relationships[0].target_entity_id == entities_by_name["new york"].id
    assert result.claims[0].entity_id == entities_by_name["acme corp"].id


def test_deterministic_extraction_creates_mentions_and_cooccurrence_edges() -> None:
    chunk = ChunkRecord(
        doc_id="doc-1",
        chunk_id="chunk-1",
        text="Acme Corp met New York Office about Project Apollo.",
        doc_title="Doc",
        group_path="/ops",
        clearance_level="NATO_RESTRICTED",
        clearance_rank=1,
    )

    result = GraphExtractor().extract(chunk)

    assert len(result.entities) >= 2
    assert len(result.mentions) == len(result.entities)
    assert result.relationships
    assert all(relationship.doc_id == "doc-1" for relationship in result.relationships)


def test_seeded_chunk_claims_and_entities_are_preserved() -> None:
    chunk = ChunkRecord(
        doc_id="doc-1",
        chunk_id="chunk-1",
        text="Acme Corp operates Project Apollo in New York.",
        doc_title="Doc",
        group_path="/ops",
        clearance_level="NATO_RESTRICTED",
        clearance_rank=1,
        claims=[
            {
                "id": "claim-1",
                "entity": "Acme Corp",
                "attribute": "operates",
                "value": "Project Apollo",
            }
        ],
        named_entities=[
            {"text": "Acme Corp", "type": "organization"},
            {"text": "New York", "type": "location"},
        ],
    )

    result = GraphExtractor().extract(chunk)

    entities_by_name = {entity.normalized_name: entity for entity in result.entities}
    assert {"acme corp", "new york", "project apollo"}.issubset(entities_by_name)
    assert any(claim.id == "claim-1" and claim.claim == "operates: Project Apollo" for claim in result.claims)
    assert any(relationship.type == "operates" for relationship in result.relationships)
