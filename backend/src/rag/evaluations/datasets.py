"""Normalize supported RAG evaluation dataset formats."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import TypeAdapter, ValidationError

from rag.evaluations.schemas import EvaluationCase, EvaluationEvidenceExpectation


SourceFormat = Literal["json", "jsonl"]
_EVIDENCE_EXPECTATIONS_ADAPTER = TypeAdapter(list[EvaluationEvidenceExpectation])


@dataclass(frozen=True)
class NormalizedEvaluationDataset:
    name: str
    description: str | None
    source_format: SourceFormat
    cases: tuple[EvaluationCase, ...]
    metadata: dict[str, Any]


class EvaluationDatasetError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def normalize_dataset_content(
    content: str,
    *,
    name: str | None = None,
    source_format: str = "auto",
) -> NormalizedEvaluationDataset:
    cleaned = content.strip()
    if not cleaned:
        raise EvaluationDatasetError("evaluation_dataset_empty", "Evaluation dataset content is empty.")
    if source_format not in {"auto", "json", "jsonl"}:
        raise EvaluationDatasetError("evaluation_dataset_format", "Evaluation dataset format must be auto, json, or jsonl.")
    if source_format == "jsonl":
        return _normalize_jsonl(cleaned, name=name)
    if source_format == "json":
        return _normalize_json(cleaned, name=name)
    try:
        json.loads(cleaned)
    except json.JSONDecodeError:
        return _normalize_jsonl(cleaned, name=name)
    return _normalize_json(cleaned, name=name)


def _normalize_json(content: str, *, name: str | None) -> NormalizedEvaluationDataset:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise EvaluationDatasetError("evaluation_dataset_invalid_json", f"Dataset JSON is invalid: {exc}") from exc
    if isinstance(payload, list):
        cases = tuple(_case_from_row(row, index, source_shape="json") for index, row in enumerate(payload))
        return _dataset(
            name=name or "Imported JSON evaluation",
            description=None,
            source_format="json",
            cases=cases,
            metadata={},
        )
    if not isinstance(payload, dict):
        raise EvaluationDatasetError("evaluation_dataset_invalid_json", "Dataset JSON must be an object or list.")
    if isinstance(payload.get("generation_cases"), list):
        return _normalize_repo_fixture(payload, name=name)
    if "question" in payload or "query" in payload:
        return _dataset(
            name=name or "Imported JSON evaluation",
            description=None,
            source_format="json",
            cases=(_case_from_row(payload, 0, source_shape="json"),),
            metadata={},
        )
    raise EvaluationDatasetError(
        "evaluation_dataset_unknown_shape",
        "Dataset JSON must contain generation_cases or case rows with question/query.",
    )


def _normalize_jsonl(content: str, *, name: str | None) -> NormalizedEvaluationDataset:
    cases: list[EvaluationCase] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvaluationDatasetError("evaluation_dataset_invalid_jsonl", f"Line {line_number} is invalid JSON: {exc}") from exc
        cases.append(_case_from_row(row, line_number - 1, source_shape="jsonl"))
    if not cases:
        raise EvaluationDatasetError("evaluation_dataset_empty", "JSONL dataset did not contain any cases.")
    return _dataset(
        name=name or "Imported JSONL evaluation",
        description=None,
        source_format="jsonl",
        cases=tuple(cases),
        metadata={},
    )


def _normalize_repo_fixture(payload: dict[str, Any], *, name: str | None) -> NormalizedEvaluationDataset:
    response_checks = _dict(payload.get("response_checks"))
    document = _dict(payload.get("document"))
    dataset_name = name or str(payload.get("id") or document.get("title") or "Imported RAG evaluation")
    description = str(payload.get("description")) if payload.get("description") else None
    cases: list[EvaluationCase] = []
    for index, row in enumerate(payload.get("generation_cases") or []):
        if not isinstance(row, dict):
            raise EvaluationDatasetError("evaluation_case_invalid", f"generation_cases[{index}] must be an object.")
        expected_docs = _string_list(row.get("expected_source_docs"))
        if not expected_docs and document.get("title"):
            expected_docs = [str(document["title"])]
        cases.append(
            EvaluationCase(
                id=_case_id(row, index),
                question=_question(row, index),
                question_type=_optional_str(row.get("question_type")),
                difficulty=_optional_str(row.get("difficulty")),
                expected_answer=_optional_str(row.get("expected_answer")),
                must_include=_string_list(row.get("expected_terms")) or _string_list(row.get("acceptable_if_mentions")),
                must_not_include=_string_list(row.get("wrong_if_mentions")),
                expected_source_docs=expected_docs,
                acceptable_source_pages=_int_list(row.get("acceptable_source_pages")),
                evidence_expectations=_evidence_expectations(row, index),
                min_sources=_optional_int(row.get("min_sources")) or 0,
                must_cite_source=bool(response_checks.get("requires_citations", False)),
                min_faithfulness_score=float(response_checks.get("min_faithfulness_score") or 0.0),
                allow_degraded=bool(response_checks.get("allow_degraded", False)),
                latency_threshold_ms=_optional_int(row.get("latency_threshold_ms")),
                metadata=_case_metadata(row, index, source_shape="repo_fixture"),
            )
        )
    return _dataset(
        name=dataset_name,
        description=description,
        source_format="json",
        cases=tuple(cases),
        metadata={
            "source_id": payload.get("id"),
            "document": document,
            "ingestion_checks": _dict(payload.get("ingestion_checks")),
            "response_checks": response_checks,
        },
    )


def _case_from_row(row: object, index: int, *, source_shape: SourceFormat) -> EvaluationCase:
    if not isinstance(row, dict):
        raise EvaluationDatasetError("evaluation_case_invalid", f"Case row {index + 1} must be an object.")
    return EvaluationCase(
        id=_case_id(row, index),
        question=_question(row, index),
        question_type=_optional_str(row.get("question_type")),
        difficulty=_optional_str(row.get("difficulty")),
        expected_answer=_optional_str(row.get("expected_answer")),
        must_include=(
            _string_list(row.get("must_include"))
            or _string_list(row.get("acceptable_if_mentions"))
            or _string_list(row.get("expected_terms"))
        ),
        must_not_include=_string_list(row.get("must_not_include")) or _string_list(row.get("wrong_if_mentions")),
        expected_source_docs=_string_list(row.get("expected_source_docs")),
        acceptable_source_pages=_int_list(row.get("acceptable_source_pages")),
        evidence_expectations=_evidence_expectations(row, index),
        min_sources=_optional_int(row.get("min_sources")) or 0,
        must_cite_source=bool(row.get("must_cite_source") or row.get("requires_citations") or False),
        min_faithfulness_score=float(row.get("min_faithfulness_score") or 0.0),
        allow_degraded=bool(row.get("allow_degraded", False)),
        latency_threshold_ms=_optional_int(row.get("latency_threshold_ms")),
        metadata=_case_metadata(row, index, source_shape=source_shape),
    )


def _evidence_expectations(
    row: dict[str, Any], index: int
) -> list[EvaluationEvidenceExpectation]:
    if "evidence_expectations" not in row:
        return []
    try:
        return _EVIDENCE_EXPECTATIONS_ADAPTER.validate_python(row["evidence_expectations"])
    except ValidationError as exc:
        raise EvaluationDatasetError(
            "evaluation_case_invalid_evidence_expectations",
            f"Case row {index + 1} evidence_expectations must be a list of valid expectation objects.",
        ) from exc


def _case_metadata(row: dict[str, Any], index: int, *, source_shape: str) -> dict[str, Any]:
    if "metadata" not in row:
        return {"source_shape": source_shape}
    metadata = row["metadata"]
    if not isinstance(metadata, dict):
        raise EvaluationDatasetError(
            "evaluation_case_invalid_metadata",
            f"Case row {index + 1} metadata must be an object.",
        )
    return {**metadata, "source_shape": source_shape}


def _dataset(
    *,
    name: str,
    description: str | None,
    source_format: SourceFormat,
    cases: tuple[EvaluationCase, ...],
    metadata: dict[str, Any],
) -> NormalizedEvaluationDataset:
    if not cases:
        raise EvaluationDatasetError("evaluation_dataset_empty", "Evaluation dataset must contain at least one case.")
    ids = [case.id for case in cases]
    duplicates = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
    if duplicates:
        raise EvaluationDatasetError("evaluation_case_duplicate", f"Duplicate case ids: {', '.join(duplicates)}")
    return NormalizedEvaluationDataset(
        name=name.strip() or "Imported RAG evaluation",
        description=description,
        source_format=source_format,
        cases=cases,
        metadata=metadata,
    )


def _case_id(row: dict[str, Any], index: int) -> str:
    value = str(row.get("id") or row.get("case_id") or f"case_{index + 1}").strip()
    if not value:
        raise EvaluationDatasetError("evaluation_case_missing_id", f"Case row {index + 1} is missing id.")
    return value


def _question(row: dict[str, Any], index: int) -> str:
    value = str(row.get("question") or row.get("query") or "").strip()
    if not value:
        raise EvaluationDatasetError("evaluation_case_missing_question", f"Case row {index + 1} is missing question/query.")
    return value


def _dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _int_list(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    items: list[int] = []
    for item in value:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if number > 0:
            items.append(number)
    return items


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
