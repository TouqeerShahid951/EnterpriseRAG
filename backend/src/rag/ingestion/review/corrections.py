"""Apply an approved transcription without promoting generated descriptions to OCR."""

from typing import Any

from ..parsers.images.analysis import image_item_description, image_item_text
from ..parsers.models import parsed_item_from_dict


def apply_review_correction(
    parsed: dict[str, Any], corrected_text: str
) -> dict[str, Any]:
    result = dict(parsed)
    raw_flags = parsed.get("quality_flags")
    flags = [str(flag) for flag in raw_flags] if isinstance(raw_flags, list) else []
    if "ocr_image_consolidated" in flags:
        description = image_item_description(parsed_item_from_dict(parsed))
        if description is None:
            raise ValueError(
                "Consolidated OCR review is missing its original transcription"
            )
        result["text"] = image_item_text(corrected_text, description)
        result["quote_texts"] = [corrected_text]
    else:
        result["text"] = corrected_text
    result["quality_flags"] = sorted({*flags, "ocr_review_approved"})
    return result
