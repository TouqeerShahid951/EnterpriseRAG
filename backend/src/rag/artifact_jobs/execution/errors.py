"""Lifecycle failures raised while executing durable artifact jobs."""


class ArtifactPermissionChanged(RuntimeError):
    """The requesting user no longer has the permissions captured by the job."""


class ArtifactJobCancelled(RuntimeError):
    """The job was cancelled or expired while an attempt was running."""


class ArtifactJobLeaseLost(RuntimeError):
    """A newer worker attempt reclaimed the job execution lease."""


class ArtifactEvidenceUnavailable(RuntimeError):
    """The authorized corpus did not yield evidence for the requested artifact."""

    code = "artifact_no_evidence"
    stage = "retrieving"
    safe_message = (
        "No authorized evidence was found for this document generation request."
    )


class ArtifactCitationVerificationFailed(ArtifactEvidenceUnavailable):
    """The single citation repair was exhausted; another delivery must not retry it."""

    code = "artifact_citation_verification_failed"
    stage = "validating"
    safe_message = "Supporting citations could not be verified."
