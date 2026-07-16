from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from rag.auth.adapters.identity_memory import InMemoryIdentityRepository
from rag.auth.dependencies import require_current_user
from rag.auth.identity_models import UserRecord
from rag.auth.identity_repository import get_identity_repository
from rag.core.config import settings
from rag.documents.upload import routes as upload_routes
from rag.documents.adapters.file_scanning import NoopFileScanner
from rag.documents.dependencies import get_file_scanner, get_upload_storage
from rag.documents.storage import StoredUpload
from rag.ingestion.contracts import IngestJobPayload
from rag.ingestion.queue import get_ingest_queue
from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.documents.repository import get_document_repository
from rag.ingestion.job_dependencies import get_ingest_job_repository

PDF_CONTENT = b"%PDF-1.7\nroute contract\n%%EOF"


class FakeQueue:
    def __init__(self) -> None:
        self.messages: list[IngestJobPayload] = []

    def enqueue(self, message: IngestJobPayload) -> None:
        self.messages.append(message)


class FakeStorage:
    def put(
        self, *, filename: str, content: bytes, content_type: str | None
    ) -> StoredUpload:
        return StoredUpload(
            object_path=f"memory://{filename}",
            size_bytes=len(content),
            content_type=content_type,
        )


def test_upload_route_parses_multipart_dependencies_and_response_contract() -> None:
    client, document_repo, queue = _client()

    response = _post_upload(client, group_path="/legal")

    assert response.status_code == 202
    body = response.json()
    assert body == {"job_id": body["job_id"], "status": "queued"}
    assert document_repo.get_ingest_job(body["job_id"]) is not None
    assert len(queue.messages) == 1


def test_upload_route_maps_application_rejection_to_existing_http_detail() -> None:
    client, document_repo, queue = _client()

    response = _post_upload(client, group_path="/missing")

    assert response.status_code == 400
    assert response.json() == {
        "detail": {
            "code": "group_not_found",
            "message": "Upload group does not exist.",
        }
    }
    assert document_repo.list_documents() == []
    assert queue.messages == []


def test_upload_route_enforces_csrf_before_application_service() -> None:
    client, document_repo, queue = _client()

    response = client.post(
        "/upload",
        data={"group_path": "/legal"},
        files={"file": ("contract.pdf", PDF_CONTENT, "application/pdf")},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "csrf_required"
    assert document_repo.list_documents() == []
    assert queue.messages == []


def _client() -> tuple[TestClient, InMemoryDocumentRepository, FakeQueue]:
    document_repo = InMemoryDocumentRepository()
    identity_repo = InMemoryIdentityRepository()
    identity_repo.create_group(path="/legal", name="Legal")
    user = UserRecord(
        id=str(uuid4()),
        email=f"{uuid4()}@example.test",
        name="Test User",
        password_hash="hash",
        is_active=True,
        account_type="contributor",
        clearance_level="NATO_RESTRICTED",
        must_change_password=False,
        permission_version=1,
        group_paths=("/legal",),
    )
    queue = FakeQueue()
    storage = FakeStorage()
    app = FastAPI()
    app.include_router(upload_routes.router)
    app.dependency_overrides[require_current_user] = lambda: user
    app.dependency_overrides[get_identity_repository] = lambda: identity_repo
    app.dependency_overrides[get_document_repository] = lambda: document_repo
    app.dependency_overrides[get_ingest_job_repository] = lambda: document_repo
    app.dependency_overrides[get_upload_storage] = lambda: storage
    app.dependency_overrides[get_file_scanner] = NoopFileScanner
    app.dependency_overrides[get_ingest_queue] = lambda: queue
    return TestClient(app), document_repo, queue


def _post_upload(client: TestClient, *, group_path: str):
    token = "csrf-test-token"
    client.cookies.set(settings.csrf_cookie_name, token)
    return client.post(
        "/upload",
        data={"group_path": group_path},
        files={"file": ("contract.pdf", PDF_CONTENT, "application/pdf")},
        headers={"X-CSRF-Token": token},
    )
