from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from rag.abbreviations.adapters.memory import InMemoryAbbreviationRepository
from rag.abbreviations.dependencies import get_abbreviation_service
from rag.abbreviations.routes import router
from rag.abbreviations.service import AbbreviationGlossaryService
from rag.auth.dependencies import require_current_user
from rag.auth.identity_models import UserRecord
from rag.core.config import settings


def test_global_admin_routes_create_list_update_and_delete_entries() -> None:
    client = _client(_user("system_admin", ()))
    headers = _csrf_headers(client)

    created = client.post(
        "/abbreviation-glossaries/entries",
        json={
            "abbreviation": "AD",
            "expansion": "Assistant Director",
        },
        headers=headers,
    )
    listed = client.get("/abbreviation-glossaries")
    updated = client.patch(
        f"/abbreviation-glossaries/entries/{created.json()['id']}",
        json={
            "abbreviation": "AD",
            "expansion": "Associate Director",
            "expected_revision": 1,
        },
        headers=headers,
    )
    deleted = client.delete(
        f"/abbreviation-glossaries/entries/{created.json()['id']}",
        params={"expected_revision": 2},
        headers=headers,
    )

    assert created.status_code == 201
    assert listed.json()["items"][0]["abbreviation"] == "AD"
    assert updated.json()["expansion"] == "Associate Director"
    assert deleted.status_code == 204


def test_space_admin_is_rejected() -> None:
    client = _client(_user("space_admin", ("/finance",)))

    response = client.get("/abbreviation-glossaries")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "abbreviation_glossary_forbidden"


def test_admin_can_list_and_remove_pdf_sources() -> None:
    repository = InMemoryAbbreviationRepository()
    document_id = str(uuid4())
    repository.replace_from_document(
        document_id=document_id,
        entries=[("AD", "Assistant Director", 4)],
    )
    client = _client(_user("system_admin", ()), repository)
    headers = _csrf_headers(client)

    listed = client.get("/abbreviation-glossaries")
    removed = client.delete(
        f"/abbreviation-glossaries/sources/{document_id}",
        headers=headers,
    )

    assert listed.json()["sources"][0]["document_id"] == document_id
    assert removed.status_code == 204
    assert client.get("/abbreviation-glossaries").json()["sources"] == []


def _client(
    user: UserRecord,
    repository: InMemoryAbbreviationRepository | None = None,
) -> TestClient:
    repository = repository or InMemoryAbbreviationRepository()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_current_user] = lambda: user
    app.dependency_overrides[get_abbreviation_service] = lambda: AbbreviationGlossaryService(
        repository
    )
    return TestClient(app)


def _csrf_headers(client: TestClient) -> dict[str, str]:
    token = "csrf-test-token"
    client.cookies.set(settings.csrf_cookie_name, token)
    return {"X-CSRF-Token": token}


def _user(account_type: str, group_paths: tuple[str, ...]) -> UserRecord:
    return UserRecord(
        id=str(uuid4()),
        email=f"{uuid4()}@example.test",
        name="Test User",
        password_hash="hash",
        is_active=True,
        account_type=account_type,  # type: ignore[arg-type]
        clearance_level="NATO_SECRET",
        must_change_password=False,
        permission_version=1,
        group_paths=group_paths,
    )
