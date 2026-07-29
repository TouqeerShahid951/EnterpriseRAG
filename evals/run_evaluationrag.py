#!/usr/bin/env python3
"""Import and run the normalized EvaluationRAG benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from typing import Any

import requests

from ingest import api_error, dataset_semantic_hash, list_documents, login


DATASET_NAME = "EvaluationRAG 32 (Apollo and Artemis excluded)"
TERMINAL = {"complete", "partial", "failed", "cancelled"}
SMOKE_CASE_IDS = ["HW-001", "LET-003", "AMZ-001", "WB-003", "X-002"]


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _import_dataset(
    session: requests.Session,
    *,
    base_url: str,
    csrf: str,
    content: str,
) -> dict[str, Any]:
    local_cases = [
        json.loads(line) for line in content.splitlines() if line.strip()
    ]
    semantic_hash = dataset_semantic_hash(local_cases)
    response = session.get(
        f"{base_url}/api/v1/rag-evaluations/datasets", timeout=30
    )
    response.raise_for_status()
    matches = [
        item
        for item in response.json().get("items", [])
        if item.get("name") == DATASET_NAME
        or str(item.get("name") or "").startswith(f"{DATASET_NAME} [")
    ]
    for item in matches:
        detail = session.get(
            f"{base_url}/api/v1/rag-evaluations/datasets/{item['id']}",
            timeout=30,
        )
        detail.raise_for_status()
        if (
            dataset_semantic_hash(detail.json().get("cases") or [])
            == semantic_hash
        ):
            return {
                "action": "existing",
                "dataset_id": item["id"],
                "name": item["name"],
                "case_count": len(local_cases),
                "semantic_sha256": semantic_hash,
            }

    name = (
        f"{DATASET_NAME} [{semantic_hash[:12]}]" if matches else DATASET_NAME
    )
    response = session.post(
        f"{base_url}/api/v1/rag-evaluations/datasets",
        headers={"X-CSRF-Token": csrf},
        json={"name": name, "content": content, "source_format": "jsonl"},
        timeout=120,
    )
    if not response.ok:
        code, message = api_error(response)
        raise RuntimeError(
            f"Dataset import failed ({response.status_code}, {code}): {message}"
        )
    payload = response.json()
    return {
        "action": "imported",
        "dataset_id": payload["id"],
        "name": payload["name"],
        "case_count": payload["case_count"],
        "semantic_sha256": semantic_hash,
    }


def _verify_corpus(
    session: requests.Session,
    *,
    base_url: str,
    qdrant_url: str,
    group_path: str,
    content: str,
) -> list[dict[str, Any]]:
    expected_titles = sorted(
        {
            title
            for line in content.splitlines()
            if line.strip()
            for title in json.loads(line).get("expected_source_docs", [])
        }
    )
    documents = {
        document["title"]: document
        for document in list_documents(session, base_url, group_path)
        if document.get("is_current", True)
    }
    health: list[dict[str, Any]] = []
    for title in expected_titles:
        document = documents.get(title)
        if document is None:
            health.append({"title": title, "present": False, "ready": False})
            continue
        response = session.post(
            f"{qdrant_url}/collections/documents/points/count",
            json={
                "exact": True,
                "filter": {
                    "must": [
                        {
                            "key": "doc_id",
                            "match": {"value": document["id"]},
                        },
                        {
                            "key": "retrieval_status",
                            "match": {"value": "active"},
                        },
                    ]
                },
            },
            timeout=30,
        )
        response.raise_for_status()
        vector_count = int(response.json()["result"]["count"])
        ready = document.get("ingest_status") == "complete" and vector_count > 0
        health.append(
            {
                "title": title,
                "present": True,
                "ingest_status": document.get("ingest_status"),
                "vector_count": vector_count,
                "ready": ready,
            }
        )
    failures = [item["title"] for item in health if not item["ready"]]
    if failures:
        raise RuntimeError(f"Required corpus is not ready: {', '.join(failures)}")
    return health


def _run(
    session: requests.Session,
    *,
    base_url: str,
    csrf: str,
    dataset_id: str,
    group_path: str,
    case_ids: list[str],
    output_path: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    response = session.post(
        f"{base_url}/api/v1/rag-evaluations/runs",
        headers={"X-CSRF-Token": csrf},
        json={
            "dataset_id": dataset_id,
            "group_path": group_path,
            "case_ids": case_ids,
        },
        timeout=30,
    )
    if not response.ok:
        code, message = api_error(response)
        raise RuntimeError(
            f"Evaluation launch failed ({response.status_code}, {code}): {message}"
        )
    payload = response.json()
    run_id = payload["id"]
    expected_count = len(case_ids) if case_ids else 32
    if payload.get("case_count") != expected_count:
        raise RuntimeError(
            f"Expected {expected_count} cases, launched {payload.get('case_count')}."
        )
    return _poll_run(
        session,
        base_url=base_url,
        run_id=run_id,
        output_path=output_path,
        timeout_seconds=timeout_seconds,
    )


def _poll_run(
    session: requests.Session,
    *,
    base_url: str,
    run_id: str,
    output_path: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    previous: tuple[object, ...] | None = None
    while True:
        try:
            response = session.get(
                f"{base_url}/api/v1/rag-evaluations/runs/{run_id}",
                timeout=30,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Evaluation timed out while polling: {run_id}"
                ) from exc
            if exc.response is not None and exc.response.status_code == 401:
                login(session, base_url)
                print("[reauthenticated] status session renewed", flush=True)
                continue
            print(f"[retrying] status poll failed: {exc}", flush=True)
            time.sleep(5)
            continue
        payload = response.json()
        _write_json(output_path, payload)
        snapshot = (
            payload["status"],
            payload["stage"],
            payload["progress_pct"],
            payload["completed_count"],
            payload["passed_count"],
            payload["failed_count"],
        )
        if snapshot != previous:
            print(
                f"[{payload['status']:8}] {payload['progress_pct']:3}% "
                f"completed={payload['completed_count']} "
                f"passed={payload['passed_count']} failed={payload['failed_count']} "
                f"stage={payload['stage']} run={run_id}",
                flush=True,
            )
            previous = snapshot
        if payload["status"] in TERMINAL:
            if payload["status"] != "complete":
                raise RuntimeError(
                    f"Evaluation {run_id} ended with {payload['status']}."
                )
            return payload
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Evaluation timed out while polling: {run_id}")
        time.sleep(5)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset", type=Path, default=Path("tmp/evaluationrag_32/dataset.jsonl")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("tmp/evaluationrag_32"))
    parser.add_argument("--base-url", default="http://127.0.0.1:3000")
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument("--group-path", default="/test")
    parser.add_argument("--full-runs", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=int, default=14400)
    args = parser.parse_args()

    content = args.dataset.read_text(encoding="utf-8")
    session = requests.Session()
    csrf = login(session, args.base_url)
    dataset = _import_dataset(
        session,
        base_url=args.base_url,
        csrf=csrf,
        content=content,
    )
    corpus = _verify_corpus(
        session,
        base_url=args.base_url,
        qdrant_url=args.qdrant_url,
        group_path=args.group_path,
        content=content,
    )
    state: dict[str, Any] = {"dataset": dataset, "corpus": corpus, "runs": []}
    _write_json(args.output_dir / "state.json", state)
    print(json.dumps({"dataset": dataset, "corpus": corpus}, indent=2), flush=True)

    smoke = _run(
        session,
        base_url=args.base_url,
        csrf=csrf,
        dataset_id=dataset["dataset_id"],
        group_path=args.group_path,
        case_ids=SMOKE_CASE_IDS,
        output_path=args.output_dir / "smoke.json",
        timeout_seconds=args.timeout_seconds,
    )
    state["runs"].append(
        {"kind": "smoke", "run_id": smoke["id"], "summary": smoke["summary"]}
    )
    _write_json(args.output_dir / "state.json", state)

    for number in range(1, args.full_runs + 1):
        result = _run(
            session,
            base_url=args.base_url,
            csrf=csrf,
            dataset_id=dataset["dataset_id"],
            group_path=args.group_path,
            case_ids=[],
            output_path=args.output_dir / f"full-{number}.json",
            timeout_seconds=args.timeout_seconds,
        )
        state["runs"].append(
            {
                "kind": f"full-{number}",
                "run_id": result["id"],
                "summary": result["summary"],
            }
        )
        _write_json(args.output_dir / "state.json", state)

    print(json.dumps(state, indent=2), flush=True)


if __name__ == "__main__":
    main()
