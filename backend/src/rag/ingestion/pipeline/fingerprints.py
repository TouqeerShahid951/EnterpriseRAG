"""Semantic stage fingerprints, excluding credentials and execution tuning."""
from __future__ import annotations

import hashlib
import json
from typing import Any

# Bump when parser, metadata prompts, chunking or embedding preprocessing changes.
PIPELINE_OUTPUT_VERSION = 2
PARSER_SETTINGS = (
    'min_chars_per_page', 'ingestion_quality_preset', 'weak_page_threshold',
    'full_doc_weak_page_ratio', 'layered_docling_max_pages',
    'layered_docling_max_page_ratio', 'prefer_full_document_docling',
    'layered_docling_batch_pages', 'pdf_image_analysis_max_images',
    'pdf_image_analysis_max_full_page_fallbacks', 'pdf_image_review_threshold',
    'scanned_visual_region_enabled', 'scanned_visual_min_area_ratio',
    'scanned_visual_max_regions_per_page', 'scanned_visual_text_mask_padding_px',
    'ocr_review_confidence_threshold', 'vision_layout_repair_enabled',
)


def model_identity(client: Any, role: str) -> dict[str, Any]:
    if role in {'language', 'embedding'}:
        client = getattr(client, f'{role}_client', client)
    fields = {
        'language': ('chat_model', 'base_url', 'num_ctx', 'thinking_enabled'),
        'embedding': ('embed_model', 'model_name', 'embedding_base_url', 'base_url'),
        'vision': ('model', 'base_url', 'num_ctx', 'provider'),
        'sparse': ('model_name',),
    }[role]
    return {
        'adapter': f'{type(client).__module__}.{type(client).__qualname__}',
        **{name: getattr(client, name, None) for name in fields},
        'revision': getattr(client, 'model_revision', None),
    }


def configuration_digest(deps: Any, stage: str = 'prepared') -> str:
    payload: dict[str, Any] = {
        'version': PIPELINE_OUTPUT_VERSION,
        'parser': {name: getattr(deps, name, None) for name in PARSER_SETTINGS},
        'vision': model_identity(getattr(deps, 'vision', None), 'vision'),
    }
    if stage != 'parsed':
        payload['metadata'] = {
            'model': model_identity(getattr(deps, 'ollama', None), 'language'),
            'gliner': getattr(deps, 'metadata_use_gliner', False),
            'taxonomy': list(getattr(deps, 'topic_taxonomy', ())),
        }
    if stage not in {'parsed', 'metadata'}:
        payload['chunking'] = {name: getattr(deps, name, None) for name in (
            'chunk_target_tokens', 'chunk_overlap_tokens', 'parent_max_tokens',
        )}
    if stage in {'dense', 'publication'}:
        payload['dense'] = model_identity(getattr(deps, 'ollama', None), 'embedding')
    if stage in {'sparse', 'publication'}:
        payload['sparse'] = model_identity(getattr(deps, 'sparse_embedder', None), 'sparse')
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
