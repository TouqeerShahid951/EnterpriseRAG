"""Failure provenance for document parsing stages."""

from .state import IngestDependencies
from ..errors import IncompletePdfError


def parser_failure_provenance(
    deps: IngestDependencies,
    content_type: str | None,
    file_path: str,
    exc: Exception,
) -> dict[str, object]:
    if isinstance(exc, IncompletePdfError):
        return {**exc.provenance, "routing_mode": "parse_failed",
                "errors": [*exc.provenance.get("errors", []), {"component": "parser", "code": exc.code}]}
    document_kind = (
        "json"
        if getattr(exc, "code", None) == "json_parse_failed"
        else document_kind_from(content_type, file_path)
    )
    structured_kind = document_kind in {"json", "csv", "xlsx"}
    parser_config: dict[str, object] = (
        {}
        if structured_kind
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
        "primary_parser": document_kind if structured_kind else "layered",
        "secondary_parser": None if structured_kind else "docling",
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
    if normalized == "application/vnd.openxmlformats-officedocument.wordprocessingml.document" or file_path.lower().endswith(".docx"):
        return "docx"
    if normalized == "application/vnd.openxmlformats-officedocument.presentationml.presentation" or file_path.lower().endswith(".pptx"):
        return "pptx"
    if normalized == "text/csv" or file_path.lower().endswith(".csv"):
        return "csv"
    if normalized == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" or file_path.lower().endswith(".xlsx"):
        return "xlsx"
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
