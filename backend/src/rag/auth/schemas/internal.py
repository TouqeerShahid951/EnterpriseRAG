"""Authentication-owned internal HTTP contracts."""

from typing import Any

from rag.shared.contracts.http import ContractModel


class AbacFilterResponse(ContractModel):
    filter: dict[str, Any]
