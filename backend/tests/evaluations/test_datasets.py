import json

import pytest

from rag.evaluations.datasets import EvaluationDatasetError, normalize_dataset_content


@pytest.mark.parametrize(
    ("source_format", "content", "expected_shape"),
    [
        (
            "json",
            json.dumps(
                [
                    {
                        "id": "case-1",
                        "question": "Why?",
                        "metadata": {"owner": "qa", "source_shape": "wrong"},
                        "unknown": "not metadata",
                    }
                ]
            ),
            "json",
        ),
        (
            "jsonl",
            json.dumps(
                {
                    "id": "case-1",
                    "question": "Why?",
                    "metadata": {"owner": "qa", "source_shape": "wrong"},
                }
            ),
            "jsonl",
        ),
    ],
)
def test_row_metadata_survives_with_actual_source_shape(
    source_format: str, content: str, expected_shape: str
) -> None:
    dataset = normalize_dataset_content(content, source_format=source_format)

    assert dataset.cases[0].metadata == {"owner": "qa", "source_shape": expected_shape}


@pytest.mark.parametrize("source_format", ["json", "auto"])
def test_explicit_non_object_case_metadata_is_rejected(source_format: str) -> None:
    content = json.dumps([{"id": "case-1", "question": "Why?", "metadata": None}])

    with pytest.raises(
        EvaluationDatasetError, match="metadata must be an object"
    ) as exc_info:
        normalize_dataset_content(content, source_format=source_format)

    assert exc_info.value.code == "evaluation_case_invalid_metadata"


def test_repo_fixture_generation_case_preserves_explicit_metadata() -> None:
    content = json.dumps(
        {
            "id": "fixture-1",
            "generation_cases": [
                {
                    "id": "case-1",
                    "question": "Why?",
                    "metadata": {"section": "claims", "source_shape": "wrong"},
                }
            ],
        }
    )

    dataset = normalize_dataset_content(content, source_format="json")

    assert dataset.cases[0].metadata == {
        "section": "claims",
        "source_shape": "repo_fixture",
    }


@pytest.mark.parametrize("source_shape", ["json", "jsonl", "repo_fixture"])
def test_explicit_document_bound_evidence_expectations_survive_import(source_shape: str) -> None:
    case = {
        "id": "case-1",
        "question": "Which documents support this?",
        "evidence_expectations": [
            {
                "document_id": "document-1",
                "pages": [2, 3, 2],
                "page_match": "all",
                "anchors": [" first anchor ", "second anchor", "first anchor"],
                "min_anchor_recall": 0.75,
            },
            {
                "content_hash": "sha256:document-2",
                "pages": [7, 9],
            },
        ],
    }
    if source_shape == "jsonl":
        content = json.dumps(case)
        source_format = "jsonl"
    elif source_shape == "repo_fixture":
        content = json.dumps({"id": "fixture-1", "generation_cases": [case]})
        source_format = "json"
    else:
        content = json.dumps([case])
        source_format = "json"

    dataset = normalize_dataset_content(content, source_format=source_format)

    assert [expectation.model_dump() for expectation in dataset.cases[0].evidence_expectations] == [
        {
            "document_id": "document-1",
            "content_hash": None,
            "pages": [2, 3],
            "page_match": "all",
            "anchors": ["first anchor", "second anchor"],
            "min_anchor_recall": 0.75,
        },
        {
            "document_id": None,
            "content_hash": "sha256:document-2",
            "pages": [7, 9],
            "page_match": "any",
            "anchors": [],
            "min_anchor_recall": 1.0,
        },
    ]


@pytest.mark.parametrize(
    "evidence_expectations",
    [
        [{}],
        "document-1",
        ["document-1"],
        [{"document_id": "document-1", "pages": [0]}],
        [{"document_id": "document-1", "anchors": ["  "]}],
        [{"document_id": "document-1", "min_anchor_recall": 0}],
        [{"document_id": "document-1", "min_anchor_recall": 1.01}],
    ],
)
@pytest.mark.parametrize("source_format", ["json", "auto"])
def test_invalid_evidence_expectations_use_stable_dataset_error(
    evidence_expectations: object,
    source_format: str,
) -> None:
    content = json.dumps(
        [
            {
                "id": "case-1",
                "question": "Why?",
                "evidence_expectations": evidence_expectations,
            }
        ]
    )

    with pytest.raises(EvaluationDatasetError) as exc_info:
        normalize_dataset_content(content, source_format=source_format)

    assert exc_info.value.code == "evaluation_case_invalid_evidence_expectations"
    assert exc_info.value.message == (
        "Case row 1 evidence_expectations must be a list of valid expectation objects."
    )


def test_legacy_source_expectations_still_import_unchanged() -> None:
    content = json.dumps(
        [
            {
                "id": "case-1",
                "question": "Where is it documented?",
                "expected_source_docs": ["Claims Manual"],
                "acceptable_source_pages": [4, 6],
            }
        ]
    )

    dataset = normalize_dataset_content(content, source_format="json")

    case = dataset.cases[0]
    assert case.expected_source_docs == ["Claims Manual"]
    assert case.acceptable_source_pages == [4, 6]
    assert case.evidence_expectations == []
