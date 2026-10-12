"""Regressions for source preservation across parsing and chunking."""

import json
from dataclasses import replace
from types import SimpleNamespace as NS

import pytest

from rag.ingestion.chunking import chunk_items
from rag.ingestion.chunking.citation_targets import citation_targets
from rag.ingestion.errors import WorkerStepError
from rag.ingestion.parsers.docling.adapter import structured_docling_items
from rag.ingestion.parsers.hierarchy import apply_hierarchy
from rag.ingestion.parsers.json import parse_json_document
from rag.ingestion.parsers.models import ParsedPdfItem, parsed_item_from_dict, parsed_item_to_dict
from rag.ingestion.parsers.pdf import layered
from rag.ingestion.parsers.pdf.parser import parse_pdf_document
from rag.ingestion.parsers.pdf.pymupdf import PymuPDFParseResult
from rag.ingestion.parsers.quality import WeakPage


def _item(index, text, kind="text", page=1, **kwargs):
    return ParsedPdfItem(index, text, kind, page, page, bbox=(0, 0, 500, 500), **kwargs)


def test_rejected_whole_page_repair_preserves_original_text():
    native = _item(0, "Important native clause. " * 200)
    repair = _item(0, "Incomplete repair. " * 8, parser="docling")
    baseline = PymuPDFParseResult([native], 1, {1: len(native.text)}, {1: ["rotated_page"]})
    fused = layered._fuse_pages(baseline, [native], [repair],
        weak_pages=[WeakPage(1, 5, ["rotated_page"])], min_chars_per_page=80)
    assert fused[0].text == native.text
    complete = replace(repair, text=native.text)
    accepted = layered._fuse_pages(baseline, [native], [complete],
        weak_pages=[WeakPage(1, 5, ["rotated_page"])], min_chars_per_page=80)
    assert accepted[0].parser == "docling"


@pytest.mark.parametrize("blank", [False, True])
def test_missing_page_fails_but_confirmed_blank_page_is_allowed(monkeypatch, blank):
    native = _item(0, "Readable original text. " * 100)
    baseline = PymuPDFParseResult([native], 2, {1: len(native.text), 2: 0},
        {1: [], 2: ["confirmed_blank_page" if blank else "image_only_page"]})
    monkeypatch.setattr(layered, "parse_pymupdf_pdf_with_metadata", lambda *a, **k: baseline)
    def unavailable(*a, **k):
        raise ImportError("unavailable")
    monkeypatch.setattr(layered, "parse_docling_pdf", unavailable)
    if blank:
        result = parse_pdf_document(b"fake", min_chars_per_page=80)
        assert result.provenance["content_complete"] is True
        assert result.provenance["page_statuses"][1]["status"] == "confirmed_blank"
    else:
        with pytest.raises(WorkerStepError) as error:
            parse_pdf_document(b"fake", min_chars_per_page=80)
        assert error.value.code == "pdf_incomplete"


@pytest.mark.parametrize("value,expected", [
    ({"warnings": ["Do not mix with bleach", {"code": "W1"}, 42]}, ["Do not mix with bleach", "W1", "42"]),
    ({"headers": ["Item", "Value"], "rows": [["A", 10]], "currency": "USD", "notes": {"exclusion": "Tax excluded"}}, ["USD", "Tax excluded", "10"]),
    ({f"field_{i}": f"uniquevalue{i}" for i in range(95)}, ["uniquevalue94"]),
    ([f"arrayvalue{i}" for i in range(215)], ["arrayvalue214", "[214]"]),
])
def test_json_keeps_values_through_chunking(value, expected):
    items = parse_json_document(json.dumps(value).encode()).items
    chunks = chunk_items(items, doc_id="test", target_tokens=128, overlap_tokens=0, parent_max_tokens=512)
    text = "\n".join(chunk.text for chunk in chunks)
    for value in expected:
        assert value in text
    assert "omitted" not in text


def test_numbered_hierarchy_and_table_captions_do_not_create_false_sections():
    result = apply_hierarchy([
        _item(0, "2. Methods", "heading"),
        _item(1, "2.1 Procedure", "heading"),
        _item(2, "Table 2: Results", "heading"),
        _item(3, "| A |\n|---|\n| 5 |", "table"),
        _item(4, "Following paragraph"),
    ])
    assert result[-1].section_path == ["2. Methods", "2.1 Procedure"]
    assert result[2].item_type == "caption"
    assert result[3].table_json["caption"] == "Table 2: Results"
    assert apply_hierarchy(result) == result


def test_multipage_source_locations_survive_serialization_and_chunking():
    bbox = NS(l=0, t=0, r=100, b=100, coord_origin="TOPLEFT")
    source = NS(text="First.Second.", label="text", self_ref="#/texts/0",
        prov=[NS(page_no=1, bbox=bbox, charspan=(0, 6)), NS(page_no=2, bbox=bbox, charspan=(6, 13))])
    item = structured_docling_items(NS(texts=[source], tables=[], pictures=[]))[0]
    assert (item.page_start, item.page_end) == (1, 2)
    restored = parsed_item_from_dict(parsed_item_to_dict(item))
    assert citation_targets([restored]) == citation_targets([item])
    targets = citation_targets([restored])
    assert [(x["page"], x["exact_text"]) for x in targets] == [(1, "First."), (2, "Second.")]
    chunks = chunk_items([restored], doc_id="test", target_tokens=128, overlap_tokens=0, parent_max_tokens=512)
    assert {target["page"] for chunk in chunks for target in chunk.citation_targets} == {1, 2}
    with pytest.raises(ValueError):
        parsed_item_from_dict({**parsed_item_to_dict(item), "source_spans": [{"page": -1}]})
