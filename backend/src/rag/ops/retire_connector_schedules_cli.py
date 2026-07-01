"""One-time cleanup for retired database connector sync schedules."""

from __future__ import annotations

import json

from rag.core.config import settings
from rag.query.qdrant import QdrantClient
from rag.repositories.documents import get_document_repository
from rag.repositories.folder_schedules import get_folder_schedule_repository
from rag.services.connector_schedule_retirement import retire_connector_schedules
from rag.services.document_image_asset_storage import get_document_image_asset_storage
from rag.services.upload_storage import get_upload_storage


def main() -> None:
    result = retire_connector_schedules(
        schedule_repo=get_folder_schedule_repository(),
        document_repo=get_document_repository(),
        qdrant=QdrantClient(
            base_url=settings.qdrant_url,
            collection=settings.qdrant_collection,
            timeout_seconds=settings.rag_http_timeout_seconds,
        ),
        storage=get_upload_storage(),
        image_storage=get_document_image_asset_storage(),
    )
    print(json.dumps(result.__dict__, sort_keys=True))


if __name__ == "__main__":
    main()
