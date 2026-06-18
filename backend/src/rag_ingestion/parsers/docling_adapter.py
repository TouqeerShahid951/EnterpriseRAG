"""Docling structured-document adapter for PDF layout extraction."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import replace
from io import BytesIO
import os
import signal
import threading
import time
from typing import Any, Iterable, Iterator

from rag.shared.runtime_offline import apply_runtime_offline_defaults, runtime_offline_enabled
from rag_ingestion.docling_models import (
    build_rapidocr_options,
    configured_docling_artifacts_path,
    verify_docling_offline_artifacts,
)

from .layout_blocks import LayoutBlock, blocks_to_items
from .models import BBox, ParsedPdfItem
from .tables import _markdown_table

DOCLING_SOURCE_FLAG = "source:docling_layout"
DEFAULT_DOCLING_CONVERT_TIMEOUT_SECONDS = 180.0
DoclingProgressCallback = Callable[[dict[str, object]], None]


class DoclingConversionTimeoutError(TimeoutError):
    """Raised when a single Docling conversion batch exceeds its local budget."""


def parse_docling_pdf(
    file_bytes: bytes,
    *,
    pages: set[int] | None = None,
    allow_page_repair: bool = True,
    mark_ocr: bool = False,
    page_batch_size: int | None = None,
    progress_callback: DoclingProgressCallback | None = None,
    progress_phase: str = "docling",
) -> list[ParsedPdfItem]:
    if pages is not None and not pages:
        return []
    page_groups = _bounded_page_groups(pages, page_batch_size) if pages else []
    converter, stream_type = _docling_imports(allow_ocr=allow_page_repair, input_format="pdf")
    if isinstance(converter, type):
        converter = converter()
    groups: list[set[int] | None] = page_groups or [pages]
    group_count = len(groups)
    total_pages = len(pages) if pages else 1
    completed_pages = 0
    items: list[ParsedPdfItem] = []
    for group_index, page_group in enumerate(groups, start=1):
        _emit_docling_progress(
            progress_callback,
            phase=progress_phase,
            status="running",
            pages=page_group,
            current=completed_pages,
            total=total_pages,
            group_index=group_index,
            group_count=group_count,
            allow_page_repair=allow_page_repair,
            mark_ocr=mark_ocr,
        )
        items.extend(
            _parse_docling_pdf_group(
                file_bytes,
                converter=converter,
                stream_type=stream_type,
                pages=page_group,
                allow_page_repair=allow_page_repair,
                mark_ocr=mark_ocr,
            )
        )
        completed_pages = min(total_pages, completed_pages + _group_page_count(page_group, total_pages))
        _emit_docling_progress(
            progress_callback,
            phase=progress_phase,
            status="complete",
            pages=page_group,
            current=completed_pages,
            total=total_pages,
            group_index=group_index,
            group_count=group_count,
            allow_page_repair=allow_page_repair,
            mark_ocr=mark_ocr,
        )
    return _renumber_items(items)


def _parse_docling_pdf_group(
    file_bytes: bytes,
    *,
    converter: Any,
    stream_type: type[Any],
    pages: set[int] | None,
    allow_page_repair: bool,
    mark_ocr: bool,
) -> list[ParsedPdfItem]:
    stream = stream_type(name="document.pdf", stream=BytesIO(file_bytes))
    kwargs: dict[str, object] = {}
    if pages:
        kwargs["page_range"] = (min(pages), max(pages))
    result = _convert_docling(converter, stream, kwargs)
    document = result.document
    items = structured_docling_items(document, pages=pages)
    if mark_ocr:
        items = _mark_ocr_items(items)
    if items or not allow_page_repair:
        return items
    return _markdown_text_items(document, pages=pages, start_index=0, mark_ocr=mark_ocr)


def parse_docling_docx(file_bytes: bytes) -> list[ParsedPdfItem]:
    converter, stream_type = _docling_imports(allow_ocr=False, input_format="docx")
    stream = stream_type(name="document.docx", stream=BytesIO(file_bytes))
    result = _convert_docling(converter, stream, {})
    return structured_docling_items(result.document)


def structured_docling_items(document: Any, *, pages: set[int] | None = None) -> list[ParsedPdfItem]:
    blocks = docling_layout_blocks(document, pages=pages)
    return blocks_to_items(blocks, parser="docling")


def docling_layout_blocks(document: Any, *, pages: set[int] | None = None) -> list[LayoutBlock]:
    blocks: list[LayoutBlock] = []
    seen_tables: set[int] = set()
    seen_refs: set[str] = set()
    for item, depth in _iter_docling_items(document):
        self_ref = _self_ref(item)
        if self_ref:
            seen_refs.add(self_ref)
        block = _block_from_docling_item(item, document, depth=depth)
        if block is None:
            continue
        if block.role == "table":
            seen_tables.add(id(item))
        if pages and block.page_no and block.page_no not in pages:
            continue
        if pages and block.page_no is None:
            continue
        blocks.append(block)
    for table in getattr(document, "tables", []) or []:
        if id(table) in seen_tables:
            continue
        self_ref = _self_ref(table)
        if self_ref and self_ref in seen_refs:
            continue
        block = _table_block(table, document, depth=None)
        if block is None:
            continue
        if pages and block.page_no and block.page_no not in pages:
            continue
        if pages and block.page_no is None:
            continue
        blocks.append(block)
    return blocks


def is_docling_available() -> bool:
    try:
        _docling_imports(allow_ocr=False, input_format="pdf")
    except ImportError:
        return False
    return True


def _docling_imports(*, allow_ocr: bool, input_format: str) -> tuple[Any, type[Any]]:
    apply_runtime_offline_defaults()
    try:
        from docling.datamodel.base_models import DocumentStream, InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
    except ImportError as exc:
        raise ImportError("Docling dependency is not installed.") from exc
    options: dict[Any, Any] = {}
    if input_format == "pdf":
        artifacts_path = configured_docling_artifacts_path()
        if runtime_offline_enabled() and artifacts_path is None:
            raise RuntimeError("DOCLING_ARTIFACTS_PATH must be set when AIRGAP_RUNTIME_OFFLINE is enabled.")
        if runtime_offline_enabled() and artifacts_path is not None:
            verify_docling_offline_artifacts(artifacts_path, require_ocr=allow_ocr)
        pipeline_options = PdfPipelineOptions(
            do_ocr=allow_ocr,
            artifacts_path=artifacts_path,
        )
        if allow_ocr:
            pipeline_options.ocr_options = build_rapidocr_options()
        options[InputFormat.PDF] = PdfFormatOption(pipeline_options=pipeline_options)
    elif input_format == "docx":
        try:
            from docling.document_converter import WordFormatOption
        except ImportError as exc:
            raise ImportError("Docling Word document support is not installed.") from exc
        docx_format = getattr(InputFormat, "DOCX", None)
        if docx_format is None:
            raise ImportError("Docling DOCX input format is not available.")
        options[docx_format] = WordFormatOption()
    else:
        raise ValueError(f"unsupported docling input format: {input_format}")
    converter = DocumentConverter(
        format_options=options
    )
    return converter, DocumentStream


def _convert_docling(converter: Any, stream: Any, kwargs: dict[str, object]) -> Any:
    if isinstance(converter, type):
        converter = converter()
    with _docling_conversion_deadline(_docling_convert_timeout_seconds()):
        return converter.convert(stream, **kwargs)


def _emit_docling_progress(
    callback: DoclingProgressCallback | None,
    *,
    phase: str,
    status: str,
    pages: set[int] | None,
    current: int,
    total: int,
    group_index: int,
    group_count: int,
    allow_page_repair: bool,
    mark_ocr: bool,
) -> None:
    if callback is None:
        return
    callback(
        {
            "phase": phase,
            "status": status,
            "pages": tuple(sorted(pages)) if pages else (),
            "current": max(0, current),
            "total": max(0, total),
            "group_index": max(1, group_index),
            "group_count": max(1, group_count),
            "allow_page_repair": allow_page_repair,
            "mark_ocr": mark_ocr,
        }
    )


def _group_page_count(pages: set[int] | None, fallback_total: int) -> int:
    if pages:
        return len(pages)
    return max(1, fallback_total)


def _docling_convert_timeout_seconds() -> float:
    value = os.getenv("DOCLING_CONVERT_TIMEOUT_SECONDS", str(DEFAULT_DOCLING_CONVERT_TIMEOUT_SECONDS)).strip()
    return max(0.0, float(value or DEFAULT_DOCLING_CONVERT_TIMEOUT_SECONDS))


@contextmanager
def _docling_conversion_deadline(timeout_seconds: float) -> Iterator[None]:
    if timeout_seconds <= 0 or not hasattr(signal, "SIGALRM") or threading.current_thread() is not threading.main_thread():
        yield
        return

    def raise_timeout(_signum: int, _frame: object) -> None:
        raise DoclingConversionTimeoutError(f"Docling conversion exceeded {timeout_seconds:g}s.")

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()
    signal.signal(signal.SIGALRM, raise_timeout)
    signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    try:
        yield
    finally:
        elapsed = time.monotonic() - started
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, max(0.001, previous_timer[0] - elapsed), previous_timer[1])


def _iter_docling_items(document: Any) -> Iterator[tuple[Any, int | None]]:
    yielded = False
    body = getattr(document, "body", None)
    seen_refs: set[str] = set()
    seen_ids: set[int] = set()
    for item, depth in _walk_docling_tree(body, document, depth=1, seen_refs=seen_refs, seen_ids=seen_ids):
        yielded = True
        yield item, depth
    if yielded:
        return
    for collection_name in ("texts", "tables", "pictures"):
        for item in getattr(document, collection_name, []) or []:
            yield item, None
            yielded = True
    if yielded:
        return
    iterator = getattr(document, "iterate_items", None)
    if iterator is not None:
        try:
            for value in iterator():
                if isinstance(value, tuple) and len(value) >= 2:
                    yield value[0], _int_or_none(value[1])
                else:
                    yield value, None
        except Exception:
            pass


def _walk_docling_tree(
    node: Any,
    document: Any,
    *,
    depth: int,
    seen_refs: set[str],
    seen_ids: set[int],
) -> Iterator[tuple[Any, int]]:
    if node is None:
        return
    for child in getattr(node, "children", []) or []:
        resolved = _resolve_docling_ref(child, document)
        if resolved is None:
            continue
        ref = _self_ref(resolved)
        if ref:
            if ref in seen_refs:
                continue
            seen_refs.add(ref)
        else:
            identity = id(resolved)
            if identity in seen_ids:
                continue
            seen_ids.add(identity)
        yield resolved, depth
        yield from _walk_docling_tree(resolved, document, depth=depth + 1, seen_refs=seen_refs, seen_ids=seen_ids)


def _resolve_docling_ref(value: Any, document: Any) -> Any | None:
    if value is None:
        return None
    get_ref = getattr(value, "get_ref", None)
    if get_ref is not None:
        try:
            return get_ref()
        except Exception:
            pass
    get_ref = getattr(document, "get_ref", None)
    if get_ref is not None:
        try:
            return get_ref(value)
        except Exception:
            pass
    cref = getattr(value, "cref", None)
    if isinstance(cref, str):
        return _resolve_cref(document, cref)
    return value


def _resolve_cref(document: Any, cref: str) -> Any | None:
    parts = [part for part in cref.lstrip("#/").split("/") if part]
    if len(parts) != 2:
        return None
    collection = getattr(document, parts[0], None)
    try:
        index = int(parts[1])
    except ValueError:
        return None
    try:
        return collection[index]
    except Exception:
        return None


def _block_from_docling_item(item: Any, document: Any, *, depth: int | None) -> LayoutBlock | None:
    role = _role(item)
    if role == "table":
        return _table_block(item, document, depth=depth)
    text = _text(item)
    if not text:
        return None
    page_no = _page_no(item)
    flags = [DOCLING_SOURCE_FLAG]
    if page_no is None:
        flags.append("missing_item_provenance")
    return LayoutBlock(
        text=text,
        role=role,
        page_no=page_no,
        bbox=_bbox(item, document),
        source="docling",
        confidence=_confidence(item),
        quality_flags=flags,
        section_level=_section_level(item, depth) if role == "heading" else None,
    )


def _table_block(table: Any, document: Any, *, depth: int | None) -> LayoutBlock | None:
    page_no = _page_no(table)
    rows = _table_rows(table, document)
    markdown = _markdown_table(rows)
    if not markdown:
        markdown = _table_markdown(table, document)
    if not markdown:
        return None
    caption = _caption(table, document)
    text = f"{caption}\n{markdown}" if caption and caption not in markdown else markdown
    flags = [DOCLING_SOURCE_FLAG, "docling_table_repair", "docling_table_repaired"]
    if page_no is None:
        flags.append("missing_item_provenance")
    row_count = max(0, len(rows) - 1)
    if row_count <= 1:
        flags.append("table_structure_low_confidence")
    return LayoutBlock(
        text=text,
        role="table",
        page_no=page_no,
        bbox=_bbox(table, document),
        source="docling",
        confidence=_confidence(table),
        table_rows=rows,
        quality_flags=flags,
        section_level=_section_level(table, depth),
        table_json={"rows": rows, "row_count": row_count, "caption": caption or ""},
    )


def _markdown_text_items(document: Any, *, pages: set[int] | None, start_index: int, mark_ocr: bool) -> list[ParsedPdfItem]:
    markdown = _document_markdown(document)
    if not markdown:
        return []
    page_start = min(pages) if pages else None
    page_end = max(pages) if pages else None
    flags = [DOCLING_SOURCE_FLAG, "docling_page_repair", "docling_page_repaired"]
    if mark_ocr:
        flags.append("source:ocr")
    if page_start is None:
        flags.append("missing_item_provenance")
    return [
        ParsedPdfItem(
            index=start_index,
            text=markdown,
            item_type="text",
            page_start=page_start,
            page_end=page_end,
            parser="docling",
            quality_flags=flags,
        )
    ]


def _mark_ocr_items(items: list[ParsedPdfItem]) -> list[ParsedPdfItem]:
    return [
        replace(item, quality_flags=sorted({*item.quality_flags, "source:ocr", "docling_ocr"}))
        for item in items
    ]


def _document_markdown(document: Any) -> str:
    export = getattr(document, "export_to_markdown", None)
    if export is None:
        return ""
    try:
        value = export()
    except Exception:
        return ""
    return value.strip() if isinstance(value, str) else ""


def _contiguous_page_groups(pages: set[int]) -> list[set[int]]:
    groups: list[set[int]] = []
    current: list[int] = []
    for page_no in sorted(pages):
        if current and page_no != current[-1] + 1:
            groups.append(set(current))
            current = []
        current.append(page_no)
    if current:
        groups.append(set(current))
    return groups


def _bounded_page_groups(pages: set[int], page_batch_size: int | None) -> list[set[int]]:
    groups = _contiguous_page_groups(pages)
    if page_batch_size is None:
        return groups
    bounded: list[set[int]] = []
    batch_size = max(1, page_batch_size)
    for group in groups:
        ordered = sorted(group)
        for offset in range(0, len(ordered), batch_size):
            bounded.append(set(ordered[offset : offset + batch_size]))
    return bounded


def _is_contiguous_pages(pages: set[int]) -> bool:
    ordered = sorted(pages)
    return all(right == left + 1 for left, right in zip(ordered, ordered[1:]))


def _renumber_items(items: list[ParsedPdfItem]) -> list[ParsedPdfItem]:
    return [replace(item, index=index) for index, item in enumerate(items)]


def _role(item: Any) -> str:
    label = _label(item)
    class_name = type(item).__name__.lower()
    if "table" in class_name or label == "table":
        return "table"
    if label in {"section_header", "heading", "title"} or "sectionheader" in class_name:
        return "heading"
    if label == "caption" or "caption" in class_name:
        return "caption"
    if label in {"picture", "figure"} or "picture" in class_name or "figure" in class_name:
        return "figure"
    return "text"


def _label(item: Any) -> str:
    value = getattr(item, "label", "")
    value = getattr(value, "value", value)
    return str(value or "").strip().lower().replace("-", "_")


def _text(item: Any) -> str:
    for attr in ("text", "orig"):
        value = getattr(item, attr, None)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return ""


def _confidence(item: Any) -> float | None:
    for attr in ("confidence", "conf", "score"):
        value = getattr(item, attr, None)
        if isinstance(value, (int, float)):
            return max(0.0, min(1.0, float(value)))
    for prov in getattr(item, "prov", []) or []:
        for attr in ("confidence", "conf", "score"):
            value = getattr(prov, attr, None)
            if isinstance(value, (int, float)):
                return max(0.0, min(1.0, float(value)))
    return None


def _table_rows(table: Any, document: Any) -> list[list[str]]:
    export = getattr(table, "export_to_dataframe", None)
    if export is None:
        return []
    try:
        dataframe = export(doc=document)
    except TypeError:
        dataframe = export()
    except Exception:
        return []
    columns = [str(column).strip() for column in getattr(dataframe, "columns", [])]
    rows: list[list[str]] = []
    if any(columns):
        rows.append(columns)
    try:
        values = dataframe.fillna("").astype(str).values.tolist()
    except Exception:
        values = []
    rows.extend([[str(cell).strip() for cell in row] for row in values if any(str(cell).strip() for cell in row)])
    return rows


def _table_markdown(table: Any, document: Any) -> str:
    for method_name in ("export_to_markdown", "export_to_html"):
        method = getattr(table, method_name, None)
        if method is None:
            continue
        try:
            value = method(doc=document)
        except TypeError:
            value = method()
        except Exception:
            continue
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _caption(table: Any, document: Any) -> str | None:
    direct = getattr(table, "caption_text", None)
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    for attr in ("caption", "label"):
        value = getattr(table, attr, None)
        if isinstance(value, str) and value.strip() and value.strip().lower() != "table":
            return value.strip()
    captions = getattr(table, "captions", None)
    if isinstance(captions, str) and captions.strip():
        return captions.strip()
    if isinstance(captions, Iterable):
        for caption in captions:
            text = _resolve_text_ref(caption, document)
            if text:
                return text
    return None


def _resolve_text_ref(value: Any, document: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    text = getattr(value, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()
    resolved = _resolve_docling_ref(value, document)
    text = getattr(resolved, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()
    return None


def _page_no(item: Any) -> int | None:
    for prov in getattr(item, "prov", []) or []:
        value = getattr(prov, "page_no", None)
        if isinstance(value, int):
            return value
    return None


def _bbox(item: Any, document: Any | None = None) -> BBox | None:
    for prov in getattr(item, "prov", []) or []:
        bbox = getattr(prov, "bbox", None)
        if bbox is None:
            continue
        values = (
            getattr(bbox, "l", None),
            getattr(bbox, "t", None),
            getattr(bbox, "r", None),
            getattr(bbox, "b", None),
        )
        if not all(isinstance(value, (int, float)) for value in values):
            continue
        left, top, right, bottom = (float(value) for value in values)
        origin = str(getattr(getattr(bbox, "coord_origin", ""), "value", getattr(bbox, "coord_origin", ""))).lower()
        page_no = getattr(prov, "page_no", None)
        page_height = _page_height(document, page_no) if isinstance(page_no, int) else None
        if "bottomleft" in origin and page_height:
            top, bottom = page_height - top, page_height - bottom
        top, bottom = min(top, bottom), max(top, bottom)
        return (left, top, right, bottom)
    return None


def _page_height(document: Any | None, page_no: int | None) -> float | None:
    if document is None or page_no is None:
        return None
    pages = getattr(document, "pages", None)
    page = None
    if isinstance(pages, dict):
        page = pages.get(page_no)
    elif isinstance(pages, list) and 0 < page_no <= len(pages):
        page = pages[page_no - 1]
    size = getattr(page, "size", None)
    height = getattr(size, "height", None)
    return float(height) if isinstance(height, (int, float)) else None


def _section_level(item: Any, depth: int | None) -> int | None:
    value = _int_or_none(getattr(item, "level", None))
    if value is not None and value > 0:
        return value
    if depth is not None and depth > 0:
        return depth
    return None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _self_ref(item: Any) -> str | None:
    value = getattr(item, "self_ref", None)
    return value if isinstance(value, str) else None
