from rag.ingestion.chunking import chunk_items
from rag.ingestion.parsers.models import ParsedPdfItem


def test_pptx_chunks_never_cross_slides_and_keep_visual_meaning_separate() -> None:
    chunks = chunk_items(
        [
            _item(0, "Slide one title\nFirst bullet", 1, "text", "source:pptx_structured"),
            _item(1, "Image description:\nApproval flows from intake to review.", 1, "image_text", "source:pptx_slide"),
            _item(2, "Slide two title\nSecond bullet", 2, "text", "source:pptx_structured"),
        ],
        doc_id="deck-1",
        target_tokens=128,
        overlap_tokens=16,
        parent_max_tokens=512,
    )

    assert [(chunk.page_start, chunk.page_end) for chunk in chunks] == [(1, 1), (1, 1), (2, 2)]
    assert chunks[0].parent_chunk_id == chunks[1].parent_chunk_id
    assert chunks[1].parent_chunk_id != chunks[2].parent_chunk_id
    assert "Approval flows" not in chunks[0].text
    assert "Approval flows" in chunks[1].text


def test_simple_pptx_slide_remains_one_chunk() -> None:
    chunks = chunk_items(
        [_item(0, "Title\nOne concise bullet\nAnother concise bullet", 1, "text", "source:pptx_structured")],
        doc_id="deck-1",
        target_tokens=128,
        overlap_tokens=16,
        parent_max_tokens=512,
    )

    assert len(chunks) == 1


def _item(index: int, text: str, slide: int, item_type: str, flag: str) -> ParsedPdfItem:
    return ParsedPdfItem(
        index=index,
        text=text,
        item_type=item_type,
        page_start=slide,
        page_end=slide,
        section_title=f"Slide {slide}",
        section_path=[f"Slide {slide}"],
        parser="docling" if item_type == "text" else "pptx_slide",
        quality_flags=[flag],
    )
