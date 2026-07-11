"""Metadata extraction package."""

from .extraction import build_metadata_bundle
from .models import CrossReference, DocumentMetadataBundle, NamedEntity
from .two_stage import METADATA_VERSION, generate_metadata_v2

__all__ = ["CrossReference", "DocumentMetadataBundle", "METADATA_VERSION", "NamedEntity", "build_metadata_bundle", "generate_metadata_v2"]
