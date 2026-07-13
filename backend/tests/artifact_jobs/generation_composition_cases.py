from __future__ import annotations

import json

from billiard.exceptions import SoftTimeLimitExceeded
import pytest

from rag.artifact_jobs.composer import (
    COMPOSITION_RECORD_TEXT_LIMIT,
    _compose_section,
    compose_document_bundle,
    normalize_bundle_evidence_ids,
)
from rag.artifact_jobs.contracts import (
    ArtifactContentBundle,
    ContentBlock,
    ContentSection,
    EvidenceBackedContent,
    EvidenceRecord,
    PaginatedDocumentSpec,
    PresentationSlide,
    PresentationSpec,
)

from generation_inference_support import (
    CapturingSectionInference,
    FailingInference,
    PresentationFormattingInference,
    ProviderFailureInference,
    SoftTimeFormattingInference,
    SoftTimeInference,
)
from generation_optimization_support import (
    artifact_job,
    content_bundle,
    document_plan,
    evidence_citation,
    evidence_manifest,
    evidence_manifest_for_section,
    evidence_record,
    structured_rows_plan,
)


def test_composer_truncates_evidence_payload_for_llm_prompt() -> None:
    inference = CapturingSectionInference()
    record = evidence_record(text="A" * (COMPOSITION_RECORD_TEXT_LIMIT + 100))

    _compose_section(
        artifact_job(),
        document_plan(),
        "Facts",
        "Summarize the facts.",
        ["paragraph"],
        [record],
        inference=inference,
        model=None,
    )

    assert "A" * COMPOSITION_RECORD_TEXT_LIMIT in inference.prompts[0]
    assert "A" * (COMPOSITION_RECORD_TEXT_LIMIT + 1) not in inference.prompts[0]


def test_composer_failure_falls_back_with_evidence_ids_preserved() -> None:
    bundle = compose_document_bundle(
        artifact_job(),
        document_plan(),
        evidence_manifest(
            [
                evidence_record(text="First fact."),
                evidence_record(evidence_id="E2", text="Second fact."),
            ]
        ),
        inference=FailingInference(),
        model=None,
        section_timeout_seconds=0.01,
    )

    list_items = bundle.content.sections[0].blocks[0].list_items
    assert [item.evidence_ids for item in list_items] == [["E1"], ["E2"]]
    assert [citation.evidence_id for citation in bundle.content.citations] == [
        "E1",
        "E2",
    ]


def test_bundle_evidence_normalization_repairs_missing_ev_prefix() -> None:
    evidence = evidence_manifest(
        [evidence_record(evidence_id="ev_abc123", text="Evidence fact.")]
    )
    section = ContentSection(
        title="Facts",
        blocks=[
            ContentBlock(
                kind="paragraph",
                text="Evidence fact.",
                evidence_ids=["abc123"],
            )
        ],
    )
    bundle = ArtifactContentBundle(
        content=EvidenceBackedContent(
            title="FIR summary",
            purpose="Summarize alleged crimes.",
            sections=[section],
            citations=[evidence_citation()],
        ),
        paginated=PaginatedDocumentSpec(title="FIR summary", sections=[section]),
        presentation=PresentationSpec(
            title="FIR summary",
            slides=[PresentationSlide(title="Facts", blocks=section.blocks)],
        ),
    )

    normalized = normalize_bundle_evidence_ids(bundle, evidence)

    assert normalized.content.sections[0].blocks[0].evidence_ids == ["ev_abc123"]
    assert normalized.paginated.sections[0].blocks[0].evidence_ids == ["ev_abc123"]
    assert normalized.presentation.slides[0].blocks[0].evidence_ids == ["ev_abc123"]
    assert [citation.evidence_id for citation in normalized.content.citations] == [
        "ev_abc123"
    ]


def test_composer_failure_builds_concise_grouped_table() -> None:
    bundle = compose_document_bundle(
        artifact_job(original_request="Create a presentation of all crimes in FIRs"),
        structured_rows_plan(),
        evidence_manifest_for_section(
            "Details",
            [
                EvidenceRecord(
                    evidence_id="E1",
                    section_title="Details",
                    query="all crimes in FIRs details",
                    doc_id="fir-1",
                    doc_title="FIR_02_kidnapping.pdf",
                    chunk_id="fir-1:1",
                    text="",
                    structured_fields={
                        "1. Complainant Information": "Contact Numbers: 03000000000",
                        "Legal Action and Current Status": "This FIR is registered under Section 365-A PPC for kidnapping for ransom.",
                        "Forensic and Physical Evidence": "CCTV footage and call records were collected.",
                    },
                ),
                EvidenceRecord(
                    evidence_id="E2",
                    section_title="Details",
                    query="all crimes in FIRs details",
                    doc_id="fir-2",
                    doc_title="FIR_05_narcotics.pdf",
                    chunk_id="fir-2:1",
                    text="",
                    structured_fields={
                        "2. Accused Information": "Contact Numbers: 03111111111",
                        "Legal Action and Investigation Status": "The case is registered under Section 9(c) of the Control of Narcotic Substances Act.",
                        "Evidence and Investigative Action": "Recovered packets were sent to PFSA for chemical analysis.",
                    },
                ),
            ],
        ),
        inference=FailingInference(),
        model=None,
        section_timeout_seconds=0.01,
    )

    table = bundle.content.sections[0].blocks[0].table
    assert table is not None
    assert table.headers == [
        "Document",
        "Crime / offense",
        "Key details",
        "Evidence / status",
    ]
    assert [row.values[1] for row in table.rows] == ["Kidnapping", "Narcotics"]
    assert "Contact Numbers" not in json.dumps(table.model_dump())


def test_composer_lets_llm_choose_table_structure() -> None:
    inference = CapturingSectionInference()

    bundle = compose_document_bundle(
        artifact_job(original_request="Create a presentation of all risks in policies"),
        structured_rows_plan(title="Policy Risks", query="all risks in policies"),
        evidence_manifest_for_section(
            "Details",
            [
                EvidenceRecord(
                    evidence_id="E1",
                    section_title="Details",
                    query="all risks in policies details",
                    doc_id="policy-1",
                    doc_title="Access-Control-Policy.pdf",
                    chunk_id="policy-1:1",
                    text="",
                    structured_fields={
                        "Risk": "Privileged access without approval",
                        "Control": "Quarterly access review is required.",
                        "Status": "Open",
                    },
                ),
                EvidenceRecord(
                    evidence_id="E2",
                    section_title="Details",
                    query="all risks in policies details",
                    doc_id="policy-2",
                    doc_title="Vendor-Risk-Policy.pdf",
                    chunk_id="policy-2:1",
                    text="",
                    structured_fields={
                        "Risk": "Vendor assessment missing before onboarding",
                        "Control": "Third-party due diligence must be completed.",
                        "Status": "Approved",
                    },
                ),
            ],
        ),
        inference=inference,
        model=None,
        section_timeout_seconds=0.01,
    )

    assert len(inference.prompts) == 2
    assert 'Preferred blocks: ["table"]' in inference.prompts[0]
    assert "structured_fields" in inference.prompts[0]
    assert (
        "Create final DOCX/PDF and presentation formatting specifications"
        in inference.prompts[1]
    )
    assert bundle.content.sections[0].blocks[0].kind == "paragraph"


def test_formatter_llm_chooses_presentation_title_subtitle_and_slides() -> None:
    bundle = compose_document_bundle(
        artifact_job(
            original_request="Create an executive presentation about policy risks",
            requested_formats=("pptx",),
        ),
        structured_rows_plan(title="Policy Risks", query="policy risks"),
        evidence_manifest_for_section(
            "Details",
            [
                EvidenceRecord(
                    evidence_id="E1",
                    section_title="Details",
                    query="policy risks",
                    doc_id="policy-1",
                    doc_title="Access-Control-Policy.pdf",
                    chunk_id="policy-1:1",
                    text="Privileged access without approval is an open risk.",
                    structured_fields={
                        "Risk": "Privileged access without approval",
                        "Status": "Open",
                    },
                )
            ],
        ),
        inference=PresentationFormattingInference(),
        model=None,
        section_timeout_seconds=0.01,
    )

    assert bundle.presentation.title == "Policy Risk Briefing"
    assert bundle.presentation.subtitle == "Executive overview"
    assert [slide.title for slide in bundle.presentation.slides] == [
        "Priority Risks",
        "Actions",
    ]


def test_composer_falls_back_when_generation_provider_is_unavailable() -> None:
    bundle = compose_document_bundle(
        artifact_job(),
        document_plan(),
        evidence_manifest([evidence_record()]),
        inference=ProviderFailureInference(),
        model=None,
        section_timeout_seconds=0.01,
    )

    assert bundle.content.sections[0].blocks[0].list_items[0].evidence_ids == ["E1"]
    assert bundle.presentation.slides


def test_formatter_propagates_soft_time_limit() -> None:
    with pytest.raises(SoftTimeLimitExceeded):
        compose_document_bundle(
            artifact_job(),
            document_plan(),
            evidence_manifest([evidence_record()]),
            inference=SoftTimeFormattingInference(),
            model=None,
            section_timeout_seconds=0.01,
        )


def test_section_composition_propagates_soft_time_limit() -> None:
    with pytest.raises(SoftTimeLimitExceeded):
        compose_document_bundle(
            artifact_job(),
            document_plan(),
            evidence_manifest([evidence_record()]),
            inference=SoftTimeInference(),
            model=None,
            section_timeout_seconds=0.01,
        )


def test_normalizer_drops_generated_references_content_slide() -> None:
    bundle = content_bundle()
    placeholder_slide = PresentationSlide(
        title="References",
        blocks=[ContentBlock(kind="heading", text="References")],
    )
    bundle = bundle.model_copy(
        update={
            "presentation": bundle.presentation.model_copy(
                update={
                    "slides": [*bundle.presentation.slides, placeholder_slide],
                }
            )
        }
    )

    normalized = normalize_bundle_evidence_ids(
        bundle,
        evidence_manifest([evidence_record()]),
    )

    assert [slide.title for slide in normalized.presentation.slides] == ["Facts"]
