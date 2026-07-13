"""Shared artifact-generation value types."""

from typing import Literal


ArtifactFormat = Literal["docx", "pptx", "pdf"]
ArtifactJobProgressUnit = Literal["sections", "batches", "slides", "formats", "files"]
ArtifactJobStatus = Literal[
    "queued",
    "planning",
    "needs_input",
    "retrieving",
    "composing",
    "validating",
    "rendering",
    "complete",
    "partial",
    "failed",
    "cancelled",
]
