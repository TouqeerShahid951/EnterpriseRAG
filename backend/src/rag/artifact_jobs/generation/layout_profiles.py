"""Adaptive visual profiles for generated artifacts."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re

from rag.artifact_jobs.contracts import ArtifactContentBundle


_PPTX_TITLE_BACKGROUND = (23, 59, 63)
_PPTX_CONTENT_BACKGROUNDS = (
    (220, 235, 232),
    (246, 231, 203),
    (226, 232, 245),
    (241, 224, 220),
    (229, 235, 213),
)


@dataclass(frozen=True)
class ArtifactLayoutProfile:
    key: str
    label: str
    kicker: str
    brand_hex: str
    accent_hex: str
    text_hex: str
    muted_hex: str
    rule_hex: str
    row_hex: str
    callout_hex: str
    pptx_title_background: tuple[int, int, int]
    pptx_backgrounds: tuple[tuple[int, int, int], ...]


_EVIDENCE_PROFILE = ArtifactLayoutProfile(
    key="evidence_brief",
    label="Evidence brief",
    kicker="EVIDENCE BRIEF",
    brand_hex="173B3F",
    accent_hex="C8A24A",
    text_hex="253538",
    muted_hex="53676A",
    rule_hex="D7E1E2",
    row_hex="F6FAFA",
    callout_hex="F8F1E3",
    pptx_title_background=_PPTX_TITLE_BACKGROUND,
    pptx_backgrounds=_PPTX_CONTENT_BACKGROUNDS,
)
_MATRIX_PROFILE = ArtifactLayoutProfile(
    key="matrix_report",
    label="Matrix report",
    kicker="MATRIX REPORT",
    brand_hex="173B3F",
    accent_hex="C8A24A",
    text_hex="253538",
    muted_hex="53676A",
    rule_hex="D7E1E2",
    row_hex="F6FAFA",
    callout_hex="F8F1E3",
    pptx_title_background=_PPTX_TITLE_BACKGROUND,
    pptx_backgrounds=_PPTX_CONTENT_BACKGROUNDS,
)
_TIMELINE_PROFILE = ArtifactLayoutProfile(
    key="timeline_report",
    label="Timeline report",
    kicker="TIMELINE REPORT",
    brand_hex="1F3A5F",
    accent_hex="C8A24A",
    text_hex="253538",
    muted_hex="596A73",
    rule_hex="D8E0E5",
    row_hex="F7FAFC",
    callout_hex="F8F1E3",
    pptx_title_background=(31, 58, 95),
    pptx_backgrounds=((232, 238, 245), (246, 231, 203), (220, 235, 232), (241, 224, 220)),
)
_OPERATOR_PROFILE = ArtifactLayoutProfile(
    key="operator_guide",
    label="Operator guide",
    kicker="REFERENCE GUIDE",
    brand_hex="243B53",
    accent_hex="4F8A8B",
    text_hex="253538",
    muted_hex="53676A",
    rule_hex="D7E1E2",
    row_hex="F6FAFA",
    callout_hex="EDF7F6",
    pptx_title_background=(36, 59, 83),
    pptx_backgrounds=((237, 247, 246), (232, 238, 245), (246, 231, 203), (242, 244, 247)),
)
_PROPOSAL_PROFILE = ArtifactLayoutProfile(
    key="proposal",
    label="Proposal",
    kicker="PROPOSAL",
    brand_hex="203748",
    accent_hex="B08A3C",
    text_hex="253538",
    muted_hex="5D6970",
    rule_hex="DDD8CC",
    row_hex="FAF8F2",
    callout_hex="FFF7E5",
    pptx_title_background=(32, 55, 72),
    pptx_backgrounds=((250, 248, 242), (232, 238, 245), (220, 235, 232), (246, 231, 203)),
)
_STANDARD_PROFILE = ArtifactLayoutProfile(
    key="standard_report",
    label="Evidence-backed report",
    kicker="REPORT",
    brand_hex="173B3F",
    accent_hex="C8A24A",
    text_hex="253538",
    muted_hex="53676A",
    rule_hex="D7E1E2",
    row_hex="F6FAFA",
    callout_hex="F8F1E3",
    pptx_title_background=_PPTX_TITLE_BACKGROUND,
    pptx_backgrounds=_PPTX_CONTENT_BACKGROUNDS,
)


def select_layout_profile(bundle: ArtifactContentBundle) -> ArtifactLayoutProfile:
    """Choose a visual profile from document intent and generated structure."""

    terms = _bundle_layout_terms(bundle)
    block_counts = Counter(
        block.kind
        for section in bundle.content.sections
        for block in section.blocks
    )
    table_count = block_counts["table"] + block_counts["key_value"]
    if _has_any_term(terms, "timeline", "chronology", "chronological", "sequence", "event log"):
        return _TIMELINE_PROFILE
    if _has_any_term(terms, "sop", "procedure", "workflow", "runbook", "checklist", "steps", "playbook"):
        return _OPERATOR_PROFILE
    if _has_any_term(terms, "proposal", "grant", "rfp", "rfi", "business case", "funding", "bid"):
        return _PROPOSAL_PROFILE
    if _has_any_term(terms, "matrix", "comparison", "compare", "compliance", "scorecard") or table_count >= 2:
        return _MATRIX_PROFILE
    if _has_any_term(terms, "fir", "crime", "evidence", "case", "risk", "citation", "source"):
        return _EVIDENCE_PROFILE
    return _STANDARD_PROFILE


def _bundle_layout_terms(bundle: ArtifactContentBundle) -> str:
    parts = [bundle.content.title, bundle.content.purpose, bundle.paginated.title, bundle.presentation.title]
    if bundle.paginated.subtitle:
        parts.append(bundle.paginated.subtitle)
    if bundle.presentation.subtitle:
        parts.append(bundle.presentation.subtitle)
    for section in bundle.content.sections:
        parts.append(section.title)
        for block in section.blocks:
            if block.text:
                parts.append(block.text[:240])
            if block.table is not None:
                parts.extend(block.table.headers)
            parts.extend(entry.key for entry in block.entries)
    return " ".join(parts).lower()


def _has_any_term(text: str, *terms: str) -> bool:
    for term in terms:
        normalized = " ".join(term.lower().split())
        if not normalized:
            continue
        pattern = r"(?<![A-Za-z0-9])" + r"[\s/_-]+".join(
            re.escape(part) for part in normalized.split()
        ) + r"(?![A-Za-z0-9])"
        if re.search(pattern, text):
            return True
    return False
