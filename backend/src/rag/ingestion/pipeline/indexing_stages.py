"""Chunking, embedding, and generation-safe indexing stages."""

import hashlib
import json
import logging
import math
import re
from hashlib import sha256
from collections import Counter

from rag.shared.contracts.abbreviations import (
    ABBREVIATION_GLOSSARY_DOC_TYPE,
    abbreviation_entry_candidates,
    abbreviation_entry_failure_reason,
    abbreviation_entries,
    normalize_abbreviation_entry,
)

from ..chunking import chunk_items
from ..indexing.claims import build_claim_records
from ..indexing.metadata_text import build_embedding_texts
from ..indexing.payloads import build_qdrant_points
from ..publication.models import aggregate_generation_hash, generation_id_for_job
from .progress import (
    bounded_progress,
    items_progress,
    raise_if_job_cancelled,
    should_report_progress,
)
from .state import IngestDependencies, IngestState
from .resume import checkpoint_review_fingerprint, logical_ranges, text_chunk_to_dict
from .fingerprints import configuration_digest
from rag.shared.contracts.sparse import SparseVector


logger = logging.getLogger(__name__)


_GLOSSARY_TABLE_HEADER_RE = re.compile(
    r"^\s*(?:abbreviations?|acronyms?|short forms?|short words?|codes?)\s+"
    r"(?:expansions?|full forms?|full expressions?|meanings?|definitions?)\s*$",
    re.IGNORECASE,
)
_GLOSSARY_TABLE_ROW_RE = re.compile(
    r"^\s*([A-Z][A-Z0-9./&-]{1,19})\s+(.{2,240}?)\s*$"
)
_GLOSSARY_TABLE_ROW_CASE_INSENSITIVE_RE = re.compile(
    _GLOSSARY_TABLE_ROW_RE.pattern,
    re.IGNORECASE,
)


def mark_processing(state: IngestState, deps: IngestDependencies) -> IngestState:
    deps.backend.update_job(
        job_id=state["payload"].job_id, status="processing", progress_pct=5
    )
    return state


def download_file(state: IngestState, deps: IngestDependencies) -> IngestState:
    state["file_bytes"] = deps.storage.read(state["payload"].file_path)
    deps.backend.update_job(
        job_id=state["payload"].job_id, status="processing", progress_pct=20
    )
    return state


def chunk_text(state: IngestState, deps: IngestDependencies) -> IngestState:
    state["chunks"] = chunk_items(
        state["parsed_items"],
        doc_id=state["payload"].doc_id,
        target_tokens=deps.chunk_target_tokens,
        overlap_tokens=deps.chunk_overlap_tokens,
        parent_max_tokens=deps.parent_max_tokens,
    )
    if not state["chunks"]:
        raise RuntimeError("document extraction produced no chunks")
    if state["payload"].doc_type == ABBREVIATION_GLOSSARY_DOC_TYPE:
        rejected_entries: list[dict[str, object]] = []
        state["abbreviation_entries"] = _abbreviation_entries_with_pages(
            state["chunks"], rejected_entries=rejected_entries
        )
        if rejected_entries or not state["abbreviation_entries"]:
            _log_abbreviation_glossary_diagnostics(
                state["payload"], state["chunks"], rejected_entries=rejected_entries
            )
        if not state["abbreviation_entries"]:
            raise RuntimeError("abbreviation glossary contains no recognized entries")
        state["claims"] = []
    else:
        state["claims"] = build_claim_records(
            job=state["payload"],
            chunks=state["chunks"],
            metadata=state["metadata"],
        )
    state["embedding_texts"] = (
        build_embedding_texts(
            file_path=state["payload"].file_path,
            chunks=state["chunks"],
            metadata=state["metadata"],
        )
        if state["payload"].doc_type != ABBREVIATION_GLOSSARY_DOC_TYPE
        else []
    )
    _save_prepared_checkpoint(state, deps)
    deps.backend.update_job(
        job_id=state["payload"].job_id,
        status="processing",
        progress_pct=60,
        stage_progress=items_progress(
            "chunks",
            len(state["chunks"]),
            len(state["chunks"]),
            "Built retrieval chunks",
        ),
    )
    return state


def embed_chunks(state: IngestState, deps: IngestDependencies) -> IngestState:
    chunks = state["chunks"]
    embedding_texts = state.get("embedding_texts") or build_embedding_texts(
        file_path=state["payload"].file_path,
        chunks=chunks,
        metadata=state["metadata"],
    )

    def report(index: int, total: int) -> None:
        raise_if_job_cancelled(deps, state["payload"].job_id)
        if should_report_progress(index, len(chunks)):
            deps.backend.update_job(
                job_id=state["payload"].job_id,
                status="processing",
                progress_pct=bounded_progress(65, 74, index, len(chunks)),
                stage_progress=items_progress(
                    "chunks",
                    index,
                    len(chunks),
                    f"Embedding chunk {index} of {len(chunks)}",
                ),
            )

    if getattr(deps, "checkpoint", None) is None:
        state["vectors"] = deps.ollama.embed_many(embedding_texts, progress=report)
        state["sparse_vectors"] = deps.sparse_embedder.embed_many(embedding_texts)
    else:
        state["vectors"] = _resume_dense_vectors(state, deps, embedding_texts, report)
        deps.backend.update_job(
            job_id=state["payload"].job_id,
            status="processing",
            progress_pct=75,
            stage_progress=items_progress(
                "vectors", len(chunks), len(chunks), "Generating sparse vectors"
            ),
        )
        state["sparse_vectors"] = _resume_sparse_vectors(state, deps, embedding_texts)
    deps.backend.update_job(
        job_id=state["payload"].job_id,
        status="processing",
        progress_pct=75,
        stage_progress=items_progress(
            "vectors", len(chunks), len(chunks), "Generating sparse vectors"
        ),
    )
    generation_id = generation_id_for_job(state["payload"].job_id)
    state["index_generation_id"] = generation_id
    state["points"] = build_qdrant_points(
        job=state["payload"],
        chunks=state["chunks"],
        vectors=state["vectors"],
        sparse_vectors=state["sparse_vectors"],
        metadata=state["metadata"],
        file_bytes=state["file_bytes"],
        claims=state["claims"],
        index_generation_id=generation_id,
    )
    item_hashes = [
        str(point["payload"]["generation_item_hash"])
        for point in state["points"]
        if isinstance(point.get("payload"), dict)
    ]
    deps.backend.stage_index_generation(
        job_id=state["payload"].job_id,
        generation_id=generation_id,
        input_hash=hashlib.sha256(state["file_bytes"]).hexdigest(),
        configuration_digest=_configuration_digest(deps),
        expected_point_count=len(state["points"]),
        expected_item_hash=aggregate_generation_hash(item_hashes),
        vector_dimension=len(state["vectors"][0]),
        metadata=state["metadata"],
        claims=state["claims"],
        supersedes=state["payload"].supersedes,
        warnings=state.get("warnings", []),
    )
    deps.backend.update_job(
        job_id=state["payload"].job_id,
        status="processing",
        progress_pct=78,
        stage_progress=items_progress(
            "vectors",
            len(state["points"]),
            len(state["points"]),
            "Prepared vectors for indexing",
        ),
    )
    return state


def upsert_qdrant(state: IngestState, deps: IngestDependencies) -> IngestState:
    job_id = state["payload"].job_id
    deps.qdrant.ensure_collection(len(state["vectors"][0]))
    raise_if_job_cancelled(deps, job_id)
    deps.backend.update_job(
        job_id=job_id,
        status="processing",
        progress_pct=82,
        stage_progress=items_progress(
            "vectors", 0, len(state["points"]), "Writing vectors to Qdrant"
        ),
    )
    generation_id = state["index_generation_id"]
    state["upsert_count"] = deps.qdrant.stage_generation(
        generation_id=generation_id,
        points=state["points"],
        guard=lambda: raise_if_job_cancelled(deps, job_id),
    )
    deps.qdrant.verify_generation(
        generation_id=generation_id,
        expected_point_count=state["upsert_count"],
        expected_item_hash=aggregate_generation_hash(
            str(point["payload"]["generation_item_hash"])
            for point in state["points"]
            if isinstance(point.get("payload"), dict)
        ),
        vector_dimension=len(state["vectors"][0]),
    )
    deps.backend.verify_index_generation(job_id=job_id, generation_id=generation_id)
    deps.qdrant.publish_generation(
        generation_id,
        guard=lambda: raise_if_job_cancelled(deps, job_id),
    )
    deps.backend.update_job(
        job_id=job_id,
        status="processing",
        progress_pct=92,
        stage_progress=items_progress(
            "vectors",
            state["upsert_count"],
            len(state["points"]),
            "Indexed vectors",
        ),
    )
    return state


def activate_generation(state: IngestState, deps: IngestDependencies) -> IngestState:
    deps.backend.activate_index_generation(
        job_id=state["payload"].job_id,
        generation_id=state["index_generation_id"],
    )
    return state


def _save_prepared_checkpoint(state: IngestState, deps: IngestDependencies) -> None:
    checkpoint = getattr(deps, "checkpoint", None)
    if checkpoint is None:
        return
    payload = {
        "chunks": [text_chunk_to_dict(chunk) for chunk in state["chunks"]],
        "claims": state.get("claims", []),
        "metadata": state.get("metadata", {}),
        "embedding_texts": state.get("embedding_texts", []),
        "parser_provenance": state.get("parser_provenance", {}),
        "warnings": state.get("warnings", []),
        "abbreviation_entries": state.get("abbreviation_entries", []),
        "review_fingerprint": checkpoint_review_fingerprint(state),
        "embedding_ranges": logical_ranges(len(state.get("embedding_texts", [])), getattr(deps, "embedding_batch_size", 16)),
    }
    descriptor = checkpoint.commit(
        job_id=state["payload"].job_id,
        document_id=state["payload"].doc_id,
        stage_key="prepared",
        payload=payload,
        upstream_sha256=sha256(state["file_bytes"]).hexdigest(),
        configuration_digest=_configuration_digest(deps),
    )
    state["prepared_sha256"] = descriptor.body_sha256
    state["embedding_ranges"] = payload["embedding_ranges"]
    logger.info(
        "ingestion checkpoint saved job_id=%s stage=prepared chunks=%d",
        state["payload"].job_id,
        len(state["chunks"]),
    )


def _resume_dense_vectors(state, deps, embedding_texts, report):
    total = len(embedding_texts)
    ranges = [tuple(pair) for pair in state.get("embedding_ranges", logical_ranges(total, getattr(deps, "embedding_batch_size", 16)))]
    values: dict[tuple[int, int], list[list[float]]] = {}
    checkpoint = deps.checkpoint
    for start, end in ranges:
        if hasattr(deps, "backend"):
            raise_if_job_cancelled(deps, state["payload"].job_id)
        loaded = checkpoint.load(
            job_id=state["payload"].job_id,
            stage_key=f"dense:{start}:{end}",
            upstream_sha256=_range_hash([state.get("prepared_sha256"), embedding_texts[start:end]]),
            configuration_digest=_configuration_digest(deps, "dense"),
            model_identity=getattr(deps.ollama, "embed_model", None),
        )
        if loaded is None:
            continue
        descriptor, payload = loaded
        vectors = payload.get("vectors")
        if _valid_dense_batch(vectors, end - start, getattr(descriptor, "vector_dimension", None)):
            values[(start, end)] = vectors
            if hasattr(deps, "backend"):
                _report_checkpoint_progress(state, deps, sum(b - a for a, b in values), total, "Resuming embeddings")
            else:
                report(sum(b - a for a, b in values), total)
        else:
            checkpoint.invalidate(descriptor)
    for start, end in ranges:
        if hasattr(deps, "backend"):
            raise_if_job_cancelled(deps, state["payload"].job_id)
        if (start, end) in values:
            continue
        batch = embedding_texts[start:end]
        vectors = deps.ollama.embed_many(
            batch,
            progress=lambda index, _batch_total: report(start + index, total),
        )
        if not _valid_dense_batch(vectors, end - start):
            raise RuntimeError("dense embedding provider returned an invalid vector batch")
        checkpoint.commit(
            job_id=state["payload"].job_id,
            document_id=state["payload"].doc_id,
            stage_key=f"dense:{start}:{end}",
            payload={"vectors": vectors, "input_hash": _range_hash(batch)},
            upstream_sha256=_range_hash([state.get("prepared_sha256"), batch]),
            configuration_digest=_configuration_digest(deps, "dense"),
            range_start=start,
            range_end=end,
            model_identity=getattr(deps.ollama, "embed_model", None),
            vector_dimension=len(vectors[0]),
        )
        values[(start, end)] = vectors
        _report_checkpoint_progress(state, deps, sum(b - a for a, b in values), total, "Saved embeddings")
    logger.info(
        "ingestion dense embeddings ready job_id=%s saved_ranges=%d total_chunks=%d",
        state["payload"].job_id,
        len(values),
        total,
    )
    return [vector for work_range in ranges for vector in values[work_range]]


def _resume_sparse_vectors(state, deps, embedding_texts):
    total = len(embedding_texts)
    ranges = [tuple(pair) for pair in state.get("embedding_ranges", logical_ranges(total, getattr(deps, "embedding_batch_size", 16)))]
    values: dict[tuple[int, int], list[SparseVector]] = {}
    checkpoint = deps.checkpoint
    for start, end in ranges:
        if hasattr(deps, "backend"):
            raise_if_job_cancelled(deps, state["payload"].job_id)
        loaded = checkpoint.load(
            job_id=state["payload"].job_id,
            stage_key=f"sparse:{start}:{end}",
            upstream_sha256=_range_hash([state.get("prepared_sha256"), embedding_texts[start:end]]),
            configuration_digest=_configuration_digest(deps, "sparse"),
            model_identity=getattr(deps.sparse_embedder, "model_name", None),
        )
        if loaded is None:
            continue
        descriptor, payload = loaded
        sparse = _sparse_batch_from_payload(payload.get("vectors"), end - start)
        if sparse is not None:
            values[(start, end)] = sparse
            _report_checkpoint_progress(state, deps, sum(b - a for a, b in values), total, "Restored sparse embeddings")
        else:
            checkpoint.invalidate(descriptor)
    for start, end in ranges:
        if hasattr(deps, "backend"):
            raise_if_job_cancelled(deps, state["payload"].job_id)
        if (start, end) in values:
            continue
        batch = deps.sparse_embedder.embed_many(embedding_texts[start:end])
        if len(batch) != end - start:
            raise RuntimeError("sparse embedding provider returned an invalid vector batch")
        serialised = [{"indices": item.indices, "values": item.values} for item in batch]
        if _sparse_batch_from_payload(serialised, end - start) is None:
            raise RuntimeError("sparse embedding provider returned invalid indices or weights")
        checkpoint.commit(
            job_id=state["payload"].job_id,
            document_id=state["payload"].doc_id,
            stage_key=f"sparse:{start}:{end}",
            payload={"vectors": serialised, "input_hash": _range_hash(embedding_texts[start:end])},
            upstream_sha256=_range_hash([state.get("prepared_sha256"), embedding_texts[start:end]]),
            configuration_digest=_configuration_digest(deps, "sparse"),
            range_start=start,
            range_end=end,
            model_identity=getattr(deps.sparse_embedder, "model_name", None),
        )
        values[(start, end)] = batch
        _report_checkpoint_progress(state, deps, sum(b - a for a, b in values), total, "Saved sparse embeddings")
    logger.info(
        "ingestion sparse embeddings ready job_id=%s saved_ranges=%d total_chunks=%d",
        state["payload"].job_id,
        len(values),
        total,
    )
    return [vector for work_range in ranges for vector in values[work_range]]


def _range_hash(values: object) -> str:
    return sha256(json.dumps(values, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _valid_dense_batch(vectors: object, expected: int, expected_dimension: int | None = None) -> bool:
    if not isinstance(vectors, list) or len(vectors) != expected or not vectors:
        return expected == 0
    dimension = None
    for vector in vectors:
        if not isinstance(vector, list) or not vector:
            return False
        if dimension is None:
            dimension = len(vector)
        if len(vector) != dimension or any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in vector):
            return False
    return expected_dimension is None or dimension == expected_dimension


def _sparse_batch_from_payload(value: object, expected: int) -> list[SparseVector] | None:
    if not isinstance(value, list) or len(value) != expected:
        return None
    result: list[SparseVector] = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("indices"), list) or not isinstance(item.get("values"), list):
            return None
        if len(item["indices"]) != len(item["values"]):
            return None
        indices, weights = item["indices"], item["values"]
        if any(type(index) is not int or index < 0 or index > 2**32 - 1 for index in indices):
            return None
        if len(set(indices)) != len(indices):
            return None
        if any(type(weight) not in {int, float} or not math.isfinite(weight) for weight in weights):
            return None
        result.append(SparseVector(indices=list(indices), values=[float(weight) for weight in weights]))
    return result


def _report_checkpoint_progress(state, deps, current: int, total: int, label: str) -> None:
    backend = getattr(deps, "backend", None)
    if backend is None or not hasattr(backend, "update_job"):
        return
    backend.update_job(
        job_id=state["payload"].job_id,
        status="processing",
        progress_pct=bounded_progress(65, 74, current, total),
        stage_progress=items_progress("chunks", current, total, f"{label}: {current} of {total} chunks saved"),
    )


def stage_abbreviation_glossary(
    state: IngestState, deps: IngestDependencies
) -> IngestState:
    generation_id = generation_id_for_job(state["payload"].job_id)
    state["index_generation_id"] = generation_id
    deps.backend.stage_index_generation(
        job_id=state["payload"].job_id,
        generation_id=generation_id,
        input_hash=hashlib.sha256(state["file_bytes"]).hexdigest(),
        configuration_digest=_configuration_digest(deps),
        expected_point_count=0,
        expected_item_hash=aggregate_generation_hash([]),
        vector_dimension=0,
        metadata=state["metadata"],
        claims=[],
        supersedes=state["payload"].supersedes,
        warnings=state.get("warnings", []),
        abbreviation_entries=state["abbreviation_entries"],
    )
    deps.backend.verify_index_generation(
        job_id=state["payload"].job_id,
        generation_id=generation_id,
    )
    deps.backend.update_job(
        job_id=state["payload"].job_id,
        status="processing",
        progress_pct=92,
        stage_progress=items_progress(
            "metadata",
            len(state["abbreviation_entries"]),
            len(state["abbreviation_entries"]),
            "Prepared abbreviation glossary",
        ),
    )
    return state


def _abbreviation_entries_with_pages(
    chunks: list[object], *, rejected_entries: list[dict[str, object]] | None = None
) -> list[dict[str, object]]:
    entries: dict[tuple[str, str], dict[str, object]] = {}
    for chunk in chunks:
        text = str(getattr(chunk, "text", ""))
        fields = getattr(chunk, "structured_fields", [])
        chunk_type = str(getattr(chunk, "chunk_type", ""))
        page = getattr(chunk, "page_start", None) or getattr(chunk, "page", None)
        lines = text.splitlines()
        pairs = abbreviation_entry_candidates(text, fields)
        pairs.extend(_headerless_table_field_pairs(fields, chunk_type=chunk_type))
        table_pairs = _markdown_table_pairs(lines) if chunk_type == "table" else []
        pairs.extend(table_pairs)
        if (
            chunk_type != "table_row"
            and not table_pairs
            and not text.lstrip().startswith("Table ")
        ):
            for line in lines:
                if _GLOSSARY_TABLE_HEADER_RE.fullmatch(line):
                    continue
                match = _GLOSSARY_TABLE_ROW_RE.fullmatch(line)
                if match is None and chunk_type == "table":
                    match = _GLOSSARY_TABLE_ROW_CASE_INSENSITIVE_RE.fullmatch(line)
                if match and match[2][0] not in "—–-:=":
                    pairs.append((match[1], match[2]))
        for raw_abbreviation, raw_expansion in dict.fromkeys(pairs):
            reason = abbreviation_entry_failure_reason(raw_abbreviation, raw_expansion)
            if reason is not None:
                if rejected_entries is not None:
                    _record_abbreviation_entry_rejection(
                        rejected_entries,
                        abbreviation=raw_abbreviation,
                        source_page=page,
                        reason=reason,
                    )
                continue
            abbreviation, expansion = normalize_abbreviation_entry(raw_abbreviation, raw_expansion)
            key = (abbreviation.casefold(), expansion.casefold())
            entries.setdefault(
                key,
                {
                    "abbreviation": abbreviation,
                    "expansion": expansion,
                    "source_page": page if isinstance(page, int) and page > 0 else None,
                },
            )
    return list(entries.values())


def _log_abbreviation_glossary_diagnostics(
    payload: object,
    chunks: list[object],
    *,
    rejected_entries: list[dict[str, object]] | None = None,
) -> None:
    chunk_types = Counter(
        str(getattr(chunk, "chunk_type", "") or "unknown") for chunk in chunks
    )
    header_lines = 0
    lowercase_only_rows = 0
    structured_field_chunks = 0
    for chunk in chunks:
        fields = getattr(chunk, "structured_fields", [])
        structured_field_chunks += int(bool(fields))
        for line in str(getattr(chunk, "text", "")).splitlines():
            if _GLOSSARY_TABLE_HEADER_RE.fullmatch(line):
                header_lines += 1
            insensitive = _GLOSSARY_TABLE_ROW_CASE_INSENSITIVE_RE.fullmatch(line)
            if insensitive and not _GLOSSARY_TABLE_ROW_RE.fullmatch(line):
                lowercase_only_rows += 1
    logger.warning(
        "Abbreviation glossary extraction yielded no recognized entries "
        "(job_id=%s doc_id=%s chunks=%d types=%s table_headers=%d "
        "structured_field_chunks=%d lowercase_only_rows=%d rejected_entries=%s)",
        getattr(payload, "job_id", "unknown"),
        getattr(payload, "doc_id", "unknown"),
        len(chunks),
        dict(sorted(chunk_types.items())),
        header_lines,
        structured_field_chunks,
        lowercase_only_rows,
        rejected_entries or [],
    )


def _record_abbreviation_entry_rejection(
    rejected_entries: list[dict[str, object]],
    *,
    abbreviation: str,
    source_page: object,
    reason: str,
) -> None:
    term = " ".join(abbreviation.split())[:20]
    if not term or len(rejected_entries) >= 20:
        return
    rejection = {
        "term": term,
        "page": source_page if isinstance(source_page, int) and source_page > 0 else None,
        "reason": reason,
    }
    if rejection not in rejected_entries:
        rejected_entries.append(rejection)


def _markdown_table_pairs(lines: list[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for line in lines:
        stripped = line.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            continue
        cells = [" ".join(cell.split()) for cell in stripped.strip("|").split("|")]
        if len(cells) != 2 or _GLOSSARY_TABLE_HEADER_RE.fullmatch(" ".join(cells)):
            continue
        match = _GLOSSARY_TABLE_ROW_CASE_INSENSITIVE_RE.fullmatch(" ".join(cells))
        if match and match[2][0] not in "—–-:=":
            pairs.append((match[1], match[2]))
    return pairs


def _headerless_table_field_pairs(
    fields: object, *, chunk_type: str
) -> list[tuple[str, str]]:
    if (
        chunk_type != "table_row"
        or not isinstance(fields, list)
        or len(fields) != 2
        or abbreviation_entries("", fields)
    ):
        return []
    items = [item for item in fields if isinstance(item, dict)]
    if len(items) != 2:
        return []
    candidates = [
        (str(items[0].get("label") or ""), str(items[1].get("label") or "")),
        (str(items[0].get("value") or ""), str(items[1].get("value") or "")),
    ]
    pairs: list[tuple[str, str]] = []
    for abbreviation, expansion in candidates:
        if " " not in expansion:
            expansion = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", expansion)
        match = _GLOSSARY_TABLE_ROW_CASE_INSENSITIVE_RE.fullmatch(
            f"{abbreviation} {expansion}"
        )
        if match and match[2][0] not in "—–-:=":
            pairs.append((match[1], match[2]))
    return pairs


def _configuration_digest(deps: IngestDependencies, stage: str = "prepared") -> str:
    return configuration_digest(deps, stage)
