from __future__ import annotations

from io import BytesIO

import pytest


def scanned_page_pdf(*, include_visual: bool, visual_kind: str = "large") -> bytes:
    fitz = pytest.importorskip("fitz")
    Image = pytest.importorskip("PIL.Image")
    ImageDraw = pytest.importorskip("PIL.ImageDraw")

    image = Image.new("RGB", (1000, 1400), "white")
    draw = ImageDraw.Draw(image)
    for y in range(90, 330, 34):
        draw.rectangle((50, y, 520, y + 11), fill=(20, 20, 20))
    if include_visual:
        if visual_kind == "many":
            for left in (570, 770):
                for top in (430, 730, 1030):
                    draw.rectangle(
                        (left, top, left + 175, top + 250), fill=(45, 45, 45)
                    )
                    draw.rectangle(
                        (left + 25, top - 22, left + 105, top + 18), fill=(25, 25, 25)
                    )
        elif visual_kind == "small":
            draw.rectangle((700, 520, 805, 610), fill=(45, 45, 45))
            draw.rectangle((730, 495, 780, 525), fill=(25, 25, 25))
            draw.rectangle((775, 505, 850, 518), fill=(25, 25, 25))
            draw.ellipse((705, 590, 805, 635), fill=(20, 20, 20))
        else:
            draw.rectangle((585, 500, 900, 730), fill=(55, 55, 55))
            draw.rectangle((635, 455, 790, 510), fill=(35, 35, 35))
            draw.rectangle((770, 465, 940, 485), fill=(35, 35, 35))
            draw.ellipse((625, 690, 875, 790), fill=(25, 25, 25))
    image_bytes = BytesIO()
    image.save(image_bytes, format="PNG")
    document = fitz.open()
    page = document.new_page(width=500, height=700)
    page.insert_image(page.rect, stream=image_bytes.getvalue())
    pdf_bytes = document.tobytes()
    document.close()
    return pdf_bytes


def ocr_text_bbox() -> tuple[float, float, float, float]:
    return (15.0, 30.0, 280.0, 185.0)


def cue_text_bbox() -> tuple[float, float, float, float]:
    return (285.0, 320.0, 470.0, 365.0)
