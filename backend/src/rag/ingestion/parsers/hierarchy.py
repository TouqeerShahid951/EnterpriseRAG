"""Canonical hierarchy inference for parsed PDF items."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import re

from .context import is_table_title
from .models import ParsedPdfItem

_ID_SAFE_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class SectionNode:
    title: str
    level: int


def apply_hierarchy(items: list[ParsedPdfItem]) -> list[ParsedPdfItem]:
    stack: list[SectionNode] = []
    enriched: list[ParsedPdfItem] = []
    for item in items:
        if item.item_type == "heading":
            node, flags = _heading_node(item, stack)
            stack = _replace_stack(stack, node)
            enriched.append(_with_hierarchy(_with_flags(item, flags), stack, node.level))
            continue
        path = [node.title for node in stack]
        section_level = stack[-1].level if stack else None
        enriched.append(_with_hierarchy(item, stack, section_level, inherited_path=path))
    return enriched


def _heading_node(item: ParsedPdfItem, stack: list[SectionNode]) -> tuple[SectionNode, set[str]]:
    text = item.text
    if item.section_level is not None and item.section_level > 0:
        return SectionNode(text, item.section_level), set()
    if is_table_title(text):
        level = (stack[-1].level + 1) if stack else 1
        return SectionNode(text, level), set()
    return SectionNode(text, 1), {"section_hierarchy_ambiguous"}


def _replace_stack(stack: list[SectionNode], node: SectionNode) -> list[SectionNode]:
    kept = [existing for existing in stack if existing.level < node.level]
    kept.append(node)
    return kept


def _with_hierarchy(
    item: ParsedPdfItem,
    stack: list[SectionNode],
    section_level: int | None,
    *,
    inherited_path: list[str] | None = None,
) -> ParsedPdfItem:
    path = inherited_path if inherited_path is not None else [node.title for node in stack]
    section_title = path[-1] if path else item.section_title
    return replace(
        item,
        section_title=section_title,
        section_path=path,
        section_level=section_level,
        parent_section_id=section_id(path),
    )


def _with_flags(item: ParsedPdfItem, flags: set[str]) -> ParsedPdfItem:
    if not flags:
        return item
    return replace(item, quality_flags=sorted({*item.quality_flags, *flags}))


def section_id(path: list[str]) -> str | None:
    if not path:
        return None
    normalized = " > ".join(" ".join(part.lower().split()) for part in path)
    slug = _ID_SAFE_RE.sub("-", path[-1].lower()).strip("-")[:48] or "section"
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]
    return f"{slug}:{digest}"
