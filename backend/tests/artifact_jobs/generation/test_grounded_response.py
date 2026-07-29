from rag.artifact_jobs.generation.validation import validate_document_bundle
from rag.artifact_jobs.grounded_response import build_grounded_artifact_payload
from rag.shared.contracts.evidence import SourceAnchor


def test_grounded_response_seed_is_render_ready_and_preserves_all_paragraphs() -> None:
    plan, evidence, bundle = build_grounded_artifact_payload(
        original_request="Export the previous answer as PDF",
        content_query="What are the quarterly risks?",
        answer="Quarterly risk is elevated.\n\nVendor exposure increased.",
        sources=[
            SourceAnchor(
                doc_id="doc-1",
                doc_title="Quarterly Risk.pdf",
                chunk_id="chunk-1",
                page=2,
                excerpt=(
                    "Quarterly risk is elevated because vendor exposure increased."
                ),
                group_path="/",
            )
        ],
    )

    validation = validate_document_bundle(bundle, plan=plan, evidence=evidence)

    assert validation.passed
    assert len(bundle.content.sections[0].blocks) == 2
    assert len(bundle.presentation.slides) == 1
