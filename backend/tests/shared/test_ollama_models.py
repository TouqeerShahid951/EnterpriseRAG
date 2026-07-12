from __future__ import annotations

import pytest

from rag.shared.ollama_models import is_ollama_cloud_model


@pytest.mark.parametrize(
    "model",
    (
        "nemotron-3-super:cloud",
        "gpt-oss:120b-cloud",
        "gemma4:31b-cloud",
        " namespace/model:7b-cloud ",
    ),
)
def test_cloud_model_tags_are_detected(model: str) -> None:
    assert is_ollama_cloud_model(model)


@pytest.mark.parametrize(
    "model",
    (
        "llama3.1:8b",
        "qwen3.5:cloud-preview",
        "cloud-model:latest",
        "cloud",
        "",
    ),
)
def test_local_or_ambiguous_model_tags_are_not_cloud(model: str) -> None:
    assert not is_ollama_cloud_model(model)
