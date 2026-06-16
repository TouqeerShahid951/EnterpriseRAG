"""Shared helpers for structured field/value payloads."""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def collapse_whitespace(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def expand_label_abbreviations(text: str) -> str:
    return text


def normalized_phrase(text: object) -> str:
    expanded = expand_label_abbreviations(collapse_whitespace(text))
    return " ".join(_TOKEN_RE.findall(expanded.lower()))


def normalized_tokens(text: object) -> set[str]:
    return {token for token in _TOKEN_RE.findall(expand_label_abbreviations(collapse_whitespace(text)).lower()) if token}


def normalized_match_tokens(text: object) -> set[str]:
    tokens = normalized_tokens(text)
    singulars = {
        token[:-1]
        for token in tokens
        if len(token) > 3 and token.endswith("s")
    }
    return tokens | singulars


def normalized_field_label(label: object) -> str:
    return normalized_phrase(label)


def normalized_field_value(value: object) -> str:
    return collapse_whitespace(value).lower()


def canonical_structured_search_text(fields: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for field in fields:
        label = collapse_whitespace(field.get("label"))
        value = collapse_whitespace(field.get("value"))
        if label and value:
            lines.append(f"{label} = {value}")
        elif label:
            lines.append(label)
        elif value:
            lines.append(value)
    return "\n".join(lines)


def normalized_field_names(fields: list[dict[str, str]]) -> list[str]:
    return [name for name in (normalized_field_label(field.get("label")) for field in fields) if name]


def normalized_field_values(fields: list[dict[str, str]]) -> list[str]:
    return [value for value in (normalized_field_value(field.get("value")) for field in fields) if value]
