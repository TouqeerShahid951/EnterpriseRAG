"""Helpers for interpreting Ollama model names."""

from __future__ import annotations


def is_ollama_cloud_model(model: str) -> bool:
    """Return whether the model's explicit tag selects Ollama Cloud inference."""
    normalized = model.strip().lower()
    _name, separator, tag = normalized.rpartition(":")
    return bool(separator) and (tag == "cloud" or tag.endswith("-cloud"))
