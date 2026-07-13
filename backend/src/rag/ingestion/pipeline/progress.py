"""Progress reporting and cancellation helpers for ingestion stages."""

from ..errors import IngestJobCancelled
from ..parsers.models import ParsedPdfItem
from .state import IngestDependencies

PARSE_PROGRESS_COMPLETE = 36
IMAGE_PROGRESS_START = 35
IMAGE_PROGRESS_END = 36
METADATA_PROGRESS_START = 37
METADATA_PROGRESS_END = 49


def page_progress_reporter(deps: IngestDependencies, job_id: str):
    last_reported = 0

    def report(page_no: int, page_count: int) -> None:
        nonlocal last_reported
        raise_if_job_cancelled(deps, job_id)
        if not should_report_progress(page_no, page_count, last_reported=last_reported):
            return
        last_reported = page_no
        deps.backend.update_job(
            job_id=job_id,
            status="processing",
            progress_pct=bounded_progress(20, 30, page_no, page_count),
            stage_progress=items_progress(
                "pages", page_no, page_count, f"Parsing page {page_no} of {page_count}"
            ),
        )

    return report


def docling_progress_reporter(deps: IngestDependencies, job_id: str):
    def report(event: dict[str, object]) -> None:
        raise_if_job_cancelled(deps, job_id)
        current = int_value(event.get("current"))
        total = max(1, int_value(event.get("total")))
        deps.backend.update_job(
            job_id=job_id,
            status="processing",
            progress_pct=bounded_progress(30, 34, current, total),
            stage_progress=items_progress(
                "pages", current, total, docling_progress_label(event)
            ),
        )

    return report


def vision_layout_progress_reporter(deps: IngestDependencies, job_id: str):
    def report(event: dict[str, object]) -> None:
        raise_if_job_cancelled(deps, job_id)
        current = int_value(event.get("current"))
        total = max(1, int_value(event.get("total")))
        deps.backend.update_job(
            job_id=job_id,
            status="processing",
            progress_pct=bounded_progress(34, 35, current, total),
            stage_progress=items_progress(
                "pages", current, total, vision_layout_progress_label(event)
            ),
        )

    return report


def image_progress_reporter(deps: IngestDependencies, job_id: str):
    def report(event: dict[str, object]) -> None:
        raise_if_job_cancelled(deps, job_id)
        current = int_value(event.get("current"))
        total = max(1, int_value(event.get("total")))
        deps.backend.update_job(
            job_id=job_id,
            status="processing",
            progress_pct=bounded_progress(
                IMAGE_PROGRESS_START, IMAGE_PROGRESS_END, current, total
            ),
            stage_progress=items_progress(
                "images", current, total, image_progress_label(event)
            ),
        )

    return report


def items_progress(
    unit: str, current: int, total: int, label: str
) -> dict[str, object]:
    return {
        "unit": unit,
        "current": max(0, current),
        "total": max(0, total),
        "label": label,
    }


def raise_if_job_cancelled(deps: IngestDependencies, job_id: str) -> None:
    ensure_lease = getattr(deps.backend, "ensure_lease", None)
    if callable(ensure_lease):
        ensure_lease(job_id)
    get_status = getattr(deps.backend, "get_job_status", None)
    if not callable(get_status):
        return
    if get_status(job_id=job_id).status == "cancelled":
        raise IngestJobCancelled(job_id=job_id)


def duration_label(total_seconds: int) -> str:
    if total_seconds < 60:
        return f"{total_seconds}s"
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}m {seconds}s" if seconds else f"{minutes}m"


def should_report_progress(current: int, total: int, *, last_reported: int = 0) -> bool:
    return current <= 1 or current >= total or current - last_reported >= 5


def bounded_progress(start: int, end: int, current: int, total: int) -> int:
    if total <= 0:
        return start
    span = max(0, end - start)
    return max(start, min(end, start + int(span * (current / total))))


def page_count(items: list[ParsedPdfItem]) -> int:
    pages = [
        page
        for item in items
        for page in (item.page_start, item.page_end)
        if isinstance(page, int) and page > 0
    ]
    return max(pages) if pages else 0


def docling_progress_label(event: dict[str, object]) -> str:
    phase = str(event.get("phase") or "docling")
    status = str(event.get("status") or "running")
    current = int_value(event.get("current"))
    total = max(1, int_value(event.get("total")))
    pages = int_tuple(event.get("pages"))
    page_count = len(pages) if pages else 1
    if status == "complete":
        selected_end = max(1, min(total, current))
        selected_start = max(1, selected_end - page_count + 1)
    else:
        selected_start = max(1, min(total, current + 1))
        selected_end = max(selected_start, min(total, current + page_count))
    selected_label = (
        f"selected page {selected_start}"
        if selected_start == selected_end
        else f"selected pages {selected_start}-{selected_end}"
    )
    page_label = pdf_page_label(pages)
    action = docling_action(phase=phase, status=status)
    return f"{action} {selected_label} of {total} ({page_label})"


def docling_action(*, phase: str, status: str) -> str:
    complete = status == "complete"
    if phase == "ocr_repair":
        return "Docling OCR repaired" if complete else "Docling OCR repairing"
    if phase == "page_repair":
        return "Docling repaired" if complete else "Docling repairing"
    if phase == "ocr_fallback":
        return (
            "Docling OCR fallback parsed"
            if complete
            else "Docling OCR fallback parsing"
        )
    if phase == "layout":
        return "Docling analyzed" if complete else "Docling analyzing"
    return "Docling processed" if complete else "Docling processing"


def vision_layout_progress_label(event: dict[str, object]) -> str:
    status = str(event.get("status") or "running")
    current = int_value(event.get("current"))
    total = max(1, int_value(event.get("total")))
    page_no = int_value(event.get("page"))
    page_label = f"PDF page {page_no}" if page_no else "PDF page"
    if status == "complete":
        return f"Vision layout repaired page {current} of {total} ({page_label})"
    if status == "skipped":
        reason = str(event.get("reason") or "not used")
        return (
            f"Vision layout skipped page {current} of {total} ({page_label}: {reason})"
        )
    if status == "failed":
        return f"Vision layout failed page {current} of {total} ({page_label})"
    return f"Vision layout repairing page {current + 1} of {total} ({page_label})"


def image_progress_label(event: dict[str, object]) -> str:
    status = str(event.get("status") or "running")
    current = int_value(event.get("current"))
    total = max(1, int_value(event.get("total")))
    page_no = int_value(event.get("page"))
    source_kind = str(event.get("source_kind") or "image")
    image_label = image_source_label(source_kind)
    page_label = f" (PDF page {page_no})" if page_no else ""
    if status == "complete":
        return (
            f"Image analysis completed {image_label} {current} of {total}{page_label}"
        )
    return f"Image analysis analyzing {image_label} {min(current + 1, total)} of {total}{page_label}"


def image_source_label(source_kind: str) -> str:
    if source_kind == "pdf_page_image":
        return "page image"
    if source_kind == "pdf_page_layout":
        return "layout image"
    if source_kind == "pdf_image":
        return "embedded image"
    if source_kind == "docx_media":
        return "document image"
    return "image"


def pdf_page_label(pages: tuple[int, ...]) -> str:
    if not pages:
        return "whole document"
    ranges: list[str] = []
    start = pages[0]
    previous = pages[0]
    for page_no in pages[1:]:
        if page_no == previous + 1:
            previous = page_no
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = page_no
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    prefix = "PDF page" if len(pages) == 1 else "PDF pages"
    return f"{prefix} {', '.join(ranges)}"


def int_tuple(value: object) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple, set)):
        return ()
    values: list[int] = []
    for item in value:
        if isinstance(item, int):
            values.append(item)
    return tuple(sorted(values))


def int_value(value: object) -> int:
    return value if isinstance(value, int) else 0
