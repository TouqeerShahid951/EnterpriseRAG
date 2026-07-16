# ruff: noqa: F401, F403, F405

from query_retrieval_common_support import *


class RecallEmbedder:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def embed(self, query: str) -> list[float]:
        self.queries.append(query)
        return [float(len(self.queries) - 1)]

class FakeDefinitionQdrant:
    def prepare_for_query(self, _vector_size: int) -> bool:
        return True

    def search(
        self, vector: list[float], *, limit: int, qdrant_filter: dict[str, object]
    ) -> list[SearchHit]:
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
    def search(
        self, vector: list[float], *, limit: int, qdrant_filter: dict[str, object]
    ) -> list[SearchHit]:
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
    def search(
        self, vector: list[float], *, limit: int, qdrant_filter: dict[str, object]
    ) -> list[SearchHit]:
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

class FakeExhaustiveRecallQdrant:
    def prepare_for_query(self, _vector_size: int) -> bool:
        return True

    def search(
        self, vector: list[float], *, limit: int, qdrant_filter: dict[str, object]
    ) -> list[SearchHit]:
        if int(vector[0]) == 0:
            text = "Table 3 lists device terms."
        else:
            text = "A device refers to a network-connected asset."
        return [
            hit(
                "terms:device",
                doc_id="terms",
                doc_title="Device Terms.pdf",
                text=text,
            )
        ][:limit]

    def retrieve_authorized_chunks(
        self,
        *,
        qdrant_filter: dict[str, object],
        structured_only: bool,
        limit: int,
        deadline: float | None = None,
    ) -> list[SearchHit]:
        return [
            hit(
                "terms:device",
                doc_id="terms",
                doc_title="Device Terms.pdf",
                text="Table 3 lists device terms.",
                authorized_scan_complete=False,
            )
        ][:limit]

class FakeNamedRecallQdrant(FakeExhaustiveRecallQdrant):
    def search(
        self, vector: list[float], *, limit: int, qdrant_filter: dict[str, object]
    ) -> list[SearchHit]:
        if int(vector[0]) == 0:
            doc_id = "samsung"
            title = "Samsung Manual.pdf"
            text = "Table 3 lists device terms."
        else:
            doc_id = "other"
            title = "Other Manual.pdf"
            text = "A device refers to a network-connected asset."
        return [
            hit(
                f"{doc_id}:device",
                doc_id=doc_id,
                doc_title=title,
                text=text,
            )
        ][:limit]

    def retrieve_document_chunks(
        self,
        *,
        document_ids: list[str],
        qdrant_filter: dict[str, object],
        structured_only: bool,
        limit: int,
        deadline: float | None = None,
    ) -> list[SearchHit]:
        return [
            hit(
                "samsung:device",
                doc_id="samsung",
                doc_title="Samsung Manual.pdf",
                text="Table 3 lists device terms.",
                authorized_scan_complete=True,
            )
        ][:limit]

__all__ = [item for item in globals() if not item.startswith("__")]
