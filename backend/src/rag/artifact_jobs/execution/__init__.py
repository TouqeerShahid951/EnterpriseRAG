"""Artifact execution API."""

from .errors import (
    ArtifactEvidenceUnavailable,
    ArtifactJobCancelled,
    ArtifactJobLeaseLost,
    ArtifactPermissionChanged,
)
__all__ = [
    "ArtifactEvidenceUnavailable",
    "ArtifactJobCancelled",
    "ArtifactJobExecutor",
    "ArtifactJobLeaseLost",
    "ArtifactPermissionChanged",
]


def __getattr__(name: str):
    if name == "ArtifactJobExecutor":
        from .executor import ArtifactJobExecutor

        return ArtifactJobExecutor
    raise AttributeError(name)
