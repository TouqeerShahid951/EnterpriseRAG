from __future__ import annotations

from pathlib import Path

import pytest

from rag.artifact_jobs.adapters.storage import LocalGeneratedArtifactStorage


def test_local_storage_stable_object_key_overwrites_atomically_and_deletes_idempotently(
    tmp_path,
) -> None:
    storage = LocalGeneratedArtifactStorage(str(tmp_path))

    first = storage.put(
        filename="Quarterly Report.docx",
        content=b"first",
        content_type="application/docx",
        object_key="jobs/job-1/report.docx",
    )
    second = storage.put(
        filename="Renamed Report.docx",
        content=b"second",
        content_type="application/docx",
        object_key="jobs/job-1/report.docx",
    )

    assert first.object_path == second.object_path
    assert Path(second.object_path).read_bytes() == b"second"
    assert storage.delete(second.object_path)
    assert not storage.delete(second.object_path)


@pytest.mark.parametrize(
    "object_key", ["", "../report.docx", "/report.docx", "jobs\\report.docx"]
)
def test_local_storage_rejects_unsafe_stable_object_keys(
    tmp_path, object_key: str
) -> None:
    storage = LocalGeneratedArtifactStorage(str(tmp_path))

    with pytest.raises(ValueError):
        storage.put(
            filename="report.docx",
            content=b"content",
            content_type="application/docx",
            object_key=object_key,
        )


def test_local_storage_default_key_remains_unique(tmp_path) -> None:
    storage = LocalGeneratedArtifactStorage(str(tmp_path))

    first = storage.put(
        filename="report.pdf", content=b"one", content_type="application/pdf"
    )
    second = storage.put(
        filename="report.pdf", content=b"two", content_type="application/pdf"
    )

    assert first.object_path != second.object_path
