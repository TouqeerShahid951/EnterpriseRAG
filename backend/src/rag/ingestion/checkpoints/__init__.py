"""Durable, fenced artifacts used to resume ingestion work."""

from .models import CheckpointDescriptor
from .service import CheckpointService

__all__ = ["CheckpointDescriptor", "CheckpointService"]
