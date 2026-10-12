from fastapi import FastAPI
from fastapi.testclient import TestClient
from io import BytesIO
from PIL import Image

from rag.auth.dependencies import require_platform_admin_user
from rag.branding.adapters.memory import InMemoryBrandingRepository
from rag.branding.dependencies import get_branding_repository
from rag.branding.routes import router
from rag.documents.repository import get_document_repository


class AuditRepository:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def append_audit_event(self, **event: object) -> None:
        self.events.append(event)


def _client() -> tuple[TestClient, InMemoryBrandingRepository, AuditRepository]:
    app = FastAPI()
    app.include_router(router)
    branding = InMemoryBrandingRepository()
    audit = AuditRepository()
    app.dependency_overrides[get_branding_repository] = lambda: branding
    app.dependency_overrides[get_document_repository] = lambda: audit
    app.dependency_overrides[require_platform_admin_user] = lambda: type("User", (), {"id": "00000000-0000-0000-0000-000000000001"})()
    return TestClient(app), branding, audit


def test_branding_defaults_then_platform_admin_can_update_and_upload_logo() -> None:
    client, branding, audit = _client()

    assert client.get("/branding").json() == {
        "app_name": "Prudentia AI", "primary_color": "#b8a77a", "accent_color": "#b8a77a", "background_color": "#101016", "login_message": "Use your organization credentials to continue.", "support_url": None, "theme_mode": "user", "h1_size": "standard", "h1_weight": "bold", "h1_color": None, "h2_size": "standard", "h2_weight": "bold", "h2_color": None, "body_size": "standard", "logo_url": None, "updated_at": None,
    }
    saved = client.put("/admin/branding", json={"app_name": "Acme Knowledge", "primary_color": "#123456", "accent_color": "#654321", "background_color": "#101112", "login_message": "Welcome to Acme.", "support_url": "https://support.example.test", "theme_mode": "dark", "h1_size": "large", "h1_weight": "extrabold", "h1_color": "#ABCDEF", "h2_size": "compact", "h2_weight": "semibold", "h2_color": "#FEDCBA", "body_size": "large"})
    assert saved.status_code == 200
    assert saved.json()["app_name"] == "Acme Knowledge"
    assert saved.json()["h1_size"] == "large"
    assert saved.json()["h1_color"] == "#ABCDEF"
    assert saved.json()["body_size"] == "large"

    logo_content = _png()
    logo = client.post("/admin/branding/logo", files={"file": ("logo.png", logo_content, "image/png")})
    assert logo.status_code == 200
    assert logo.json()["logo_url"] == "/api/v1/branding/logo"
    assert client.get("/branding/logo").content == logo_content
    assert branding.get_active() is not None
    assert [event["event_type"] for event in audit.events] == ["admin.branding.updated", "admin.branding.logo_uploaded"]


def test_branding_rejects_untrusted_logo_types() -> None:
    client, _, _ = _client()
    response = client.post("/admin/branding/logo", files={"file": ("logo.svg", b"<svg/>", "image/svg+xml")})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_logo"


def test_branding_rejects_spoofed_image_content() -> None:
    client, _, _ = _client()
    response = client.post("/admin/branding/logo", files={"file": ("logo.png", b"not an image", "image/png")})
    assert response.status_code == 400


def _png() -> bytes:
    image = Image.new("RGB", (8, 8), "white")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
