"""Verify factual blocks in every artifact representation against original evidence."""

from collections.abc import Callable
from hashlib import sha256
import json

from rag.shared.contracts.evidence import PARTIAL_NOTICE, CitationClaim, SourceAnchor
from rag.artifact_jobs.contracts import ArtifactContentBundle, EvidenceManifest
from .contracts import ArtifactJsonGenerator

_STRUCTURAL_NOTICES = {
    PARTIAL_NOTICE,
    "Grounded answer",
    "Grounded RAG response",
    "Rendered from the previously displayed grounded answer.",
}


def verify_bundle_citations(
    bundle: ArtifactContentBundle,
    evidence: EvidenceManifest,
    *,
    inference: ArtifactJsonGenerator,
    model: str,
    deadline: float,
    check_cancelled: Callable[[], None],
    max_calls: int = 8,
    context_tokens: int = 16384,
    output_tokens: int = 4096,
) -> tuple[ArtifactContentBundle, list[str], int]:
    sources = [
        SourceAnchor(
            doc_id=r.doc_id,
            chunk_id=r.chunk_id,
            doc_title=r.doc_title,
            excerpt=r.text,
            group_path="/artifact",
            provenance_kind=r.provenance_kind,
            quote_texts=r.quote_texts,
            index_generation_id=r.index_generation_id,
            content_hash=r.content_hash,
        )
        for r in evidence.records
    ]
    labels = {
        r.evidence_id: (
            f"[{r.chunk_id}]"
            if r.chunk_id.startswith(f"{r.doc_id}:")
            else f"[{r.doc_id}:{r.chunk_id}]"
        )
        for r in evidence.records
    }
    claims = bundle_claims(bundle, labels)
    serialized = json.dumps(
        [c.model_dump() for c in claims], sort_keys=True, ensure_ascii=False
    )
    partial = any(
        text.strip() == PARTIAL_NOTICE for text, _ids in _bundle_units(bundle)
    )
    checked, calls = inference.validate_evidence(
        claims,
        sources,
        question=bundle.content.purpose,
        answer=serialized + (f"\n{PARTIAL_NOTICE}" if partial else ""),
        model=model,
        deadline=deadline,
        check_cancelled=check_cancelled,
        max_calls=max_calls,
        context_tokens=context_tokens,
        output_tokens=output_tokens,
    )
    errors = [
        f"{c.claim_id}: {c.reason or c.verdict}"
        for c in checked
        if c.verdict != "supported"
    ]
    if not checked or len(checked) != len(claims):
        errors.append("artifact_claim_coverage_incomplete")
    if errors:
        return bundle.model_copy(update={"citation_verification": None}), errors, calls
    by_evidence = {
        key: list(
            dict.fromkeys(
                q.text for c in checked for q in c.quotes if q.source_label == label
            )
        )
        for key, label in labels.items()
    }
    records = {r.evidence_id: r for r in evidence.records}
    citations = [
        c.model_copy(
            update={
                "quotes": by_evidence.get(c.evidence_id, []),
                "index_generation_id": records[c.evidence_id].index_generation_id,
                "content_hash": records[c.evidence_id].content_hash,
            }
        )
        for c in bundle.content.citations
    ]
    return (
        bundle.model_copy(
            update={
                "content": bundle.content.model_copy(update={"citations": citations}),
                "paginated": bundle.paginated.model_copy(
                    update={"include_references": True}
                ),
                "presentation": bundle.presentation.model_copy(
                    update={"include_references_slide": True}
                ),
                "citation_verification": {
                    "version": 1,
                    "status": "verified",
                    "content_sha256": sha256(serialized.encode()).hexdigest(),
                    "coverage": "partial" if partial else "complete",
                    "claims": [c.model_dump() for c in checked],
                },
            }
        ),
        [],
        calls,
    )


def bundle_claims(
    bundle: ArtifactContentBundle, labels: dict[str, str]
) -> list[CitationClaim]:
    # Exact server notices contain no document facts; all other headings and warnings are checked.
    unique = list(
        dict.fromkeys(
            (text, tuple(ids))
            for text, ids in _bundle_units(bundle)
            if text.strip() and text.strip() not in _STRUCTURAL_NOTICES
        )
    )
    return [
        CitationClaim(
            claim_id=f"artifact-claim-{i + 1}",
            text=text,
            answer_start=0,
            answer_end=len(text),
            source_labels=[labels.get(key, f"[unknown:{key}]") for key in ids],
        )
        for i, (text, ids) in enumerate(unique)
    ]


def _bundle_units(bundle: ArtifactContentBundle) -> list[tuple[str, list[str]]]:
    units: list[tuple[str, list[str]]] = []
    groups = [
        *bundle.content.sections,
        *bundle.paginated.sections,
        *bundle.presentation.slides,
    ]
    for group in groups:
        blocks = group.blocks
        ids = list(dict.fromkeys(key for block in blocks for key in _block_ids(block)))
        units.append((group.title, ids))
        for block in blocks:
            if block.text and block.kind not in {"page_break", "section_break"}:
                units.append((block.text, block.evidence_ids))
            units.extend((item.text, item.evidence_ids) for item in block.list_items)
            units.extend((item, block.evidence_ids) for item in block.items)
            units.extend(
                (f"{item.key}: {item.value}", item.evidence_ids)
                for item in block.entries
            )
            if block.table is not None:
                units.extend(
                    (
                        json.dumps(
                            dict(zip(block.table.headers, row.values, strict=True)),
                            ensure_ascii=False,
                        ),
                        row.evidence_ids,
                    )
                    for row in block.table.rows
                )
    all_ids = list(dict.fromkeys(key for _text, ids in units for key in ids))
    units.extend((warning, all_ids) for warning in bundle.content.warnings)
    for spec in (bundle.content, bundle.paginated, bundle.presentation):
        units.append((spec.title, all_ids))
        if getattr(spec, "subtitle", None):
            units.append((spec.subtitle, all_ids))
    return units


def _block_ids(block):
    return [
        *block.evidence_ids,
        *(key for item in block.list_items for key in item.evidence_ids),
        *(key for item in block.entries for key in item.evidence_ids),
        *(
            key
            for row in (block.table.rows if block.table else [])
            for key in row.evidence_ids
        ),
    ]
