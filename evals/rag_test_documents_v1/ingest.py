#!/usr/bin/env python3
"""Idempotently ingest the generated corpus manifest and import its eval dataset."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

import requests

from rag.evaluations.schemas import EvaluationCase


PACKAGE_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = PACKAGE_DIR / "corpus-manifest.json"
DATASET_PATH = PACKAGE_DIR / "dataset.jsonl"
RESULTS_PATH = PACKAGE_DIR / "ingestion-results.json"
TERMINAL = {"complete", "failed", "human_review", "cancelled"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def save_results(results: dict[str, Any]) -> None:
    temporary = RESULTS_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(RESULTS_PATH)


def api_error(response: requests.Response) -> tuple[str | None, str]:
    try:
        payload = response.json()
    except ValueError:
        return None, response.text[:500]
    detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
    if isinstance(detail, dict):
        return detail.get("code"), str(detail.get("message") or detail)
    return None, str(detail)


def credentials() -> tuple[str, str]:
    dotenv = _read_dotenv(PACKAGE_DIR.parents[1] / ".env")
    email = (
        os.environ.get("RAG_EMAIL")
        or os.environ.get("BOOTSTRAP_ADMIN_EMAIL")
        or dotenv.get("BOOTSTRAP_ADMIN_EMAIL")
        or "admin@prudentia.ai"
    )
    password = (
        os.environ.get("RAG_PASSWORD")
        or os.environ.get("BOOTSTRAP_ADMIN_PASSWORD")
        or dotenv.get("BOOTSTRAP_ADMIN_PASSWORD")
    )
    if not password:
        password = getpass.getpass(f"Password for {email}: ")
    if not password:
        raise SystemExit("RAG_PASSWORD is required")
    return email, password


def _read_dotenv(path: Path) -> dict[str, str]:
    """Read literal KEY=VALUE pairs without evaluating shell syntax."""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def login(session: requests.Session, base_url: str) -> str:
    email, password = credentials()
    response = session.post(
        f"{base_url}/api/v1/auth/login",
        json={"email": email, "password": password},
        timeout=30,
    )
    if not response.ok:
        code, message = api_error(response)
        raise SystemExit(f"Login failed ({response.status_code}, {code}): {message}")
    return str(response.json()["csrf_token"])


def list_documents(session: requests.Session, base_url: str, group_path: str) -> list[dict[str, Any]]:
    response = session.get(
        f"{base_url}/api/v1/docs",
        params={"group_path": group_path},
        timeout=30,
    )
    response.raise_for_status()
    return list(response.json().get("items") or [])


def list_latest_ingest_jobs(
    session: requests.Session,
    base_url: str,
    group_path: str,
) -> dict[str, dict[str, Any]]:
    items: list[dict[str, Any]] = []
    offset = 0
    while True:
        response = session.get(
            f"{base_url}/api/v1/ingest-jobs",
            params={"group_path": group_path, "limit": 100, "offset": offset},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        page = list(payload.get("items") or [])
        items.extend(page)
        offset += len(page)
        if not page or offset >= int(payload.get("total") or 0):
            break
    latest: dict[str, dict[str, Any]] = {}
    for item in sorted(items, key=lambda row: str(row.get("created_at") or "")):
        latest[item["document_id"]] = item
    return latest


def resolve_file(entry: dict[str, Any], source_root: Path) -> Path:
    if entry["kind"] == "source":
        path = source_root / entry["relative_path"]
    else:
        path = PACKAGE_DIR / entry["relative_path"]
    if not path.is_file():
        raise SystemExit(f"Manifest file is missing: {path}")
    actual_hash = sha256(path)
    if actual_hash != entry["sha256"]:
        raise SystemExit(f"Hash mismatch for {path}: manifest={entry['sha256']} actual={actual_hash}")
    return path


def upload(
    session: requests.Session,
    *,
    base_url: str,
    csrf: str,
    group_path: str,
    entry: dict[str, Any],
    path: Path,
) -> requests.Response:
    with path.open("rb") as handle:
        return session.post(
            f"{base_url}/api/v1/upload",
            headers={"X-CSRF-Token": csrf},
            data={
                "group_path": group_path,
                "clearance_level": "NATO_RESTRICTED",
                "quality_preset": entry["quality_preset"],
                "description": f"rag-test-documents-v1; tier={entry['tier']}; sha256={entry['sha256']}",
            },
            files={"file": (entry["upload_title"], handle, entry["content_type"])},
            timeout=600,
        )


def poll_jobs(
    session: requests.Session,
    *,
    base_url: str,
    jobs: dict[str, dict[str, Any]],
    results: dict[str, Any],
    timeout_seconds: int,
    interval_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_report: dict[str, tuple[str, int, str]] = {}
    pending = set(jobs)
    while pending:
        for job_id in list(pending):
            response = session.get(f"{base_url}/api/v1/upload/{job_id}/status", timeout=30)
            if not response.ok:
                code, message = api_error(response)
                jobs[job_id].update(status="status_error", http_status=response.status_code, error_code=code, error_message=message)
                pending.remove(job_id)
                continue
            status = response.json()
            snapshot = (str(status["status"]), int(status["progress_pct"]), str(status["stage"]))
            jobs[job_id].update(
                status=status["status"],
                progress_pct=status["progress_pct"],
                stage=status["stage"],
                stage_detail=status.get("stage_detail"),
                warnings=status.get("warnings") or [],
                error_code=status.get("error_code"),
                error_message=status.get("error_message"),
                parser_provenance=status.get("parser_provenance"),
                updated_at=now(),
            )
            if last_report.get(job_id) != snapshot:
                print(f"[{status['status']:12}] {status['progress_pct']:3}% {jobs[job_id]['title']} — {status['stage']}", flush=True)
                last_report[job_id] = snapshot
            if status["status"] in TERMINAL:
                pending.remove(job_id)
        results["updated_at"] = now()
        results["jobs"] = list(jobs.values())
        save_results(results)
        if not pending:
            return
        if time.monotonic() >= deadline:
            for job_id in pending:
                jobs[job_id].update(status="poll_timeout", updated_at=now())
            results["updated_at"] = now()
            results["jobs"] = list(jobs.values())
            save_results(results)
            return
        time.sleep(interval_seconds)


def import_dataset(
    session: requests.Session,
    *,
    base_url: str,
    csrf: str,
    content: str,
) -> dict[str, Any]:
    name = "RAG test documents v1"
    expected_count = sum(1 for line in content.splitlines() if line.strip())
    local_semantic_hash = dataset_semantic_hash(
        [json.loads(line) for line in content.splitlines() if line.strip()]
    )
    response = session.get(f"{base_url}/api/v1/rag-evaluations/datasets", timeout=30)
    response.raise_for_status()
    version_prefix = f"{name} ["
    matches = [
        item
        for item in response.json().get("items", [])
        if item.get("name") == name
        or (
            str(item.get("name") or "").startswith(version_prefix)
            and str(item.get("name") or "").endswith("]")
        )
    ]
    exact = None
    for item in matches:
        detail = session.get(
            f"{base_url}/api/v1/rag-evaluations/datasets/{item['id']}",
            timeout=30,
        )
        detail.raise_for_status()
        if dataset_semantic_hash(detail.json().get("cases") or []) == local_semantic_hash:
            exact = item
            break
    if exact:
        return {
            "action": "existing",
            "dataset_id": exact["id"],
            "name": exact["name"],
            "case_count": expected_count,
            "semantic_sha256": local_semantic_hash,
        }
    import_name = f"{name} [{local_semantic_hash[:12]}]" if matches else name
    response = session.post(
        f"{base_url}/api/v1/rag-evaluations/datasets",
        headers={"X-CSRF-Token": csrf},
        json={"name": import_name, "content": content, "source_format": "jsonl"},
        timeout=120,
    )
    if not response.ok:
        code, message = api_error(response)
        return {"action": "error", "http_status": response.status_code, "error_code": code, "error_message": message}
    payload = response.json()
    return {
        "action": "imported",
        "dataset_id": payload["id"],
        "name": payload["name"],
        "case_count": payload["case_count"],
        "semantic_sha256": local_semantic_hash,
    }


def dataset_semantic_hash(cases: list[dict[str, Any]]) -> str:
    canonical = []
    for raw_case in cases:
        case = EvaluationCase.model_validate(raw_case).model_dump(mode="json")
        case["metadata"].pop("source_shape", None)
        canonical.append(case)
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def qdrant_vector_count(
    session: requests.Session,
    *,
    qdrant_url: str,
    title: str,
    content_hash: str,
    document_id: str,
) -> int:
    response = session.post(
        f"{qdrant_url.rstrip('/')}/collections/documents/points/count",
        json={
            "exact": True,
            "filter": {
                "must": [
                    {"key": "doc_id", "match": {"value": document_id}},
                    {"key": "content_hash", "match": {"value": content_hash}},
                    {"key": "retrieval_status", "match": {"value": "active"}},
                ]
            },
        },
        timeout=30,
    )
    response.raise_for_status()
    return int(response.json()["result"]["count"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3000")
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument("--group-path", default="/test")
    parser.add_argument("--tiers", default="core,distractor,ocr_stress")
    parser.add_argument("--timeout-seconds", type=int, default=7200)
    parser.add_argument("--poll-interval-seconds", type=float, default=3.0)
    parser.add_argument("--skip-dataset-import", action="store_true")
    args = parser.parse_args()

    manifest_bytes = MANIFEST_PATH.read_bytes()
    dataset_content = DATASET_PATH.read_text(encoding="utf-8")
    manifest = json.loads(manifest_bytes)
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    dataset_hash = hashlib.sha256(dataset_content.encode("utf-8")).hexdigest()
    source_root = Path(manifest["source_root"])
    selected_tiers = {item.strip() for item in args.tiers.split(",") if item.strip()}
    entries = [item for item in manifest["files"] if item["tier"] in selected_tiers]
    unknown_tiers = selected_tiers - {item["tier"] for item in manifest["files"]}
    if unknown_tiers:
        raise SystemExit(f"Unknown tiers: {sorted(unknown_tiers)}")

    session = requests.Session()
    csrf = login(session, args.base_url.rstrip("/"))
    base_url = args.base_url.rstrip("/")
    documents = list_documents(session, base_url, args.group_path)
    latest_jobs_by_document = list_latest_ingest_jobs(session, base_url, args.group_path)
    by_title: dict[str, list[dict[str, Any]]] = {}
    for document in documents:
        if document.get("is_current", True):
            by_title.setdefault(document["title"], []).append(document)
    results: dict[str, Any] = {
        "schema_version": 1,
        "dataset_id": manifest["dataset_id"],
        "manifest_sha256": manifest_hash,
        "dataset_sha256": dataset_hash,
        "source_root": str(source_root),
        "group_path": args.group_path,
        "selected_tiers": sorted(selected_tiers),
        "started_at": now(),
        "updated_at": now(),
        "actions": [],
        "jobs": [],
    }
    save_results(results)
    jobs: dict[str, dict[str, Any]] = {}

    for index, entry in enumerate(entries, start=1):
        path = resolve_file(entry, source_root)
        title = entry["upload_title"]
        existing_candidates = by_title.get(title, [])
        existing = None
        vector_count = 0
        for candidate in existing_candidates:
            candidate_count = qdrant_vector_count(
                session,
                qdrant_url=args.qdrant_url,
                title=title,
                content_hash=entry["sha256"],
                document_id=candidate["id"],
            )
            if candidate.get("ingest_status") == "complete" and candidate_count > 0:
                existing = candidate
                vector_count = candidate_count
                break
        if existing is None and existing_candidates:
            existing = next(
                (
                    candidate
                    for candidate in existing_candidates
                    if candidate.get("ingest_status") in {"scheduled", "queued", "processing"}
                ),
                existing_candidates[0],
            )
        if existing:
            status = existing.get("ingest_status")
            active_job = latest_jobs_by_document.get(existing["id"])
            if status in {"scheduled", "queued", "processing"} and active_job:
                job_id = str(active_job["job_id"])
                job = {
                    "job_id": job_id,
                    "title": title,
                    "relative_path": entry["relative_path"],
                    "sha256": entry["sha256"],
                    "tier": entry["tier"],
                    "quality_preset": entry["quality_preset"],
                    "status": status,
                    "submitted_at": active_job.get("created_at"),
                    "adopted_existing_job": True,
                }
                jobs[job_id] = job
                results["actions"].append({**job, "action": "monitor_existing_active"})
                print(f"[monitoring_active ] {index:02}/{len(entries)} {title}", flush=True)
                save_results(results)
                continue
            if vector_count == 0:
                vector_count = qdrant_vector_count(
                    session,
                    qdrant_url=args.qdrant_url,
                    title=title,
                    content_hash=entry["sha256"],
                    document_id=existing["id"],
                )
            if status == "complete" and vector_count > 0:
                action = "existing_complete"
            elif status == "complete":
                action = "title_hash_conflict"
            else:
                action = "existing_unhealthy"
            print(f"[{action:18}] {index:02}/{len(entries)} {title}", flush=True)
            results["actions"].append(
                {
                    "title": title,
                    "relative_path": entry["relative_path"],
                    "sha256": entry["sha256"],
                    "action": action,
                    "document_id": existing.get("id"),
                    "ingest_status": status,
                    "vector_count": vector_count,
                }
            )
            save_results(results)
            continue

        response = upload(
            session,
            base_url=base_url,
            csrf=csrf,
            group_path=args.group_path,
            entry=entry,
            path=path,
        )
        if response.status_code == 202:
            job_id = str(response.json()["job_id"])
            print(f"[queued            ] {index:02}/{len(entries)} {title}", flush=True)
            job = {
                "job_id": job_id,
                "title": title,
                "relative_path": entry["relative_path"],
                "sha256": entry["sha256"],
                "tier": entry["tier"],
                "quality_preset": entry["quality_preset"],
                "status": "queued",
                "submitted_at": now(),
            }
            jobs[job_id] = job
            results["actions"].append({**job, "action": "queued"})
        else:
            code, message = api_error(response)
            action = "duplicate_content" if response.status_code == 409 and code == "duplicate_document" else "upload_error"
            print(f"[{action:18}] {index:02}/{len(entries)} {title} ({response.status_code}, {code})", flush=True)
            results["actions"].append(
                {
                    "title": title,
                    "relative_path": entry["relative_path"],
                    "sha256": entry["sha256"],
                    "action": action,
                    "http_status": response.status_code,
                    "error_code": code,
                    "error_message": message,
                }
            )
        results["updated_at"] = now()
        save_results(results)

    poll_jobs(
        session,
        base_url=base_url,
        jobs=jobs,
        results=results,
        timeout_seconds=args.timeout_seconds,
        interval_seconds=args.poll_interval_seconds,
    )
    documents = list_documents(session, base_url, args.group_path)
    entries_by_title = {entry["upload_title"]: entry for entry in entries}
    results["document_health"] = [
        {
            "document_id": item["id"],
            "title": item["title"],
            "ingest_status": item["ingest_status"],
            "expected_sha256": entries_by_title[item["title"]]["sha256"],
            "vector_count": qdrant_vector_count(
                session,
                qdrant_url=args.qdrant_url,
                title=item["title"],
                content_hash=entries_by_title[item["title"]]["sha256"],
                document_id=item["id"],
            ),
        }
        for item in documents
        if item["title"] in entries_by_title
    ]
    current_manifest_hash = sha256(MANIFEST_PATH)
    current_dataset_hash = sha256(DATASET_PATH)
    results["input_integrity"] = {
        "manifest_unchanged": current_manifest_hash == manifest_hash,
        "dataset_unchanged": current_dataset_hash == dataset_hash,
        "current_manifest_sha256": current_manifest_hash,
        "current_dataset_sha256": current_dataset_hash,
    }
    required_titles = {
        title
        for line in dataset_content.splitlines()
        if line.strip()
        for title in json.loads(line).get("expected_source_docs", [])
    }
    health_by_title: dict[str, dict[str, Any]] = {}
    for item in results["document_health"]:
        previous = health_by_title.get(item["title"])
        item_ready = item["ingest_status"] == "complete" and item["vector_count"] > 0
        previous_ready = bool(
            previous
            and previous["ingest_status"] == "complete"
            and previous["vector_count"] > 0
        )
        if previous is None or (item_ready and not previous_ready):
            health_by_title[item["title"]] = item
    required_health = [
        {
            "title": title,
            "present": title in health_by_title,
            "ingest_status": health_by_title.get(title, {}).get("ingest_status"),
            "vector_count": health_by_title.get(title, {}).get("vector_count", 0),
            "ready": (
                health_by_title.get(title, {}).get("ingest_status") == "complete"
                and health_by_title.get(title, {}).get("vector_count", 0) > 0
            ),
        }
        for title in sorted(required_titles)
    ]
    results["required_corpus_health"] = required_health
    corpus_ready = all(item["ready"] for item in required_health)
    if not args.skip_dataset_import:
        if current_manifest_hash != manifest_hash or current_dataset_hash != dataset_hash:
            results["evaluation_dataset"] = {
                "action": "refused_input_changed",
                "message": "Manifest or dataset changed while ingestion was running; run a clean pass before importing.",
            }
        elif not corpus_ready:
            results["evaluation_dataset"] = {
                "action": "refused_corpus_unhealthy",
                "message": "At least one dataset-required document is missing, incomplete, hash-mismatched, or has zero active vectors.",
                "unready_titles": [item["title"] for item in required_health if not item["ready"]],
            }
        else:
            results["evaluation_dataset"] = import_dataset(
                session,
                base_url=base_url,
                csrf=csrf,
                content=dataset_content,
            )
    results["completed_at"] = now()
    results["updated_at"] = now()
    save_results(results)

    failed = [job for job in jobs.values() if job.get("status") != "complete"]
    unhealthy = [
        item
        for item in results["actions"]
        if item.get("action") in {
            "existing_unhealthy", "title_hash_conflict", "duplicate_content", "upload_error"
        }
    ]
    dataset_action = results.get("evaluation_dataset", {}).get("action")
    dataset_failed = not args.skip_dataset_import and dataset_action not in {"imported", "existing"}
    print(json.dumps({"submitted": len(jobs), "completed": len(jobs) - len(failed), "failed_or_pending": len(failed), "preexisting_unhealthy": len(unhealthy), "dataset_action": dataset_action, "results": str(RESULTS_PATH)}, indent=2))
    if failed or unhealthy or dataset_failed:
        sys.exit(2)


if __name__ == "__main__":
    main()
