"""In-memory connector adapter used by local and test workflows."""

from __future__ import annotations

from typing import Any

from ..models import ConnectorQueryResult, ConnectorTestResult
from ..row_mapping import json_safe


class FakeConnector:
    connector_type = "fake"

    def test_connection(
        self, *, config: dict[str, Any], secrets: dict[str, Any]
    ) -> ConnectorTestResult:
        _ = secrets
        records = config.get("records")
        count = len(records) if isinstance(records, list) else 0
        return ConnectorTestResult(
            status="ok", message=f"Fake connector ready with {count} records."
        )

    def introspect(
        self, *, config: dict[str, Any], secrets: dict[str, Any]
    ) -> dict[str, Any]:
        _ = secrets
        records = [item for item in config.get("records", []) if isinstance(item, dict)]
        fields = sorted({key for record in records for key in record})
        return {
            "connector_type": self.connector_type,
            "collections": [
                {
                    "name": "fake.records",
                    "columns": [
                        {
                            "name": field,
                            "type": type(records[0].get(field)).__name__
                            if records
                            else "unknown",
                        }
                        for field in fields
                    ],
                    "sample_count": len(records),
                }
            ],
        }

    def execute_query(
        self,
        *,
        config: dict[str, Any],
        secrets: dict[str, Any],
        query: str,
        row_limit: int,
        timeout_seconds: int,
    ) -> ConnectorQueryResult:
        _ = secrets, timeout_seconds
        rows = [
            item
            for item in config.get("live_query_rows", config.get("records", []))
            if isinstance(item, dict)
        ]
        bounded = [json_safe(row) for row in rows[: max(1, row_limit)]]
        columns = sorted({key for row in bounded for key in row})
        return ConnectorQueryResult(query=query, columns=columns, rows=bounded)
