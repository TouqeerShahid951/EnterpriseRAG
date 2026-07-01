from types import SimpleNamespace

from rag_ingestion.parsers import pymupdf as pymupdf_parser


class FakePage:
    rotation = 0

    def __init__(self, blocks):
        self.blocks = blocks
        self.rect = SimpleNamespace(width=600, height=800)

    def get_text(self, kind):
        if kind == "dict":
            return {"blocks": self.blocks}
        if kind == "text":
            return "\n".join(_block_text(block) for block in self.blocks if block.get("type") == 0)
        raise AssertionError(kind)


def _text_block(text, bbox=(72, 72, 520, 120)):
    return {
        "type": 0,
        "bbox": bbox,
        "lines": [{"spans": [{"text": text, "size": 11, "font": "Helvetica"}]}],
    }


def _image_block(bbox=(0, 0, 600, 800)):
    return {"type": 1, "bbox": bbox}


def _block_text(block):
    return " ".join(
        str(span.get("text", "")).strip()
        for line in block.get("lines", [])
        for span in line.get("spans", [])
        if str(span.get("text", "")).strip()
    )


def _unexpected_call(name):
    def fail(*_args, **_kwargs):
        raise AssertionError(name)

    return fail


def test_plain_text_page_skips_table_and_layout(monkeypatch):
    page = FakePage(
        [
            _text_block(
                "This is a normal paragraph with enough words to be treated as simple native text. "
                "It has no images, columns, form fields, or obvious table cues."
            )
        ]
    )

    monkeypatch.setattr(pymupdf_parser, "table_entries", _unexpected_call("table"))
    monkeypatch.setattr(pymupdf_parser, "layout_page_entries", _unexpected_call("layout"))

    entries = pymupdf_parser._page_entries(page, 1)

    assert [entry.text for entry in entries] == [page.get_text("text")]


def test_page_sized_image_skips_native_table_and_layout(monkeypatch):
    page = FakePage(
        [
            _image_block(),
            _text_block(
                "OCR text from a scanned page can be used directly here while Docling handles stronger OCR repair."
            ),
        ]
    )

    monkeypatch.setattr(pymupdf_parser, "table_entries", _unexpected_call("table"))
    monkeypatch.setattr(pymupdf_parser, "layout_page_entries", _unexpected_call("layout"))

    entries = pymupdf_parser._page_entries(page, 1)

    assert [entry.text for entry in entries] == [page.get_text("text")]


def test_table_like_page_keeps_existing_table_layout_path(monkeypatch):
    page = FakePage(
        [
            _text_block("Part 1 123 available units", (72, 72, 140, 90)),
            _text_block("Part 2 456 available units", (160, 72, 230, 90)),
            _text_block("Part 3 789 available units", (250, 72, 320, 90)),
            _text_block("Part 4 101 available units", (340, 72, 410, 90)),
        ]
    )
    calls = {"tables": 0, "layout": 0}

    def fake_tables(_page, _page_no):
        calls["tables"] += 1
        return []

    def fake_layout(_page, _page_no, _tables):
        calls["layout"] += 1
        return []

    monkeypatch.setattr(pymupdf_parser, "table_entries", fake_tables)
    monkeypatch.setattr(pymupdf_parser, "layout_page_entries", fake_layout)

    pymupdf_parser._page_entries(page, 1)

    assert calls == {"tables": 1, "layout": 1}
