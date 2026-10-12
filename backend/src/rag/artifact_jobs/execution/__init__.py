"""Artifact execution API."""

from .errors import (
    ArtifactEvidenceUnavailable,
    ArtifactCitationVerificationFailed,
    ArtifactJobCancelled,
    ArtifactJobLeaseLost,
    ArtifactPermissionChanged,
)
__all__ = [
    "ArtifactEvidenceUnavailable",
    "ArtifactCitationVerificationFailed",
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
