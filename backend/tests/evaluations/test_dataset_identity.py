import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import Any

from rag.evaluations.schemas import EvaluationCase


def _ingest_module() -> ModuleType:
    path = Path(__file__).parents[3] / "evals/rag_test_documents_v1/ingest.py"
    spec = importlib.util.spec_from_file_location("rag_test_documents_ingest", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_module() -> ModuleType:
    path = Path(__file__).parents[3] / "evals/rag_test_documents_v1/build_dataset.py"
    spec = importlib.util.spec_from_file_location("rag_test_documents_build", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _release_module() -> ModuleType:
    path = Path(__file__).parents[3] / "evals/rag_test_documents_v1/run_release_gate.py"
    spec = importlib.util.spec_from_file_location("rag_test_documents_release", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get("ingest")
    sys.modules["ingest"] = _ingest_module()
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop("ingest", None)
        else:
            sys.modules["ingest"] = previous
    return module


class _Response:
    ok = True
    status_code = 200

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def json(self) -> dict[str, Any]:
        return self.payload

    def raise_for_status(self) -> None:
        return None


class _Session:
    def __init__(
        self, items: list[dict[str, Any]], details: dict[str, dict[str, Any]]
    ) -> None:
        self.items = items
        self.details = details
        self.posts: list[dict[str, Any]] = []

    def get(self, url: str, **_: Any) -> _Response:
        if url.endswith("/datasets"):
            return _Response({"items": self.items})
        return _Response(self.details[url.rsplit("/", 1)[-1]])

    def post(self, _url: str, *, json: dict[str, Any], **_: Any) -> _Response:
        self.posts.append(json)
        return _Response(
            {
                "id": "new-dataset",
                "name": json["name"],
                "case_count": len(json["content"].splitlines()),
            }
        )


def test_dataset_semantic_hash_uses_the_complete_case_contract() -> None:
    ingest = _ingest_module()
    minimal = {"id": "case-1", "question": "What is supported?"}
    normalized = EvaluationCase.model_validate(minimal).model_dump(mode="json")
    normalized["metadata"] = {"source_shape": "jsonl"}

    assert ingest.dataset_semantic_hash([minimal]) == ingest.dataset_semantic_hash(
        [normalized]
    )

    for change in (
        {"min_faithfulness_score": 0.8},
        {"evidence_expectations": [{"document_id": "doc-1", "pages": [2]}]},
        {"metadata": {"owner": "qa"}},
    ):
        assert ingest.dataset_semantic_hash([{**minimal, **change}]) != (
            ingest.dataset_semantic_hash([minimal])
        )

    expectation = {"document_id": "doc-1", "pages": [2]}
    assert ingest.dataset_semantic_hash(
        [{**minimal, "evidence_expectations": [expectation]}]
    ) != ingest.dataset_semantic_hash(
        [
            {
                **minimal,
                "evidence_expectations": [
                    {**expectation, "anchors": ["needle"], "min_anchor_recall": 0.5}
                ],
            }
        ]
    )


def test_dataset_import_reuses_exact_content_and_versions_a_name_collision() -> None:
    ingest = _ingest_module()
    case = {"id": "case-1", "question": "What is supported?"}
    content = json.dumps(case) + "\n"
    remote_case = EvaluationCase.model_validate(case).model_dump(mode="json")
    remote_case["metadata"] = {"source_shape": "jsonl"}
    name = "RAG test documents v1"

    exact_session = _Session(
        [{"id": "exact", "name": name}],
        {"exact": {"cases": [remote_case]}},
    )
    exact = ingest.import_dataset(
        exact_session, base_url="http://rag", csrf="csrf", content=content
    )
    assert exact["action"] == "existing"
    assert exact_session.posts == []

    collision_session = _Session(
        [{"id": "old", "name": name}],
        {"old": {"cases": [{"id": "case-1", "question": "Old meaning"}]}},
    )
    imported = ingest.import_dataset(
        collision_session, base_url="http://rag", csrf="csrf", content=content
    )
    expected_name = f"{name} [{ingest.dataset_semantic_hash([case])[:12]}]"
    assert imported["action"] == "imported"
    assert collision_session.posts[0]["name"] == expected_name

    version_session = _Session(
        [
            {"id": "old", "name": name},
            {"id": "version", "name": expected_name},
        ],
        {
            "old": {"cases": [{"id": "case-1", "question": "Old meaning"}]},
            "version": {"cases": [remote_case]},
        },
    )
    existing_version = ingest.import_dataset(
        version_session, base_url="http://rag", csrf="csrf", content=content
    )
    assert existing_version["dataset_id"] == "version"
    assert version_session.posts == []


def test_samsung_expectations_and_ranking_gold_share_page_spans() -> None:
    build = _build_module()
    case = build.samsung_cases()[0]
    build.attach_document_bound_expectations([case])
    ranking = build.ranking_case(case)

    expectations = case["evidence_expectations"]
    spans = ranking["required_evidence_spans"]
    assert [expectation["pages"] for expectation in expectations] == [[51], [52], [53]]
    assert [expectation["anchors"] for expectation in expectations] == [
        span["must_contain"] for span in spans
    ]
    assert sum(len(expectation["anchors"]) for expectation in expectations) == 14
    assert all(expectation["min_anchor_recall"] == 1.0 for expectation in expectations)


def test_release_runner_preserves_server_runtime_pins() -> None:
    release = _release_module()
    merged = release._merged_run_pins(
        {
            "rag_config_snapshot": {
                "_runtime_pins": {
                    "image_digest": "sha256:image",
                    "host_profile": "host-a",
                    "dataset_semantic_hash": "untrusted-server-value",
                }
            }
        },
        {"dataset_semantic_hash": "local-dataset"},
    )

    assert merged == {
        "image_digest": "sha256:image",
        "host_profile": "host-a",
        "dataset_semantic_hash": "local-dataset",
    }
