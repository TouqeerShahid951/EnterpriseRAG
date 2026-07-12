from __future__ import annotations

import pytest
from pydantic import ValidationError

from rag.core.config import Settings


def test_artifact_pipeline_version_rejects_unknown_values() -> None:
    with pytest.raises(ValidationError):
        Settings(artifact_pipeline_version="v3")  # type: ignore[arg-type]


def test_artifact_pipeline_version_accepts_supported_values() -> None:
    assert Settings(artifact_pipeline_version="v1").artifact_pipeline_version == "v1"
    assert Settings(artifact_pipeline_version="v2").artifact_pipeline_version == "v2"
