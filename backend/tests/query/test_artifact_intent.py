from rag.query.artifact_intent import cleaned_content_query, parse_artifact_request


def test_source_pdf_filename_does_not_request_pdf_output() -> None:
    request = parse_artifact_request("Generate a docx file summarizing FIR_02_kidnapping.pdf.")

    assert request is not None
    assert request.formats == ("docx",)
    assert cleaned_content_query(request.original_query) == "summarize FIR_02_kidnapping.pdf"


def test_artifact_content_query_normalizes_leading_operation() -> None:
    request = parse_artifact_request("Generate a docx file summarizing the crimes in FIRs")

    assert request is not None
    assert request.content_query == "summarize the crimes in FIRs"


def test_explicit_pdf_output_still_detected_with_source_pdf_filename() -> None:
    request = parse_artifact_request("Generate a pdf summary of FIR_02_kidnapping.pdf.")

    assert request is not None
    assert request.formats == ("pdf",)


def test_multiple_explicit_outputs_are_preserved() -> None:
    request = parse_artifact_request("Generate a docx and pdf file for the selected evidence.")

    assert request is not None
    assert request.formats == ("docx", "pdf")


def test_detailed_presentation_query_keeps_business_topic_clean() -> None:
    request = parse_artifact_request("Create a detailed presentation of all crimes in the FIRs")

    assert request is not None
    assert request.content_query == "all crimes in the FIRs"


def test_detail_instruction_does_not_pollute_artifact_topic() -> None:
    request = parse_artifact_request("Create a detailed presentation of All the Crime Commited with details in the all FIRs")

    assert request is not None
    assert request.content_query == "All the Crime Commited in all FIRs"
