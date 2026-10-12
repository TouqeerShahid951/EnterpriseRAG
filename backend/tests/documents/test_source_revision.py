"""Revision constraints apply to source metadata and every binary preview path."""

from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from rag.auth.dependencies import require_current_user
from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.documents.routes import content
from rag.documents.repository import get_document_repository
from rag.ingestion.publication.models import generation_id_for_job
from rag.query.qdrant import SearchHit
from documents.document_route_characterization_support import _document, _user


@pytest.fixture
def viewer():
    user = _user("contributor")
    memory = InMemoryDocumentRepository()
    document = replace(
        _document(memory, user=user),
        file_path="original.pdf",
        content_hash=sha256(b"original").hexdigest(),
        active_index_generation_id=generation_id_for_job("job"),
    )
    repo = Mock()
    repo.get_document.return_value = document
    asset = SimpleNamespace(
        doc_id=document.id,
        job_id="job",
        page=1,
        source_kind="pptx_slide",
        object_path="preview.png",
        content_type="image/png",
        content_hash=sha256(b"preview").hexdigest(),
    )
    repo.get_document_image_asset.return_value = asset
    repo.list_document_image_assets.return_value = [asset]
    upload = Mock(
        read=Mock(
            return_value=SimpleNamespace(
                content=b"original", filename="file.pdf", content_type="application/pdf"
            )
        )
    )
    images = Mock(
        read=Mock(
            return_value=SimpleNamespace(
                content=b"preview", filename="preview.png", content_type="image/png"
            )
        )
    )
    qdrant = Mock(
        retrieve_source_chunk=Mock(
            return_value=SearchHit(
                point_id="point",
                score=1,
                payload={
                    "doc_id": document.id,
                    "chunk_id": "chunk",
                    "text": "Retention is 30 days.",
                    "doc_title": document.title,
                    "group_path": document.group_path,
                    "index_generation_id": document.active_index_generation_id,
                    "content_hash": document.content_hash,
                    "provenance_kind": "native",
                },
            )
        )
    )
    app = FastAPI()
    app.include_router(content.router, prefix="/api/v1")

    def dependency_for(value):
        return lambda: value

    for dependency, value in (
        (require_current_user, user),
        (get_document_repository, repo),
        (content.get_upload_storage, upload),
        (content.get_document_image_asset_storage, images),
        (content.get_document_qdrant_client, qdrant),
    ):
        app.dependency_overrides[dependency] = dependency_for(value)
    with TestClient(app) as client:
        yield SimpleNamespace(
            client=client,
            repo=repo,
            document=document,
            upload=upload,
            images=images,
            qdrant=qdrant,
            params={
                "generation_id": document.active_index_generation_id,
                "content_hash": document.content_hash,
            },
        )


@pytest.mark.parametrize(
    "suffix",
    [
        "sources/chunk",
        "content",
        "slides",
        "slides/1/content",
        "image-assets/asset/content",
    ],
)
def test_current_revision_opens_and_replacement_is_rejected(viewer, suffix):
    url = f"/api/v1/docs/{viewer.document.id}/{suffix}"
    assert viewer.client.get(url, params=viewer.params).status_code == 200
    viewer.repo.get_document.return_value = replace(
        viewer.document, active_index_generation_id="replacement"
    )
    failed = viewer.client.get(url, params=viewer.params)
    assert failed.status_code == 404
    assert failed.json()["detail"]["code"] == "source_revision_unavailable"
    assert viewer.document.title not in failed.text


@pytest.mark.parametrize(
    "suffix",
    [
        "sources/chunk",
        "content",
        "slides",
        "slides/1/content",
        "image-assets/asset/content",
    ],
)
def test_access_denial_precedes_revision_details(viewer, suffix):
    viewer.repo.get_document.return_value = replace(
        viewer.document, group_path="/private", active_index_generation_id="replacement"
    )
    failed = viewer.client.get(
        f"/api/v1/docs/{viewer.document.id}/{suffix}", params=viewer.params
    )
    assert failed.status_code == 404
    assert failed.json()["detail"]["code"] == "document_not_found"


def test_source_chunk_hash_mismatch_never_substitutes_new_text(viewer):
    failed = viewer.client.get(
        f"/api/v1/docs/{viewer.document.id}/sources/chunk",
        params={**viewer.params, "evidence_hash": sha256(b"old chunk").hexdigest()},
    )
    assert failed.json()["detail"]["code"] == "source_revision_unavailable"
    assert "Retention" not in failed.text


@pytest.mark.parametrize("field", ["doc_id", "chunk_id"])
def test_lookup_cannot_return_another_identity_with_matching_revision(viewer, field):
    viewer.qdrant.retrieve_source_chunk.return_value.payload[field] = "other"
    failed = viewer.client.get(
        f"/api/v1/docs/{viewer.document.id}/sources/chunk", params=viewer.params
    )
    assert failed.status_code == 404
    assert failed.json()["detail"]["code"] == "source_revision_unavailable"
    assert "Retention" not in failed.text


@pytest.mark.parametrize(
    "suffix,storage_name",
    [
        ("content", "upload"),
        ("slides/1/content", "images"),
        ("image-assets/asset/content", "images"),
    ],
)
def test_binary_replacement_between_metadata_and_read_is_rejected(
    viewer, suffix, storage_name
):
    storage = getattr(viewer, storage_name)
    storage.read.return_value.content = b"replacement"
    failed = viewer.client.get(
        f"/api/v1/docs/{viewer.document.id}/{suffix}", params=viewer.params
    )
    assert failed.status_code == 404
    assert failed.json()["detail"]["code"] == "source_revision_unavailable"


def test_generation_change_during_read_is_rejected(viewer):
    viewer.repo.get_document.side_effect = [
        viewer.document,
        replace(viewer.document, active_index_generation_id="replacement"),
    ]
    failed = viewer.client.get(
        f"/api/v1/docs/{viewer.document.id}/content", params=viewer.params
    )
    assert failed.status_code == 404


def test_preview_from_old_ingestion_job_is_rejected(viewer):
    viewer.repo.get_document_image_asset.return_value.job_id = "old-job"
    failed = viewer.client.get(
        f"/api/v1/docs/{viewer.document.id}/image-assets/asset/content",
        params=viewer.params,
    )
    assert failed.json()["detail"]["code"] == "source_revision_unavailable"


def test_legacy_source_link_remains_readable_but_has_no_verification(viewer):
    response = viewer.client.get(f"/api/v1/docs/{viewer.document.id}/sources/chunk")
    assert response.status_code == 200
    assert response.json()["citation_protocol_version"] is None
