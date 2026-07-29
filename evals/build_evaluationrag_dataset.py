#!/usr/bin/env python3
"""Normalize the local EvaluationRAG benchmark while excluding Apollo and Artemis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from rag.evaluations.datasets import normalize_dataset_content


DEFAULT_INPUT = Path("/Users/tabbasi/Downloads/rag_evaluation_dataset.jsonl")
DEFAULT_OUTPUT = Path("tmp/evaluationrag_32/dataset.jsonl")
SKIPPED_CASE_IDS = {
    "AP11-001",
    "AP11-002",
    "AP11-003",
    "AP11-004",
    "ART-001",
    "ART-002",
    "X-001",
}


def _load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Input line {line_number} is invalid JSON: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"Input line {line_number} must be a JSON object.")
        rows.append(row)
    return rows


def _page_list(value: object) -> list[int]:
    if isinstance(value, bool):
        return []
    if isinstance(value, int) and value > 0:
        return [value]
    if isinstance(value, str) and value.strip().isdigit():
        page = int(value.strip())
        return [page] if page > 0 else []
    return []


def _normalize_case(row: dict[str, Any]) -> dict[str, Any]:
    case_id = str(row.get("id") or "").strip()
    question = str(row.get("question") or "").strip()
    expected_answer = str(row.get("expected_answer") or "").strip()
    source_document = str(row.get("source_document") or "").strip()
    if not case_id or not question or not expected_answer or not source_document:
        raise ValueError(
            f"Case {case_id or '<missing id>'} must define question, "
            "expected_answer, and source_document."
        )

    corpus_negative = source_document == "All uploaded documents"
    unanswerable = str(row.get("answerable") or "").strip().lower() == "no"
    expected_source_docs = [] if corpus_negative else [source_document]
    case = {
        "id": case_id,
        "question": question,
        "question_type": row.get("question_type"),
        "difficulty": row.get("difficulty"),
        "expected_answer": expected_answer,
        "expected_source_docs": expected_source_docs,
        "acceptable_source_pages": (
            [] if corpus_negative else _page_list(row.get("source_page"))
        ),
        "min_sources": 0 if corpus_negative else 1,
        "must_cite_source": not corpus_negative,
        "min_faithfulness_score": 0.0 if corpus_negative else 0.8,
        "allow_degraded": unanswerable,
        "metadata": {
            key: row[key]
            for key in (
                "source_document",
                "source_page",
                "modality",
                "acceptable_variants",
                "evidence",
                "answerable",
                "retrieval_scope",
                "evaluation_notes",
            )
            if key in row
        },
    }
    return {key: value for key, value in case.items() if value is not None}


def build_dataset(input_path: Path) -> str:
    rows = _load_rows(input_path)
    if len(rows) != 39:
        raise ValueError(f"Expected 39 input cases, found {len(rows)}.")
    ids = [str(row.get("id") or "").strip() for row in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("Input case IDs must be unique.")
    missing_skips = sorted(SKIPPED_CASE_IDS.difference(ids))
    if missing_skips:
        raise ValueError(f"Expected skipped cases are missing: {', '.join(missing_skips)}")

    cases = [
        _normalize_case(row)
        for row in rows
        if str(row.get("id") or "").strip() not in SKIPPED_CASE_IDS
    ]
    content = "".join(
        json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n" for case in cases
    )
    normalized = normalize_dataset_content(
        content,
        name="EvaluationRAG 32 (Apollo and Artemis excluded)",
        source_format="jsonl",
    )
    if len(normalized.cases) != 32:
        raise ValueError(f"Expected 32 output cases, found {len(normalized.cases)}.")
    if any(
        "Apollo" in document or "artemis" in document.lower()
        for case in normalized.cases
        for document in case.expected_source_docs
    ):
        raise ValueError("Apollo or Artemis source expectations leaked into output.")
    return content


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    content = build_dataset(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content, encoding="utf-8")
    print(
        json.dumps(
            {
                "input": str(args.input),
                "output": str(args.output),
                "case_count": len(content.splitlines()),
                "skipped_case_ids": sorted(SKIPPED_CASE_IDS),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
