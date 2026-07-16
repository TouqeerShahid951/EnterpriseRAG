from __future__ import annotations

from types import SimpleNamespace

from billiard.exceptions import SoftTimeLimitExceeded
import pytest

from rag.artifact_jobs import dependencies
from rag.artifact_jobs.adapters.query_generation import (
    QueryRuntimeArtifactJsonGenerator,
)
from rag.artifact_jobs.generation import ArtifactGenerationError
from rag.core.config import Settings
from rag.query.http import ServiceRequestError


def test_query_generation_adapter_delegates_exact_json_request() -> None:
    client = _QueryClient(response='{"title":"Quarterly review"}')
    generator = QueryRuntimeArtifactJsonGenerator(client)  # type: ignore[arg-type]

    result = generator.generate_json(
        prompt="Build the plan",
        model="reasoning-model",
        system="Return JSON",
    )

    assert result == '{"title":"Quarterly review"}'
    assert client.calls == [
        {
            "prompt": "Build the plan",
            "model": "reasoning-model",
            "system": "Return JSON",
        }
    ]


def test_query_generation_adapter_translates_provider_failure() -> None:
    provider_error = ServiceRequestError("vllm", "raw provider detail", 503)
    generator = QueryRuntimeArtifactJsonGenerator(  # type: ignore[arg-type]
        _QueryClient(error=provider_error)
    )

    with pytest.raises(ArtifactGenerationError) as raised:
        generator.generate_json(prompt="p", model=None, system="s")

    assert raised.value.service == "vllm"
    assert raised.value.status_code == 503
    assert str(raised.value) == "artifact generation provider vllm failed (status 503)"
    assert raised.value.__cause__ is provider_error


@pytest.mark.parametrize("error", [TimeoutError("timeout"), SoftTimeLimitExceeded()])
def test_query_generation_adapter_preserves_lifecycle_errors(error: Exception) -> None:
    generator = QueryRuntimeArtifactJsonGenerator(  # type: ignore[arg-type]
        _QueryClient(error=error)
    )

    with pytest.raises(type(error)) as raised:
        generator.generate_json(prompt="p", model=None, system="s")

    assert raised.value is error


def test_executor_wiring_reuses_one_query_client_for_generation_and_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = Settings(document_repository="memory")
    rag_config = SimpleNamespace(
        effective_reasoning_model="reasoning-model",
        chat_model="chat-model",
    )
    query_client = _QueryClient(response="{}")
    retriever = object()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        dependencies,
        "effective_rag_config",
        lambda *, config: rag_config,
    )
    monkeypatch.setattr(
        dependencies,
        "build_inference_client",
        lambda selected_config, *, settings: (
            captured.update(
                inference_config=selected_config,
                inference_settings=settings,
            )
            or query_client
        ),
    )

    def build_retriever(**kwargs: object) -> object:
        captured.update(retrieval_kwargs=kwargs)
        return retriever

    monkeypatch.setattr(
        dependencies,
        "build_authorized_corpus_retriever",
        build_retriever,
    )

    executor = dependencies.get_artifact_job_executor(config)

    assert executor.retriever is retriever
    assert isinstance(executor.inference, QueryRuntimeArtifactJsonGenerator)
    assert executor.model_name == "reasoning-model"
    assert captured["inference_config"] is rag_config
    assert captured["inference_settings"] is config
    retrieval_kwargs = captured["retrieval_kwargs"]
    assert isinstance(retrieval_kwargs, dict)
    assert retrieval_kwargs == {
        "config": config,
        "rag_config": rag_config,
        "inference": query_client,
    }
    assert executor.inference.generate_json(
        prompt="p",
        model="reasoning-model",
        system="s",
    ) == "{}"
    assert query_client.calls == [
        {"prompt": "p", "model": "reasoning-model", "system": "s"}
    ]


class _QueryClient:
    def __init__(
        self,
        *,
        response: str = "{}",
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, str | None]] = []

    def generate_json(
        self,
        *,
        prompt: str,
        model: str | None,
        system: str,
        **_kwargs: object,
    ) -> str:
        self.calls.append({"prompt": prompt, "model": model, "system": system})
        if self.error is not None:
            raise self.error
        return self.response
