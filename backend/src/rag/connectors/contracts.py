"""Runtime contract implemented by connector adapters."""

from __future__ import annotations

from typing import Any, Protocol

from .models import ConnectorQueryResult, ConnectorTestResult


class Connector(Protocol):
    connector_type: str

    def test_connection(
        self, *, config: dict[str, Any], secrets: dict[str, Any]
    ) -> ConnectorTestResult: ...

    def introspect(
        self, *, config: dict[str, Any], secrets: dict[str, Any]
    ) -> dict[str, Any]: ...

    def execute_query(
        self,
        *,
        config: dict[str, Any],
        secrets: dict[str, Any],
        query: str,
        row_limit: int,
        timeout_seconds: int,
    ) -> ConnectorQueryResult: ...
