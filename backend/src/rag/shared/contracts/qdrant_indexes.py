"""Qdrant payload index schema shared by ingestion and query runtimes."""

from __future__ import annotations

PAYLOAD_INDEXES: tuple[tuple[str, str], ...] = (
    ("doc_id", "keyword"),
    ("chunk_id", "keyword"),
    ("group_path", "keyword"),
    ("acl_group_paths", "keyword"),
    ("clearance_level", "keyword"),
    ("clearance_rank", "integer"),
    ("is_current", "bool"),
    ("source_deleted", "bool"),
    ("retrieval_status", "keyword"),
    ("doc_type", "keyword"),
    ("effective_date", "datetime"),
    ("expiry_date", "datetime"),
    ("is_expired", "bool"),
    ("language", "keyword"),
    ("topics", "keyword"),
    ("metadata_terms", "keyword"),
    ("claim_ids", "keyword"),
    ("has_conflict", "bool"),
    ("chunk_type", "keyword"),
    ("table_title", "keyword"),
    ("structured_kind", "keyword"),
    ("structured_field_names", "keyword"),
)
