#!/usr/bin/env python3
"""Launch and capture a small cross-domain evaluation against the imported dataset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import requests

from ingest import dataset_semantic_hash, login


PACKAGE_DIR = Path(__file__).resolve().parent
TERMINAL = {"complete", "partial", "failed", "cancelled"}
DEFAULT_CASES = [
    "samsung-equipment-001",
    "fir-026",
    "insurance-010",
    "structured-003",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3000")
    parser.add_argument("--group-path", default="/test")
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    parser.add_argument("--poll-interval-seconds", type=float, default=3.0)
    parser.add_argument(
        "--case-id",
        action="append",
        dest="case_ids",
        help="Run only this case id; repeat the option for multiple cases.",
    )
    parser.add_argument(
        "--output",
        default="smoke-results.json",
        help="Result filename (relative paths are written inside this package).",
    )
    args = parser.parse_args()
    case_ids = args.case_ids or DEFAULT_CASES
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = PACKAGE_DIR / output_path

    ingestion = json.loads((PACKAGE_DIR / "ingestion-results.json").read_text(encoding="utf-8"))
    dataset_id = ingestion.get("evaluation_dataset", {}).get("dataset_id")
    if not dataset_id:
        raise SystemExit("ingestion-results.json does not contain an imported dataset id")

    session = requests.Session()
    base_url = args.base_url.rstrip("/")
    csrf = login(session, base_url)
    local_cases = [
        json.loads(line)
        for line in (PACKAGE_DIR / "dataset.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    dataset_response = session.get(
        f"{base_url}/api/v1/rag-evaluations/datasets/{dataset_id}", timeout=30
    )
    dataset_response.raise_for_status()
    if dataset_semantic_hash(dataset_response.json().get("cases") or []) != dataset_semantic_hash(local_cases):
        raise SystemExit("Imported evaluation dataset is stale; rerun ingest.py")
    response = session.post(
        f"{base_url}/api/v1/rag-evaluations/runs",
        headers={"X-CSRF-Token": csrf},
        json={
            "dataset_id": dataset_id,
            "group_path": args.group_path,
            "case_ids": case_ids,
        },
        timeout=30,
    )
    if not response.ok:
        raise SystemExit(f"Could not launch smoke evaluation: {response.status_code} {response.text[:500]}")
    launched = response.json()
    run_id = launched["id"]
    if launched.get("case_count") != len(case_ids):
        raise SystemExit(
            f"Requested {len(case_ids)} cases but API launched {launched.get('case_count')}: {run_id}"
        )
    deadline = time.monotonic() + args.timeout_seconds
    previous = None
    payload = launched
    while True:
        response = session.get(
            f"{base_url}/api/v1/rag-evaluations/runs/{run_id}",
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        snapshot = (
            payload["status"], payload["stage"], payload["progress_pct"],
            payload["completed_count"], payload["passed_count"], payload["failed_count"],
        )
        if snapshot != previous:
            print(
                f"[{payload['status']}] {payload['progress_pct']}% "
                f"completed={payload['completed_count']} passed={payload['passed_count']} "
                f"failed={payload['failed_count']} stage={payload['stage']}",
                flush=True,
            )
            previous = snapshot
        if payload["status"] in TERMINAL:
            output_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(json.dumps({"run_id": run_id, "status": payload["status"], "passed": payload["passed_count"], "failed": payload["failed_count"]}, indent=2))
            if payload["status"] != "complete" or payload["failed_count"]:
                raise SystemExit(1)
            return
        if time.monotonic() >= deadline:
            output_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            raise SystemExit(f"Smoke evaluation timed out: {run_id}")
        time.sleep(args.poll_interval_seconds)


if __name__ == "__main__":
    main()
