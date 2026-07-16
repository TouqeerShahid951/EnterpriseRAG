"""Deterministic artifact composition when inference is unavailable."""

from __future__ import annotations

import re

from rag.artifact_jobs.contracts import (
    ContentBlock,
    ContentListItem,
    ContentSection,
    ContentTable,
    ContentTableRow,
    EvidenceRecord,
)


FALLBACK_MAX_LIST_ITEMS = 12
FALLBACK_MAX_TABLE_COLUMNS = 6


def _fallback_section(title: str, records: list[EvidenceRecord]) -> ContentSection:
    if _should_use_compact_record_table(records):
        return _fallback_compact_record_table(title, records)
    structured_records = [record for record in records if record.structured_fields]
    if structured_records:
        headers = _fallback_headers(structured_records)
        if len(headers) > FALLBACK_MAX_TABLE_COLUMNS:
            return _fallback_bullet_section(title, records)
        rows = [
            ContentTableRow(
                values=[record.structured_fields.get(header, "") for header in headers],
                evidence_ids=[record.evidence_id],
            )
            for record in structured_records
        ]
        return ContentSection(
            title=title,
            blocks=[
                ContentBlock(
                    kind="table", table=ContentTable(headers=headers, rows=rows)
                )
            ],
        )
    return _fallback_bullet_section(title, records)


def _fallback_bullet_section(
    title: str, records: list[EvidenceRecord]
) -> ContentSection:
    return ContentSection(
        title=title,
        blocks=[
            ContentBlock(
                kind="bullet_list",
                list_items=[
                    ContentListItem(
                        text=_fallback_item_text(record),
                        evidence_ids=[record.evidence_id],
                    )
                    for record in records[:FALLBACK_MAX_LIST_ITEMS]
                ],
            )
        ],
    )


def _should_use_compact_record_table(records: list[EvidenceRecord]) -> bool:
    structured_records = [record for record in records if record.structured_fields]
    if not structured_records:
        return False
    unique_docs = {record.doc_title for record in records}
    return (
        len(_fallback_headers(structured_records)) > FALLBACK_MAX_TABLE_COLUMNS
        or len(unique_docs) > 1
    )


def _fallback_compact_record_table(
    title: str, records: list[EvidenceRecord]
) -> ContentSection:
    grouped: dict[str, list[EvidenceRecord]] = {}
    for record in records:
        grouped.setdefault(record.doc_title, []).append(record)
    rows = [
        ContentTableRow(
            values=[
                doc_title,
                _topic_value(doc_title, doc_records),
                _key_detail_summary(doc_records),
                _evidence_or_status_summary(doc_records),
            ],
            evidence_ids=_record_ids(doc_records),
        )
        for doc_title, doc_records in sorted(grouped.items())
    ]
    if not rows:
        return _fallback_bullet_section(title, records)
    return ContentSection(
        title=title,
        blocks=[
            ContentBlock(
                kind="table",
                table=ContentTable(
                    headers=[
                        "Document",
                        _fallback_topic_header(records),
                        "Key details",
                        "Evidence / status",
                    ],
                    rows=rows,
                ),
            )
        ],
    )


def _fallback_topic_header(records: list[EvidenceRecord]) -> str:
    text = " ".join(record.query for record in records).lower()
    rules = (
        (("crime", "criminal", "offence", "offense"), "Crime / offense"),
        (("risk", "issue"), "Risk / issue"),
        (("requirement", "shall", "must"), "Requirement"),
        (("control", "compliance"), "Control / compliance"),
        (("standard", "specification"), "Standard / specification"),
        (("event", "timeline", "date"), "Event"),
        (("finding", "observation"), "Finding"),
    )
    for needles, label in rules:
        if any(needle in text for needle in needles):
            return label
    return "Topic"


def _topic_value(doc_title: str, records: list[EvidenceRecord]) -> str:
    field_value = _first_field_value(
        records,
        (
            "subject",
            "title",
            "category",
            "classification",
            "type",
            "topic",
            "offense",
            "offence",
            "crime",
            "risk",
            "requirement",
            "standard",
            "control",
            "finding",
            "issue",
        ),
    )
    if field_value:
        return _clip(field_value, 130)
    subject = _subject_from_title(doc_title)
    if subject.lower() not in {"document", "report", "fictitious", "untitled"}:
        return subject
    sentence = _first_matching_sentence(
        _records_text(records),
        ("registered", "section", "finding", "requirement", "risk", "status"),
    )
    return _clip(sentence or subject, 130)


def _key_detail_summary(records: list[EvidenceRecord]) -> str:
    text = _field_summary(
        records,
        (
            "summary",
            "description",
            "detail",
            "legal",
            "requirement",
            "scope",
            "objective",
            "finding",
            "issue",
            "risk",
            "standard",
            "control",
            "date",
            "status",
        ),
    )
    return _clip(text or _records_text(records), 260)


def _evidence_or_status_summary(records: list[EvidenceRecord]) -> str:
    text = _field_summary(
        records,
        (
            "evidence",
            "status",
            "action",
            "outcome",
            "result",
            "analysis",
            "finding",
            "note",
        ),
    )
    if not text:
        text = _first_matching_sentence(
            _records_text(records),
            ("evidence", "status", "action", "result", "analysis", "finding"),
        )
    return _clip(text or _records_text(records), 260)


def _first_field_value(records: list[EvidenceRecord], labels: tuple[str, ...]) -> str:
    for record in records:
        for key, value in record.structured_fields.items():
            if _is_useful_field(key) and any(label in key.lower() for label in labels):
                return value
    return ""


def _field_summary(
    records: list[EvidenceRecord],
    labels: tuple[str, ...],
    *,
    max_fields: int = 2,
) -> str:
    parts: list[str] = []
    for record in records:
        for key, value in record.structured_fields.items():
            if not _is_useful_field(key) or not any(
                label in key.lower() for label in labels
            ):
                continue
            parts.append(f"{key}: {value}")
            if len(parts) >= max_fields:
                return " ".join(parts)
    return " ".join(parts)


def _is_useful_field(label: str) -> bool:
    lowered = label.lower()
    low_value = ("contact", "phone", "address", "signature", "cnic", "imei")
    return not any(term in lowered for term in low_value)


def _subject_from_title(doc_title: str) -> str:
    stem = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", doc_title.rsplit("/", 1)[-1])
    words = [
        word for word in re.split(r"[^A-Za-z0-9]+", stem) if word and not word.isdigit()
    ]
    if len(words) > 1 and words[0].isupper() and len(words[0]) <= 6:
        words = words[1:]
    subject = " ".join(words[:5]) or "Document"
    return " ".join(
        word.upper() if word.isupper() else word.capitalize()
        for word in subject.split()
    )


def _records_text(records: list[EvidenceRecord]) -> str:
    parts: list[str] = []
    for record in records:
        parts.extend(record.structured_fields.values())
        parts.append(record.text)
    return " ".join(" ".join(part.split()) for part in parts if part)


def _first_matching_sentence(text: str, needles: tuple[str, ...]) -> str:
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        lowered = sentence.lower()
        if any(needle in lowered for needle in needles):
            return sentence.strip()
    return ""


def _record_ids(records: list[EvidenceRecord]) -> list[str]:
    return list(dict.fromkeys(record.evidence_id for record in records))[:8]


def _clip(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    return compact[: limit - 1].rstrip() + "..." if len(compact) > limit else compact


def _fallback_headers(records: list[EvidenceRecord]) -> list[str]:
    headers: list[str] = []
    for record in records:
        for key in record.structured_fields:
            if key not in headers:
                headers.append(key)
    return headers or ["Evidence"]


def _fallback_item_text(record: EvidenceRecord) -> str:
    text = " ".join((record.text or "").split())
    if not text and record.structured_fields:
        text = "; ".join(
            f"{key}: {value}" for key, value in record.structured_fields.items()
        )
    return text[:360] or f"Evidence item {record.evidence_id}"
