"""Lifecycle failures raised while executing durable artifact jobs."""


class ArtifactPermissionChanged(RuntimeError):
    """The requesting user no longer has the permissions captured by the job."""


class ArtifactJobCancelled(RuntimeError):
    """The job was cancelled or expired while an attempt was running."""


class ArtifactJobLeaseLost(RuntimeError):
    """A newer worker attempt reclaimed the job execution lease."""


class ArtifactEvidenceUnavailable(RuntimeError):
    """The authorized corpus did not yield evidence for the requested artifact."""

    safe_message = (
        "No authorized evidence was found for this document generation request."
    )
