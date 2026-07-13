"""Failure provenance for document parsing stages."""

from .state import IngestDependencies


def parser_failure_provenance(
    deps: IngestDependencies,
    content_type: str | None,
    file_path: str,
    exc: Exception,
) -> dict[str, object]:
    document_kind = (
        "json"
        if getattr(exc, "code", None) == "json_parse_failed"
        else document_kind_from(content_type, file_path)
    )
    parser_config: dict[str, object] = (
        {}
        if document_kind == "json"
        else {
            "min_chars_per_page": deps.min_chars_per_page,
            "quality_preset": deps.ingestion_quality_preset,
            "weak_page_threshold": deps.weak_page_threshold,
            "full_doc_weak_page_ratio": deps.full_doc_weak_page_ratio,
            "layered_docling_max_pages": deps.layered_docling_max_pages,
            "layered_docling_max_page_ratio": deps.layered_docling_max_page_ratio,
            "prefer_full_document_docling": deps.prefer_full_document_docling,
            "layered_docling_batch_pages": deps.layered_docling_batch_pages,
        }
    )
    return {
        "version": 1,
        "document_kind": document_kind,
        "page_count": None,
        "primary_parser": "json" if document_kind == "json" else "layered",
        "secondary_parser": None if document_kind == "json" else "docling",
        "routing_mode": "parse_failed",
        "config": parser_config,
        "docling_selection": None,
        "parser_item_counts": {},
        "parser_page_counts": {},
        "quality_flag_counts": {},
        "fallback": None,
        "errors": [{"component": "parser", "code": type(exc).__name__}],
    }


def document_kind_from(content_type: str | None, file_path: str) -> str:
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if (
        normalized
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        or file_path.lower().endswith(".docx")
    ):
        return "docx"
    if normalized in {"image/jpeg", "image/png"} or file_path.lower().endswith(
        (".jpg", ".jpeg", ".png")
    ):
        return "image"
    if normalized == "application/json" or file_path.lower().endswith(".json"):
        return "json"
    if (
        normalized
        and normalized != "application/pdf"
        and not file_path.lower().endswith(".pdf")
    ):
        return "unsupported"
    return "pdf"
