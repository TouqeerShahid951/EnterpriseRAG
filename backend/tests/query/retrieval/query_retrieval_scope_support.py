# ruff: noqa: F401, F403, F405

from query_retrieval_common_support import *


class FakeManualQdrant:
    def prepare_for_query(self, _vector_size: int) -> bool:
        return True

    def search(
        self, _vector: list[float], *, limit: int, qdrant_filter: dict[str, object]
    ) -> list[SearchHit]:
        return [
            hit(
                "policy:1",
                doc_id="policy",
                doc_title="Maintenance Policy.pdf",
                doc_type="policy",
                text="Maintenance details.",
            ),
            hit(
                "manual-a:1",
                doc_id="manual-a",
                doc_title="Operations Guide.pdf",
                doc_type="manual",
                text="Pump details.",
            ),
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
                "manual-a:1",
                doc_id="manual-a",
                doc_title="Operations Guide.pdf",
                doc_type="manual",
                text="Pump details.",
            ),
            hit(
                "manual-b:1",
                doc_id="manual-b",
                doc_title="Equipment Handbook.pdf",
                generated_doc_type="manual",
                text="Valve details.",
            ),
            hit(
                "policy:1",
                doc_id="policy",
                doc_title="Maintenance Policy.pdf",
                doc_type="policy",
                text="Maintenance details.",
            ),
        ][:limit]

class FakeScopedManualQdrant(FakeManualQdrant):
    def __init__(self) -> None:
        self.document_scan: dict[str, object] | None = None

    def search(
        self, _vector: list[float], *, limit: int, qdrant_filter: dict[str, object]
    ) -> list[SearchHit]:
        return [
            hit(
                "samsung:precautions",
                doc_id="samsung",
                doc_title="samsung repair manual.pdf",
                doc_type="manual",
                text="Refer to Tools for Disassembly and Assembly.",
            ),
            hit(
                "policy:1",
                doc_id="policy",
                doc_title="Maintenance Policy.pdf",
                doc_type="policy",
                text="Maintenance details.",
            ),
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
        self.document_scan = {
            "document_ids": document_ids,
            "qdrant_filter": qdrant_filter,
            "structured_only": structured_only,
            "limit": limit,
        }
        return [
            hit(
                "samsung:tools",
                doc_id="samsung",
                doc_title="samsung repair manual.pdf",
                doc_type="manual",
                text="Safety Goggles and ESD Safe Mat",
                authorized_scan_complete=True,
            )
        ]

class FakeRealAdapterManualQdrant(FakeManualQdrant):
    def __init__(self) -> None:
        self.document_scan_called = False
        self.authorized_scan_called = False

    def retrieve_document_chunks(
        self,
        *,
        document_ids: list[str],
        qdrant_filter: dict[str, object],
        structured_only: bool,
        limit: int,
        deadline: float | None = None,
    ) -> list[SearchHit]:
        self.document_scan_called = True
        return [
            hit(
                "manual-a:1",
                doc_id="manual-a",
                doc_title="Operations Guide.pdf",
                doc_type="manual",
                text="Pump details.",
            ),
        ][:limit]

    def retrieve_authorized_chunks(
        self,
        *,
        qdrant_filter: dict[str, object],
        structured_only: bool,
        limit: int,
        deadline: float | None = None,
    ) -> list[SearchHit]:
        self.authorized_scan_called = True
        return super().retrieve_authorized_chunks(
            qdrant_filter=qdrant_filter,
            structured_only=structured_only,
            limit=limit,
            deadline=deadline,
        )

class FakeBroadDocumentQdrant:
    def prepare_for_query(self, _vector_size: int) -> bool:
        return True

    def search(
        self, _vector: list[float], *, limit: int, qdrant_filter: dict[str, object]
    ) -> list[SearchHit]:
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
        deadline: float | None = None,
    ) -> list[SearchHit]:
        return [
            hit(
                "policy:table",
                doc_id="policy",
                doc_title="Policy.pdf",
                text="A table about document review schedules.",
                chunk_type="table",
            ),
            hit(
                "climate:1",
                doc_id="climate",
                doc_title="Climate.pdf",
                text="Climate report summary.",
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

class FakeBroadSummaryQdrant(FakeBroadDocumentQdrant):
    def search(
        self, _vector: list[float], *, limit: int, qdrant_filter: dict[str, object]
    ) -> list[SearchHit]:
        return []

class FakeBroadSectionQdrant(FakeBroadSummaryQdrant):
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
                "manual:tools-heading",
                doc_id="manual",
                doc_title="Repair Manual.pdf",
                text="Required equipment",
                parent_section_id="tools",
                parent_chunk_id="tools-parent",
            ),
            hit(
                "manual:goggles",
                doc_id="manual",
                doc_title="Repair Manual.pdf",
                text="Safety Goggles",
                parent_chunk_id="tools-parent",
            ),
            hit(
                "manual:mat",
                doc_id="manual",
                doc_title="Repair Manual.pdf",
                text="ESD Safe Mat",
                parent_chunk_id="tools-parent",
            ),
            hit(
                "manual:gloves",
                doc_id="manual",
                doc_title="Repair Manual.pdf",
                text="Safety Gloves",
                parent_chunk_id="tools-parent",
            ),
            hit(
                "manual:warranty",
                doc_id="manual",
                doc_title="Repair Manual.pdf",
                text="Warranty exclusions",
                parent_section_id="warranty",
            ),
        ][:limit]

class FakeRealAdapterBroadQdrant(FakeBroadSummaryQdrant):
    def __init__(self) -> None:
        self.document_scan_called = False
        self.authorized_scan_called = False

    def search(
        self, _vector: list[float], *, limit: int, qdrant_filter: dict[str, object]
    ) -> list[SearchHit]:
        return [
            hit("doc-a:1", doc_id="doc-a", doc_title="Document A.pdf", text="Summary A")
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
        self.document_scan_called = True
        return [
            hit("doc-a:1", doc_id="doc-a", doc_title="Document A.pdf", text="Summary A")
        ][:limit]

    def retrieve_authorized_chunks(
        self,
        *,
        qdrant_filter: dict[str, object],
        structured_only: bool,
        limit: int,
        deadline: float | None = None,
    ) -> list[SearchHit]:
        self.authorized_scan_called = True
        return [
            hit(
                "doc-a:1", doc_id="doc-a", doc_title="Document A.pdf", text="Summary A"
            ),
            hit(
                "doc-b:1", doc_id="doc-b", doc_title="Document B.pdf", text="Summary B"
            ),
        ][:limit]

class FakeExpiredBroadQdrant(FakeRealAdapterBroadQdrant):
    def retrieve_authorized_chunks(
        self,
        *,
        qdrant_filter: dict[str, object],
        structured_only: bool,
        limit: int,
        deadline: float | None = None,
    ) -> list[SearchHit]:
        self.authorized_scan_called = True
        return []

class FakeWrongNamedScopeQdrant(FakeRealAdapterBroadQdrant):
    def search(
        self, _vector: list[float], *, limit: int, qdrant_filter: dict[str, object]
    ) -> list[SearchHit]:
        return [
            hit(
                "generic:1",
                doc_id="generic",
                doc_title="Generic Equipment Manual.pdf",
                doc_type="manual",
                text="Generic equipment.",
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
        self.authorized_scan_called = True
        return self.search([], limit=limit, qdrant_filter=qdrant_filter)

class FakeSamsungSemanticMissQdrant(FakeRealAdapterBroadQdrant):
    def search(
        self, _vector: list[float], *, limit: int, qdrant_filter: dict[str, object]
    ) -> list[SearchHit]:
        return [
            hit(
                "generic:1",
                doc_id="generic",
                doc_title="Generic Safety Guide.pdf",
                text="Wear safety equipment.",
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
        self.authorized_scan_called = True
        return [
            *self.search([], limit=limit, qdrant_filter=qdrant_filter),
            hit(
                "samsung:tools",
                doc_id="samsung",
                doc_title="Samsung Galaxy S24 Repair Manual.pdf",
                text="Safety Goggles and ESD Safe Mat",
                authorized_scan_complete=True,
            ),
        ][:limit]

class FakeDevicePolicyScopeQdrant(FakeSamsungSemanticMissQdrant):
    def search(
        self, _vector: list[float], *, limit: int, qdrant_filter: dict[str, object]
    ) -> list[SearchHit]:
        return [
            hit(
                "device-policy:1",
                doc_id="device-policy",
                doc_title="Device Policy.pdf",
                text="Corporate device policy.",
            )
        ][:limit]

class FakeGenericRepairManualScopeQdrant(FakeSamsungSemanticMissQdrant):
    def search(
        self, _vector: list[float], *, limit: int, qdrant_filter: dict[str, object]
    ) -> list[SearchHit]:
        return [
            hit(
                "acme:tools",
                doc_id="acme",
                doc_title="Acme Repair Manual.pdf",
                doc_type="manual",
                text="Acme repair tools.",
            )
        ][:limit]

class FakeHospitalPolicyScopeQdrant(FakeSamsungSemanticMissQdrant):
    def search(
        self, _vector: list[float], *, limit: int, qdrant_filter: dict[str, object]
    ) -> list[SearchHit]:
        return [
            hit(
                "hospital:policy",
                doc_id="hospital",
                doc_title="Hospital Use Policy.pdf",
                doc_type="policy",
                text="Hospital equipment policy.",
            )
        ][:limit]

class FakeHomePolicyScopeQdrant(FakeSamsungSemanticMissQdrant):
    def search(
        self, _vector: list[float], *, limit: int, qdrant_filter: dict[str, object]
    ) -> list[SearchHit]:
        return [
            hit(
                "home:policy",
                doc_id="home",
                doc_title="Home Repair Policy.pdf",
                doc_type="policy",
                text="Home repair policy.",
            )
        ][:limit]

class FakeManualModeGuideScopeQdrant(FakeSamsungSemanticMissQdrant):
    def search(
        self, _vector: list[float], *, limit: int, qdrant_filter: dict[str, object]
    ) -> list[SearchHit]:
        return [
            hit(
                "manual-mode:guide",
                doc_id="manual-mode",
                doc_title="Manual Mode Guide.pdf",
                doc_type="guide",
                text="Manual operating mode.",
            )
        ][:limit]

class FakeManualSuffixNotesScopeQdrant(FakeRealAdapterBroadQdrant):
    def search(
        self, _vector: list[float], *, limit: int, qdrant_filter: dict[str, object]
    ) -> list[SearchHit]:
        return [
            hit(
                "section-notes:1",
                doc_id="section-notes",
                doc_title="Samsung Manual Section 3 Notes.pdf",
                text="Section notes.",
            ),
            hit(
                "version-notes:1",
                doc_id="version-notes",
                doc_title="Samsung Manual Version 2 Notes.pdf",
                text="Version notes.",
            ),
        ][:limit]

    def retrieve_authorized_chunks(
        self,
        *,
        qdrant_filter: dict[str, object],
        structured_only: bool,
        limit: int,
        deadline: float | None = None,
    ) -> list[SearchHit]:
        self.authorized_scan_called = True
        return [
            *self.search([], limit=limit, qdrant_filter=qdrant_filter),
            hit(
                "samsung:tools",
                doc_id="samsung",
                doc_title="Samsung Repair Manual.pdf",
                text="Safety Goggles and ESD Safe Mat",
            ),
        ][:limit]

class FakeExplicitManualScopeQdrant(FakeRealAdapterBroadQdrant):
    def search(
        self, _vector: list[float], *, limit: int, qdrant_filter: dict[str, object]
    ) -> list[SearchHit]:
        return [
            hit(
                "screen-guide:1",
                doc_id="screen-guide",
                doc_title="Cracked Screen Guide.pdf",
                text="Screen repair overview.",
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
        self.authorized_scan_called = True
        return [
            *self.search([], limit=limit, qdrant_filter=qdrant_filter),
            hit(
                "samsung-operations:tools",
                doc_id="samsung-operations",
                doc_title="Samsung Operations Manual.pdf",
                text="Approved repair tools.",
            ),
        ][:limit]

__all__ = [item for item in globals() if not item.startswith("__")]
