from types import SimpleNamespace

from rag.abbreviations import task_execution


class _Backend:
    def __init__(self) -> None:
        self.updates: list[dict[str, object]] = []

    def start_attempt(self, **_kwargs):
        return SimpleNamespace(accepted=True, job_status="processing")

    def update_job(self, **kwargs) -> None:
        self.updates.append(kwargs)

    def replace_abbreviation_glossary(self, **_kwargs) -> None:
        pass


def test_glossary_import_uses_supported_job_progress_units(monkeypatch) -> None:
    backend = _Backend()
    monkeypatch.setattr(
        task_execution.WorkerConfig,
        "from_env",
        lambda: SimpleNamespace(minio=object()),
    )
    monkeypatch.setattr(task_execution, "build_backend_client", lambda _config: backend)
    monkeypatch.setattr(task_execution.UploadObjectReader, "read", lambda _self, _path: b"pdf")
    monkeypatch.setattr(
        task_execution,
        "extract_glossary_source",
        lambda *_args, **_kwargs: SimpleNamespace(entries=(("TDN", "Tradesman", 1),), rejected_entries=()),
    )

    task_execution.run_glossary_source_import(
        {
            "job_id": "job-1",
            "doc_id": "doc-1",
            "file_path": "glossary.pdf",
            "group_path": "/",
            "supersedes": [],
            "content_type": "application/pdf",
        }
    )

    assert [update["stage_progress"]["unit"] for update in backend.updates] == [
        "files",
        "metadata",
        "metadata",
    ]
