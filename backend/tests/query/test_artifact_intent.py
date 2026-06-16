from rag.query.artifact_intent import cleaned_content_query, parse_artifact_request


def test_source_pdf_filename_does_not_request_pdf_output() -> None:
    request = parse_artifact_request("Generate a docx file summarizing FIR_02_kidnapping.pdf.")

    assert request is not None
    assert request.formats == ("docx",)
    assert cleaned_content_query(request.original_query) == "summarizing FIR_02_kidnapping.pdf"


def test_explicit_pdf_output_still_detected_with_source_pdf_filename() -> None:
    request = parse_artifact_request("Generate a pdf summary of FIR_02_kidnapping.pdf.")

    assert request is not None
    assert request.formats == ("pdf",)


def test_multiple_explicit_outputs_are_preserved() -> None:
    request = parse_artifact_request("Generate a docx and pdf file for the selected evidence.")

    assert request is not None
    assert request.formats == ("docx", "pdf")
