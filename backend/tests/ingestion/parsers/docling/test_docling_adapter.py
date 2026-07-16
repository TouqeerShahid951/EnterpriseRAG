from __future__ import annotations

import sys
import types

import pytest

from rag.ingestion.parsers.docling.adapter import _docling_convert_timeout_seconds, _docling_imports, _resolve_docling_ref, docling_layout_blocks, parse_docling_pdf


class FakeBody:
    def __init__(self, children: list[object]) -> None:
        self.children = children


class FakeProvenance:
    page_no = 1


class FakeTextItem:
    text = "Diabetes inpatient guideline"
    label = "text"
    prov = [FakeProvenance()]
    children: list[object]

    def __init__(self) -> None:
        self.children = []


class FakeRefItem:
    cref = "#/texts/0"

    def get_ref(self):
        return self

    def resolve(self, document):
        return document.texts[0]


class FakeDoclingDocument:
    tables: list[object] = []

    def __init__(self, body: FakeBody) -> None:
        self.body = body

    def iterate_items(self):
        raise AssertionError("body traversal should not call docling iterate_items")


def test_docling_layout_blocks_walks_body_without_iterate_items() -> None:
    document = FakeDoclingDocument(FakeBody([FakeTextItem()]))

    blocks = docling_layout_blocks(document)

    assert [block.text for block in blocks] == ["Diabetes inpatient guideline"]
    assert [block.page_no for block in blocks] == [1]


def test_docling_layout_blocks_resolves_body_ref_items() -> None:
    ref = FakeRefItem()
    document = FakeDoclingDocument(FakeBody([ref]))
    document.texts = [FakeTextItem()]

    assert _resolve_docling_ref(ref, document) is document.texts[0]

    blocks = docling_layout_blocks(document)

    assert [block.text for block in blocks] == ["Diabetes inpatient guideline"]


def test_docling_layout_blocks_merges_collections_without_duplicates() -> None:
    body_item = FakeTextItem()
    collection_item = FakeTextItem()
    collection_item.text = "Insulin discharge checklist"
    document = FakeDoclingDocument(FakeBody([body_item]))
    document.texts = [body_item, collection_item]

    blocks = docling_layout_blocks(document)

    assert [block.text for block in blocks] == [
        "Diabetes inpatient guideline",
        "Insulin discharge checklist",
    ]


def test_docling_layout_blocks_ignores_body_cycles() -> None:
    item = FakeTextItem()
    item.children = [item]
    document = FakeDoclingDocument(FakeBody([item]))

    blocks = docling_layout_blocks(document)

    assert [block.text for block in blocks] == ["Diabetes inpatient guideline"]


def test_docling_pdf_imports_pin_local_rapidocr_options(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _install_fake_docling_modules(monkeypatch)
    monkeypatch.setenv("AIRGAP_RUNTIME_OFFLINE", "0")
    monkeypatch.setenv("DOCLING_ARTIFACTS_PATH", str(tmp_path))
    monkeypatch.setenv("DOCLING_OCR_BACKEND", "onnxruntime")
    monkeypatch.setenv("DOCLING_OCR_LANGS", "en,chinese")

    converter, stream_type = _docling_imports(allow_ocr=True, input_format="pdf")

    pipeline_options = converter.format_options["pdf"].pipeline_options
    assert stream_type is FakeDocumentStream
    assert pipeline_options.do_ocr is True
    assert pipeline_options.artifacts_path == tmp_path
    assert pipeline_options.ocr_options.kwargs == {
        "backend": "onnxruntime",
        "lang": ["english", "chinese"],
    }


def test_docling_pdf_imports_require_artifacts_path_in_offline_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_docling_modules(monkeypatch)
    monkeypatch.setenv("AIRGAP_RUNTIME_OFFLINE", "1")
    monkeypatch.delenv("DOCLING_ARTIFACTS_PATH", raising=False)

    with pytest.raises(RuntimeError, match="DOCLING_ARTIFACTS_PATH"):
        _docling_imports(allow_ocr=True, input_format="pdf")


def test_parse_docling_pdf_reports_page_group_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_docling_modules(monkeypatch)
    monkeypatch.setenv("AIRGAP_RUNTIME_OFFLINE", "0")
    events: list[dict[str, object]] = []

    parse_docling_pdf(
        b"%PDF-1.7",
        pages={2, 3, 7},
        allow_page_repair=False,
        page_batch_size=2,
        progress_callback=events.append,
        progress_phase="layout",
    )

    assert events == [
        {
            "phase": "layout",
            "status": "running",
            "pages": (2, 3),
            "current": 0,
            "total": 3,
            "group_index": 1,
            "group_count": 2,
            "allow_page_repair": False,
            "mark_ocr": False,
        },
        {
            "phase": "layout",
            "status": "complete",
            "pages": (2, 3),
            "current": 2,
            "total": 3,
            "group_index": 1,
            "group_count": 2,
            "allow_page_repair": False,
            "mark_ocr": False,
        },
        {
            "phase": "layout",
            "status": "running",
            "pages": (7,),
            "current": 2,
            "total": 3,
            "group_index": 2,
            "group_count": 2,
            "allow_page_repair": False,
            "mark_ocr": False,
        },
        {
            "phase": "layout",
            "status": "complete",
            "pages": (7,),
            "current": 3,
            "total": 3,
            "group_index": 2,
            "group_count": 2,
            "allow_page_repair": False,
            "mark_ocr": False,
        },
    ]


def test_docling_convert_timeout_uses_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCLING_CONVERT_TIMEOUT_SECONDS", "12.5")

    assert _docling_convert_timeout_seconds() == 12.5


@pytest.mark.parametrize("value", ["-1", "nan", "not-a-number"])
def test_docling_convert_timeout_rejects_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("DOCLING_CONVERT_TIMEOUT_SECONDS", value)

    with pytest.raises(ValueError, match="DOCLING_CONVERT_TIMEOUT_SECONDS"):
        _docling_convert_timeout_seconds()


class FakeDocumentStream:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs


class FakeInputFormat:
    PDF = "pdf"
    DOCX = "docx"


class FakePdfPipelineOptions:
    def __init__(self, *, do_ocr: bool, artifacts_path) -> None:
        self.do_ocr = do_ocr
        self.artifacts_path = artifacts_path
        self.ocr_options = None


class FakeRapidOcrOptions:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


class FakePdfFormatOption:
    def __init__(self, *, pipeline_options: FakePdfPipelineOptions) -> None:
        self.pipeline_options = pipeline_options


class FakeDocumentConverter:
    def __init__(self, *, format_options) -> None:
        self.format_options = format_options

    def convert(self, stream, **kwargs):
        return FakeConversionResult(FakeDoclingDocument(FakeBody([FakeTextItem()])))


class FakeConversionResult:
    def __init__(self, document: FakeDoclingDocument) -> None:
        self.document = document


def _install_fake_docling_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    base_models = types.ModuleType("docling.datamodel.base_models")
    base_models.DocumentStream = FakeDocumentStream
    base_models.InputFormat = FakeInputFormat

    pipeline_options = types.ModuleType("docling.datamodel.pipeline_options")
    pipeline_options.PdfPipelineOptions = FakePdfPipelineOptions
    pipeline_options.RapidOcrOptions = FakeRapidOcrOptions

    document_converter = types.ModuleType("docling.document_converter")
    document_converter.DocumentConverter = FakeDocumentConverter
    document_converter.PdfFormatOption = FakePdfFormatOption

    monkeypatch.setitem(sys.modules, "docling", types.ModuleType("docling"))
    monkeypatch.setitem(sys.modules, "docling.datamodel", types.ModuleType("docling.datamodel"))
    monkeypatch.setitem(sys.modules, "docling.datamodel.base_models", base_models)
    monkeypatch.setitem(sys.modules, "docling.datamodel.pipeline_options", pipeline_options)
    monkeypatch.setitem(sys.modules, "docling.document_converter", document_converter)
