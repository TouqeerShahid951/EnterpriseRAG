from rag.connectors.models import CONNECTOR_RECORD_CONTENT_TYPE
from rag.ingestion.parsers.document import parse_document


def test_connector_record_parser_uses_direct_chunk_shape() -> None:
    parsed = parse_document(
        b'{"title":"FIR row","identity":{"id":123},'
        b'"data":{"fir_number":"FIR-2024-88","status":"Open"}}',
        content_type=CONNECTOR_RECORD_CONTENT_TYPE,
        file_path="memory://record.connector.json",
        min_chars_per_page=10,
    )

    assert parsed.provenance["document_kind"] == "connector_record"
    assert parsed.provenance["routing_mode"] == "direct_chunks"
    assert parsed.items[0].parser == "connector_record"
    assert "FIR-2024-88" in parsed.items[0].text
