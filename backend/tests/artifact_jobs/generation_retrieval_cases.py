from __future__ import annotations

from rag.artifact_jobs.retrieval import retrieve_document_evidence
from rag.documents.models import DocumentRecord
from rag.retrieval.contracts import AuthorizedCorpusRequest, RetrievedChunk

from generation_optimization_support import (
    artifact_job,
    document_record,
    structured_rows_plan,
)


def test_retrieval_infers_document_family_scope() -> None:
    retriever = ScopedRetriever()

    evidence = retrieve_document_evidence(
        artifact_job(original_request="Create a presentation of all crimes in FIRs"),
        structured_rows_plan(),
        retriever=retriever,
        document_repo=CatalogDocumentRepository(
            [
                document_record("fir-1", "FIR_02_kidnapping.pdf"),
                document_record(
                    "image-1",
                    "preview16.jpg",
                    summary="The image shows a tank firing.",
                ),
                document_record(
                    "manual-1",
                    "Dell PowerEdge R630 Technical Manual.pdf",
                ),
            ]
        ),
    )

    assert retriever.document_scans == [["fir-1"]]
    assert [record.doc_title for record in evidence.records] == [
        "FIR_02_kidnapping.pdf"
    ]


def test_retrieval_infers_policy_scope_from_doc_type() -> None:
    retriever = ScopedRetriever(
        {
            "policy-1": "Access-Control-Policy.pdf",
            "policy-2": "Vendor-Risk-Policy.pdf",
            "manual-1": "Dell PowerEdge R630 Technical Manual.pdf",
        }
    )

    evidence = retrieve_document_evidence(
        artifact_job(original_request="Create a presentation of all risks in policies"),
        structured_rows_plan(title="Policy Risks", query="all risks in policies"),
        retriever=retriever,
        document_repo=CatalogDocumentRepository(
            [
                document_record(
                    "policy-1",
                    "Access-Control-Policy.pdf",
                    doc_type="policy",
                ),
                document_record(
                    "policy-2",
                    "Vendor-Risk-Policy.pdf",
                    doc_type="policy",
                ),
                document_record(
                    "manual-1",
                    "Dell PowerEdge R630 Technical Manual.pdf",
                    doc_type="manual",
                ),
            ]
        ),
    )

    assert retriever.document_scans == [["policy-1", "policy-2"]]
    assert [record.doc_title for record in evidence.records] == [
        "Access-Control-Policy.pdf",
        "Vendor-Risk-Policy.pdf",
    ]


def test_retrieval_does_not_scan_every_structured_row_without_scope() -> None:
    retriever = ScopedRetriever()

    evidence = retrieve_document_evidence(
        artifact_job(original_request="Create a presentation of all standards"),
        structured_rows_plan(title="Standards", query="all standards"),
        retriever=retriever,
        document_repo=CatalogDocumentRepository(
            [
                document_record(
                    "manual-1",
                    "Dell PowerEdge R630 Technical Manual.pdf",
                )
            ]
        ),
    )

    assert retriever.document_scans == []
    assert evidence.records == []


class CatalogDocumentRepository:
    def __init__(self, documents: list[DocumentRecord]) -> None:
        self.documents = documents

    def list_documents(self, *, state: str = "active") -> list[DocumentRecord]:
        assert state == "active"
        return self.documents


class ScopedRetriever:
    def __init__(self, titles: dict[str, str] | None = None) -> None:
        self.document_scans: list[list[str]] = []
        self.titles = titles or {"fir-1": "FIR_02_kidnapping.pdf"}

    def search(
        self,
        _request: AuthorizedCorpusRequest,
    ) -> tuple[RetrievedChunk, ...]:
        return ()

    def scan_documents(
        self,
        request: AuthorizedCorpusRequest,
        *,
        structured_only: bool,
        limit: int,
    ) -> tuple[RetrievedChunk, ...]:
        _ = structured_only, limit
        document_ids = list(request.document_ids)
        self.document_scans.append(list(document_ids))
        return tuple(
            retrieved_chunk(
                doc_id,
                self.titles[doc_id],
                f"Evidence for {self.titles[doc_id]}.",
            )
            for doc_id in document_ids
            if doc_id in self.titles
        )


def retrieved_chunk(doc_id: str, title: str, text: str) -> RetrievedChunk:
    return RetrievedChunk(
        point_id=f"{doc_id}:1",
        doc_id=doc_id,
        doc_title=title,
        chunk_id=f"{doc_id}:1",
        page_start=1,
        page_end=1,
        content_type="table_row",
        text=text,
        structured_fields=(("Crime", text),),
        retrieval_score=1.0,
        rerank_score=None,
        identity_keys=frozenset(),
    )
