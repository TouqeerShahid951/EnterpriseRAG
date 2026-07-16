#!/usr/bin/env python3
"""Run or fetch two full benchmark evaluations and apply the release gate."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import time
from typing import Any

import requests

from ingest import api_error, dataset_semantic_hash, login, sha256
from rag.evaluations.release_gate import evaluate_release_gate
from rag.evaluations.runtime_pins import runtime_pins_from_snapshot


PACKAGE_DIR = Path(__file__).resolve().parent

DATASET_PATH = PACKAGE_DIR / "dataset.jsonl"
GOLD_PATH = PACKAGE_DIR / "ranking-gold.json"
MANIFEST_PATH = PACKAGE_DIR / "corpus-manifest.json"
INGESTION_RESULTS_PATH = PACKAGE_DIR / "ingestion-results.json"
TERMINAL = {"complete", "partial", "failed", "cancelled"}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _dataset_cases() -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in DATASET_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _save(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _dataset_id() -> str:
    payload = _load_json(INGESTION_RESULTS_PATH)
    dataset_id = payload.get("evaluation_dataset", {}).get("dataset_id")
    if not dataset_id:
        raise SystemExit("ingestion-results.json has no imported evaluation dataset id")
    return str(dataset_id)


def _preflight(
    session: requests.Session,
    *,
    base_url: str,
    dataset_id: str,
    local_cases: list[dict[str, Any]],
    ranking_gold: dict[str, Any],
) -> dict[str, str]:
    dataset_hash = sha256(DATASET_PATH)
    manifest_hash = sha256(MANIFEST_PATH)
    if ranking_gold.get("dataset_sha256") != dataset_hash:
        raise SystemExit("ranking-gold.json is not bound to the current dataset.jsonl")
    if ranking_gold.get("corpus_manifest_sha256") != manifest_hash:
        raise SystemExit("ranking-gold.json is not bound to the current corpus manifest")

    response = session.get(
        f"{base_url}/api/v1/rag-evaluations/datasets/{dataset_id}", timeout=30
    )
    if not response.ok:
        code, message = api_error(response)
        raise SystemExit(
            f"Could not read evaluation dataset ({response.status_code}, {code}): {message}"
        )
    local_semantic_hash = dataset_semantic_hash(local_cases)
    remote_semantic_hash = dataset_semantic_hash(response.json().get("cases") or [])
    if remote_semantic_hash != local_semantic_hash:
        raise SystemExit(
            "Imported evaluation dataset is stale; rerun ingest.py before the release gate"
        )
    return {
        "dataset_semantic_hash": local_semantic_hash,
        "ranking_gold_hash": sha256(GOLD_PATH),
        "corpus_manifest_hash": manifest_hash,
    }


def _read_run(
    session: requests.Session, *, base_url: str, run_id: str
) -> dict[str, Any]:
    response = session.get(
        f"{base_url}/api/v1/rag-evaluations/runs/{run_id}", timeout=30
    )
    if not response.ok:
        code, message = api_error(response)
        raise SystemExit(
            f"Could not read evaluation run {run_id} "
            f"({response.status_code}, {code}): {message}"
        )
    return dict(response.json())


def _launch_run(
    session: requests.Session,
    *,
    base_url: str,
    csrf: str,
    dataset_id: str,
    group_path: str,
    case_ids: list[str],
) -> str:
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
        raise SystemExit(
            f"Could not launch evaluation ({response.status_code}, {code}): {message}"
        )
    payload = response.json()
    if payload.get("case_count") != len(case_ids):
        raise SystemExit(
            f"Requested {len(case_ids)} cases but launched {payload.get('case_count')}"
        )
    return str(payload["id"])


def _wait_for_run(
    session: requests.Session,
    *,
    base_url: str,
    run_id: str,
    timeout_seconds: int,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    previous: tuple[object, ...] | None = None
    while True:
        payload = _read_run(session, base_url=base_url, run_id=run_id)
        snapshot = (
            payload.get("status"),
            payload.get("stage"),
            payload.get("completed_count"),
            payload.get("passed_count"),
            payload.get("failed_count"),
        )
        if snapshot != previous:
            print(
                f"[{payload.get('status')}] run={run_id} "
                f"completed={payload.get('completed_count')}/{payload.get('case_count')} "
                f"passed={payload.get('passed_count')} failed={payload.get('failed_count')}",
                flush=True,
            )
            previous = snapshot
        if payload.get("status") in TERMINAL:
            return payload
        if time.monotonic() >= deadline:
            raise SystemExit(f"Evaluation run timed out: {run_id}")
        time.sleep(poll_interval_seconds)


def _merged_run_pins(
    run: dict[str, Any], file_pins: dict[str, str]
) -> dict[str, Any]:
    return {
        **runtime_pins_from_snapshot(run.get("rag_config_snapshot")),
        **file_pins,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3000")
    parser.add_argument("--group-path", default="/test")
    parser.add_argument("--run-id", action="append", default=[])
    parser.add_argument("--timeout-seconds", type=int, default=21600)
    parser.add_argument("--poll-interval-seconds", type=float, default=3.0)
    parser.add_argument("--output", default="release-gate-results.json")
    args = parser.parse_args()
    if len(args.run_id) not in {0, 2}:
        parser.error("provide either zero or exactly two --run-id values")
    if any(not run_id.strip() for run_id in args.run_id):
        parser.error("--run-id cannot be empty")

    output = Path(args.output)
    if not output.is_absolute():
        output = PACKAGE_DIR / output
    base_url = args.base_url.rstrip("/")
    local_cases = _dataset_cases()
    ranking_gold = _load_json(GOLD_PATH)
    dataset_id = _dataset_id()
    session = requests.Session()
    csrf = login(session, base_url)
    file_pins = _preflight(
        session,
        base_url=base_url,
        dataset_id=dataset_id,
        local_cases=local_cases,
        ranking_gold=ranking_gold,
    )
    run_ids = list(args.run_id)
    runs: list[dict[str, Any]] = []
    if not run_ids:
        case_ids = [str(case["id"]) for case in local_cases]
        for _ in range(2):
            run_ids.append(
                _launch_run(
                    session,
                    base_url=base_url,
                    csrf=csrf,
                    dataset_id=dataset_id,
                    group_path=args.group_path,
                    case_ids=case_ids,
                )
            )
            runs.append(
                _wait_for_run(
                    session,
                    base_url=base_url,
                    run_id=run_ids[-1],
                    timeout_seconds=args.timeout_seconds,
                    poll_interval_seconds=args.poll_interval_seconds,
                )
            )
    else:
        runs = [
            _wait_for_run(
                session,
                base_url=base_url,
                run_id=run_id,
                timeout_seconds=args.timeout_seconds,
                poll_interval_seconds=args.poll_interval_seconds,
            )
            for run_id in run_ids
        ]
    for run in runs:
        if run.get("dataset_id") != dataset_id:
            raise SystemExit(
                f"Run {run.get('id')} belongs to a different evaluation dataset"
            )
        run["pins"] = _merged_run_pins(run, file_pins)
    expected_pins: dict[str, Any] = {
        "dataset_id": dataset_id,
        **dict(runs[0]["pins"]),
        "rag_config_snapshot": runs[0].get("rag_config_snapshot"),
        "reranker_model": dict(runs[0].get("rag_config_snapshot") or {}).get(
            "reranker_model"
        ),
    }
    report = evaluate_release_gate(
        runs,
        ranking_gold=ranking_gold,
        dataset_cases=local_cases,
        expected_pins=expected_pins,
    )
    artifact = {
        "created_at": datetime.now(UTC).isoformat(),
        "expected_pins": expected_pins,
        "runs": runs,
        "report": report,
    }
    _save(output, artifact)
    print(json.dumps(report, indent=2))
    if not report.get("passed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
