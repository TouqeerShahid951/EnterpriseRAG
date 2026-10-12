"""Preserve Excel values, formats, and cached formula results without evaluating formulas."""

from datetime import date, datetime, time
from decimal import Decimal
import re


def xlsx_rows(worksheet, cached_sheet, metadata: list[dict[str, object]]):
    for row, cached_row in zip(worksheet.iter_rows(), cached_sheet.iter_rows(), strict=True):
        rendered = []
        for cell, cached in zip(row, cached_row, strict=True):
            raw = cell.value
            formula = isinstance(raw, str) and raw.startswith("=")
            fmt = cell.number_format or "General"
            display = _display(cached.value if formula else raw, fmt)
            if formula:
                display = f"{raw} [cached result: {display if cached.value is not None else 'unavailable'}]"
            if raw is not None and (formula or fmt != "General"):
                metadata.append({
                    "cell": cell.coordinate, "raw_value": _text(raw), "number_format": fmt,
                    "display_value": display, "formula": raw if formula else None,
                    "cached_value": _text(cached.value) if formula and cached.value is not None else None,
                })
            rendered.append(display)
        yield rendered


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _display(value, number_format: str) -> str:
    if type(value) not in {int, float} or number_format == "General":
        return _text(value)
    number = Decimal(str(value))
    fmt = number_format.replace('"', '')
    if re.fullmatch(r"0+", fmt) and number == number.to_integral_value():
        return str(int(number)).zfill(len(fmt))
    if re.fullmatch(r"0(?:\.0+)?%", fmt):
        places = len(fmt.rstrip('%').partition('.')[2])
        return f"{number * 100:.{places}f}%"
    match = re.fullmatch(r"([$€£¥]?)([#,0]+)(?:\.(0+))?", fmt)
    if match:
        places = len(match.group(3) or '')
        grouping = ',' if ',' in match.group(2) else ''
        return f"{match.group(1)}{number:{grouping}.{places}f}"
    # ponytail: preserve unsupported Excel formats explicitly; do not approximate their display.
    return f"{value} [number format: {number_format}]"
