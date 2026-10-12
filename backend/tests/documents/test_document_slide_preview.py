from __future__ import annotations

import asyncio
from hashlib import sha256
from rag.documents.source_revision import SourceRevision
from dataclasses import replace
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.documents.image_asset_storage import StoredDocumentImageAssetContent
from rag.documents.routes.content import get_document_slide_content
from rag.documents.routes import content
from rag.documents.repository import get_document_repository
from rag.auth.dependencies import require_current_user

from documents.document_route_characterization_support import _document, _user


class _SlideStorage:
    def __init__(self) -> None:
        self.read_path: str | None = None

    def read(self, object_path: str) -> StoredDocumentImageAssetContent:
        self.read_path = object_path
        return StoredDocumentImageAssetContent(
            content=b"png-slide",
            content_type="image/png",
            filename="slide-1.png",
        )


def test_slide_catalog_http_contract_and_document_access() -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor")
    document = _document(repo, user=user)
    repo.replace_document_image_assets(doc_id=document.id, job_id="job-1", assets=[
        {"id": f"asset-{index}", "source_kind": kind, "page": page,
         "object_path": f"memory://{index}.png", "content_type": "image/png", "content_hash": str(index)}
        for index, (kind, page) in enumerate([("pptx_slide", 3), ("pptx_slide", 1), ("pptx_media", 2), ("pptx_slide", 3)])
    ])
    app = FastAPI()
    app.include_router(content.router, prefix="/api/v1")
    app.dependency_overrides[require_current_user] = lambda: user
    app.dependency_overrides[get_document_repository] = lambda: repo
    with TestClient(app) as client:
        response = client.get(f"/api/v1/docs/{document.id}/slides")
        assert response.status_code == 200
        assert response.json() == {"slides": [1, 3]}
        assert client.get("/api/v1/docs/missing/slides").status_code == 404
        app.dependency_overrides[require_current_user] = lambda: replace(_user("contributor"), group_paths=("/other",))
        assert client.get(f"/api/v1/docs/{document.id}/slides").status_code == 404
    operation = app.openapi()["paths"]["/api/v1/docs/{document_id}/slides"]["get"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/DocumentSlidesResponse")


def test_slide_preview_resolves_the_ingested_full_slide_asset() -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor")
    document = _document(repo, user=user)
    repo.replace_document_image_assets(
        doc_id=document.id,
        job_id="job-1",
        assets=[
            {
                "id": "asset-1",
                "source_kind": "pptx_slide",
                "page": 1,
                "object_path": "memory://slide-1.png",
                "content_type": "image/png",
                "content_hash": sha256(b"png-slide").hexdigest(),
            }
        ],
    )
    storage = _SlideStorage()

    response = asyncio.run(
        get_document_slide_content(
            document.id,
            1,
            expected=SourceRevision(),
            user=user,
            repo=repo,
            storage=storage,  # type: ignore[arg-type]
        )
    )

    assert response.status_code == 200
    assert response.media_type == "image/png"
    assert response.headers["content-length"] == "9"
    assert storage.read_path == "memory://slide-1.png"
