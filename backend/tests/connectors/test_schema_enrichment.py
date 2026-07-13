from __future__ import annotations

from rag.connectors.schema_enrichment import (
    enrich_schema_table_with_llm,
    initialize_schema_catalog_enrichment,
    schema_catalog_with_table_enrichment_failure,
)


class FakeSchemaEnrichmentLlm:
    def __init__(self, response: str | list[str]) -> None:
        self.responses = response if isinstance(response, list) else [response]
        self.calls = 0
        self.requests: list[dict[str, object]] = []

    def generate_json(self, **kwargs) -> str:
        self.requests.append(dict(kwargs))
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response


def test_schema_table_enrichment_checkpoints_each_table_without_changing_scope() -> None:
    catalog = initialize_schema_catalog_enrichment(
        {
            "tables": [
                {
                    "key": "public.cases",
                    "allowed": True,
                    "sensitive": False,
                    "description": "",
                    "columns": [
                        {
                            "name": "id",
                            "data_type": "integer",
                            "allowed": True,
                            "sensitive": False,
                            "description": "",
                        },
                        {
                            "name": "secret_note",
                            "data_type": "text",
                            "allowed": False,
                            "sensitive": True,
                            "description": "",
                        },
                    ],
                },
                {
                    "key": "public.people",
                    "allowed": True,
                    "sensitive": False,
                    "description": "",
                    "columns": [
                        {
                            "name": "id",
                            "data_type": "integer",
                            "allowed": True,
                            "sensitive": False,
                            "description": "",
                        }
                    ],
                },
            ],
            "relationships": [],
        }
    )
    llm = FakeSchemaEnrichmentLlm(
        '{"tables":[{"key":"public.cases","description":"Operational case records.",'
        '"columns":[{"name":"id","description":"Stable case identifier."},'
        '{"name":"secret_note","description":"Restricted case note."}]}],'
        '"business_rules":[]}'
    )

    enriched = enrich_schema_table_with_llm(
        catalog,
        table_key="public.cases",
        connector_type="postgres",
        profile_name="Cases",
        llm=llm,
        model=None,
    )

    assert enriched["tables"][0]["description"] == "Operational case records."
    assert enriched["tables"][0]["columns"][1]["allowed"] is False
    assert enriched["tables"][0]["columns"][1]["sensitive"] is True
    assert enriched["tables"][1]["description"] == ""
    assert enriched["ai_enrichment"]["status"] == "in_progress"
    assert enriched["ai_enrichment"]["completed_tables"] == 1
    assert enriched["ai_enrichment"]["total_tables"] == 2
    assert "public.people" not in str(llm.requests[0]["prompt"])
    assert "secret_note" in str(llm.requests[0]["prompt"])


def test_schema_table_enrichment_failure_is_checkpointed_and_retryable() -> None:
    catalog = initialize_schema_catalog_enrichment(
        {
            "tables": [
                {"key": "public.cases", "description": "", "columns": []}
            ],
            "relationships": [],
        }
    )
    failed = schema_catalog_with_table_enrichment_failure(
        catalog,
        table_key="public.cases",
        error_message="model timeout",
    )

    assert failed["ai_enrichment"]["status"] == "partial"
    assert failed["ai_enrichment"]["failed_tables"] == 1
    assert (
        failed["ai_enrichment"]["table_statuses"][0]["error_message"]
        == "model timeout"
    )

    retried = enrich_schema_table_with_llm(
        failed,
        table_key="public.cases",
        connector_type="postgres",
        profile_name="Cases",
        llm=FakeSchemaEnrichmentLlm(
            '{"tables":[{"key":"public.cases","description":"Case records."}]}'
        ),
        model=None,
    )

    assert retried["ai_enrichment"]["status"] == "generated"
    assert retried["ai_enrichment"]["failed_tables"] == 0


def test_schema_table_enrichment_requires_descriptions_for_every_column() -> None:
    catalog = initialize_schema_catalog_enrichment(
        {
            "tables": [
                {
                    "key": "public.cases",
                    "description": "",
                    "columns": [
                        {"name": "id", "description": ""},
                        {"name": "status", "description": ""},
                    ],
                }
            ],
            "relationships": [],
        }
    )
    llm = FakeSchemaEnrichmentLlm(
        '{"tables":[{"key":"public.cases","description":"Case records.",'
        '"columns":[{"name":"id","description":"Stable case identifier."}]}]}'
    )

    enriched = enrich_schema_table_with_llm(
        catalog,
        table_key="public.cases",
        connector_type="postgres",
        profile_name="Cases",
        llm=llm,
        model=None,
    )

    assert llm.calls == 2
    assert (
        enriched["tables"][0]["columns"][0]["description"]
        == "Stable case identifier."
    )
    assert enriched["tables"][0]["columns"][1]["description"] == ""
    assert enriched["ai_enrichment"]["status"] == "partial"
    assert enriched["ai_enrichment"]["failed_tables"] == 1
