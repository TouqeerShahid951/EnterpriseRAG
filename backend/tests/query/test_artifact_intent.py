import pytest

from rag.artifact_jobs.request_text import (
    cleaned_content_query as artifact_cleaned_content_query,
)
from rag.query.artifact_intent import (
    cleaned_content_query,
    parse_artifact_request,
    references_previous_answer,
    requires_conversation_context,
)


def test_query_reexports_artifact_owned_request_cleaner() -> None:
    assert cleaned_content_query is artifact_cleaned_content_query


def test_source_pdf_filename_does_not_request_pdf_output() -> None:
    request = parse_artifact_request(
        "Generate a docx file summarizing FIR_02_kidnapping.pdf."
    )

    assert request is not None
    assert request.formats == ("docx",)
    assert (
        cleaned_content_query(request.original_query)
        == "summarize FIR_02_kidnapping.pdf"
    )


def test_artifact_content_query_normalizes_leading_operation() -> None:
    request = parse_artifact_request(
        "Generate a docx file summarizing the crimes in FIRs"
    )

    assert request is not None
    assert request.content_query == "summarize the crimes in FIRs"


def test_explicit_pdf_output_still_detected_with_source_pdf_filename() -> None:
    request = parse_artifact_request("Generate a pdf summary of FIR_02_kidnapping.pdf.")

    assert request is not None
    assert request.formats == ("pdf",)


def test_multiple_explicit_outputs_are_preserved() -> None:
    request = parse_artifact_request(
        "Generate a docx and pdf file for the selected evidence."
    )

    assert request is not None
    assert request.formats == ("docx", "pdf")


def test_detailed_presentation_query_keeps_business_topic_clean() -> None:
    request = parse_artifact_request(
        "Create a detailed presentation of all crimes in the FIRs"
    )

    assert request is not None
    assert request.content_query == "all crimes in the FIRs"


def test_detail_instruction_does_not_pollute_artifact_topic() -> None:
    request = parse_artifact_request(
        "Create a detailed presentation of All the Crime Commited with details in the all FIRs"
    )

    assert request is not None
    assert request.content_query == "All the Crime Commited in all FIRs"


@pytest.mark.parametrize(
    ("query", "formats"),
    [
        ("Create a PDF report about quarterly risk", ("pdf",)),
        ("Export this as PDF", ("pdf",)),
        ("Convert this into PDF", ("pdf",)),
        ("Save this as a PDF", ("pdf",)),
        (
            "Could you create a PowerPoint presentation about incident trends?",
            ("pptx",),
        ),
        ("Please generate a DOCX summary of the selected evidence", ("docx",)),
        ("Using the selected documents, create a PDF risk register", ("pdf",)),
        ("I would like you to prepare slides about policy changes", ("pptx",)),
        ("Give me the current answer as a Word document", ("docx",)),
        ("I need a PDF summary of quarterly risk", ("pdf",)),
        ("Turn that into a PDF", ("pdf",)),
        ("Summarize quarterly risk and export it to PDF", ("pdf",)),
    ],
)
def test_explicit_artifact_commands_are_detected(
    query: str,
    formats: tuple[str, ...],
) -> None:
    request = parse_artifact_request(query)

    assert request is not None
    assert request.formats == formats


@pytest.mark.parametrize(
    "query",
    [
        "How do I create PDF files in Python?",
        "Can you explain how to make PowerPoint slides programmatically?",
        "How can I generate a PDF report in Python?",
        "What library should I use to build PPTX presentations?",
        "Explain how to create a Word document programmatically.",
        "Please explain how to create PDF files.",
        "The service can generate PDF reports.",
        "Why does export to PDF fail?",
        "Can this system create PDF reports?",
        "PDF creation in Python",
        "Build a presentation layer in React",
        "Build a presentation component for the dashboard",
        "Create a PDF parser in Python",
        "Build a DOCX API",
        "Build a presentation API that exports PDF",
        "Create a PDF parser that exports DOCX",
        "Download the quarterly risk PDF",
    ],
)
def test_instructional_or_descriptive_format_mentions_are_not_artifact_requests(
    query: str,
) -> None:
    assert parse_artifact_request(query) is None


@pytest.mark.parametrize("query", ["Convert this into PDF", "Save this as a PDF"])
def test_pronoun_only_conversion_requests_ask_for_clarification(query: str) -> None:
    request = parse_artifact_request(query)

    assert request is not None
    assert request.content_query == "this"
    assert request.needs_clarification


@pytest.mark.parametrize(
    ("query", "content_query"),
    [
        ("Make that a PDF", "that"),
        ("Turn that into a PDF", "that"),
        (
            "Summarize quarterly risk and export it to PDF",
            "Summarize quarterly risk",
        ),
        (
            "Could you create a PowerPoint about incident trends?",
            "incident trends?",
        ),
        ("Please make me a PDF about quarterly risk", "quarterly risk"),
    ],
)
def test_artifact_content_query_removes_output_wrappers(
    query: str,
    content_query: str,
) -> None:
    request = parse_artifact_request(query)

    assert request is not None
    assert request.content_query == content_query


def test_context_reference_is_distinct_from_a_concrete_relative_period() -> None:
    assert requires_conversation_context("this policy")
    assert not requires_conversation_context("this quarter's risks")


def test_previous_answer_reference_is_explicitly_identified() -> None:
    assert references_previous_answer("the previous answer")
    assert not references_previous_answer("quarterly risk")


def test_software_topic_format_is_not_added_as_an_output() -> None:
    request = parse_artifact_request("Create slides about a PDF parser")

    assert request is not None
    assert request.formats == ("pptx",)
    assert request.content_query == "PDF parser"
