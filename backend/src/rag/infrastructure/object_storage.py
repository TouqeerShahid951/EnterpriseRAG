"""Object storage infrastructure adapter names."""

from rag.services.generated_artifact_storage import MinioGeneratedArtifactStorage
from rag.services.upload_storage import MinioUploadStorage

__all__ = ["MinioGeneratedArtifactStorage", "MinioUploadStorage"]
