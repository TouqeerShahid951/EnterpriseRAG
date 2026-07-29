"""Capture and validate reproducibility pins for evaluation runs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
from typing import Any

from rag.auth.abac import normalize_group_path
from rag.auth.context import UserContext
from rag.auth.document_access import can_read_document
from rag.core.config import Settings
from rag.documents.models import DocumentRecord, DocumentRepository
from rag.evaluations.answer_verifier import ANSWER_VERIFIER_VERSION
from rag.query.prompt_policy import QUERY_PROMPT_POLICY_VERSION


RUNTIME_PINS_KEY = "_runtime_pins"
PROMPT_POLICY_VERSION = (
    f"{QUERY_PROMPT_POLICY_VERSION}+answer-verifier-{ANSWER_VERIFIER_VERSION}"
)

_QUERY_SETTING_FIELDS = (
    "connector_include_stale_in_retrieval",
    "connector_live_sql_enabled",
    "connector_live_sql_max_repair_attempts",
    "connector_live_sql_max_rows",
    "connector_live_sql_max_scopes",
    "connector_live_sql_result_verifier_enabled",
    "connector_live_sql_timeout_seconds",
    "connector_live_sql_verifier_sample_rows",
    "evaluation_answer_llm_verifier_enabled",
    "evaluation_answer_llm_verifier_model",
    "graphrag_community_collection",
    "graphrag_enabled",
    "qdrant_collection",
    "qdrant_url",
    "rag_dense_cache_dir",
    "rag_faithfulness_policy",
    "rag_http_timeout_seconds",
    "rag_hybrid_disagreement_detector_enabled",
    "rag_query_rewrite_llm_enabled",
    "rag_reranker_cache_dir",
    "rag_reranker_device",
    "rag_reranker_max_candidates",
    "rag_retrieval_max_retries",
    "rag_sparse_cache_dir",
    "rag_sparse_model",
    "rag_top_k",
)
_RETIRED_QUERY_SETTING_FIELDS = frozenset(
    {"artifact_pipeline_version", "rag_faithfulness_threshold"}
)


class EvaluationRuntimePinError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def capture_runtime_pins(
    *,
    config: Settings,
    rag_config_snapshot: Mapping[str, Any],
    document_repo: DocumentRepository,
    user: UserContext,
    group_path: str | None,
    document_ids: Sequence[str],
) -> dict[str, Any]:
    query_settings = {
        field: getattr(config, field) for field in _QUERY_SETTING_FIELDS
    }
    stable_rag_config = _stable_rag_config(rag_config_snapshot)
    models = _model_identifiers(stable_rag_config, query_settings)
    documents = _active_documents(
        document_repo,
        user=user,
        group_path=group_path,
        document_ids=document_ids,
    )
    content_hash, document_count = _content_hash(documents)
    return {
        "rag_config_hash": _digest(stable_rag_config),
        "query_settings": query_settings,
        "query_settings_hash": _digest(query_settings),
        "model_identifiers": models,
        "model_identifiers_hash": _digest(models),
        "prompt_policy_version": PROMPT_POLICY_VERSION,
        "image_digest": _optional_text(config.application_image_digest),
        "active_generation": _generation_hash(documents),
        "active_document_content_hash": content_hash,
        "active_document_count": document_count,
        "host_profile": _optional_text(config.evaluation_host_profile),
    }


def resolve_pinned_runtime(
    snapshot: Mapping[str, Any],
    *,
    current_config: Settings,
    document_repo: DocumentRepository,
    user: UserContext,
    group_path: str | None,
    document_ids: Sequence[str],
) -> tuple[dict[str, Any], Settings]:
    rag_config = dict(snapshot)
    raw_pins = rag_config.pop(RUNTIME_PINS_KEY, None)
    if raw_pins is None:  # Existing runs remain executable but cannot pass the gate.
        return rag_config, current_config
    if not isinstance(raw_pins, Mapping):
        raise _invalid_pins()
    pins = dict(raw_pins)
    query_settings = pins.get("query_settings")
    models = pins.get("model_identifiers")
    normalized_query_settings = (
        _normalize_query_settings(query_settings)
        if isinstance(query_settings, Mapping)
        else None
    )
    if (
        normalized_query_settings is None
        or pins.get("query_settings_hash") != _digest(query_settings)
        or pins.get("rag_config_hash") != _digest(_stable_rag_config(rag_config))
        or not isinstance(models, Mapping)
        or pins.get("model_identifiers_hash") != _digest(models)
        or dict(models)
        != _model_identifiers(
            _stable_rag_config(rag_config), normalized_query_settings
        )
    ):
        raise _invalid_pins()

    for key, current in (
        ("prompt_policy_version", PROMPT_POLICY_VERSION),
        ("image_digest", _optional_text(current_config.application_image_digest)),
        ("host_profile", _optional_text(current_config.evaluation_host_profile)),
    ):
        frozen = pins.get(key)
        if frozen is not None and frozen != current:
            raise EvaluationRuntimePinError(
                "evaluation_runtime_pin_drift",
                "Evaluation runtime no longer matches the submitted run.",
            )

    documents = _active_documents(
        document_repo,
        user=user,
        group_path=group_path,
        document_ids=document_ids,
    )
    content_hash, _ = _content_hash(documents)
    frozen_content_hash = pins.get("active_document_content_hash")
    if frozen_content_hash is not None and frozen_content_hash != content_hash:
        raise EvaluationRuntimePinError(
            "evaluation_runtime_pin_drift",
            "Evaluation document content changed after the run was submitted.",
        )
    frozen_generation = pins.get("active_generation")
    if frozen_generation is not None and frozen_generation != _generation_hash(documents):
        raise EvaluationRuntimePinError(
            "evaluation_runtime_pin_drift",
            "Evaluation index generation changed after the run was submitted.",
        )

    try:
        frozen_config = type(current_config).model_validate(
            {**current_config.model_dump(), **normalized_query_settings}
        )
    except Exception as exc:  # noqa: BLE001 - persisted snapshots are a trust boundary
        raise _invalid_pins() from exc
    return rag_config, frozen_config


def runtime_pins_from_snapshot(snapshot: object) -> dict[str, Any]:
    if not isinstance(snapshot, Mapping):
        return {}
    pins = snapshot.get(RUNTIME_PINS_KEY)
    return dict(pins) if isinstance(pins, Mapping) else {}


def _normalize_query_settings(
    query_settings: Mapping[str, Any],
) -> dict[str, Any] | None:
    fields = frozenset(query_settings)
    current_fields = set(_QUERY_SETTING_FIELDS)
    if not current_fields <= fields or not fields <= (
        current_fields | _RETIRED_QUERY_SETTING_FIELDS
    ):
        return None
    return {field: query_settings[field] for field in _QUERY_SETTING_FIELDS}


def _model_identifiers(
    rag_config: Mapping[str, Any], query_settings: Mapping[str, Any]
) -> dict[str, Any]:
    chat = rag_config.get("chat_model")
    reasoning = rag_config.get("reasoning_model") or rag_config.get("routing_model")
    return {
        "chat": chat,
        "embedding": rag_config.get("embed_model"),
        "reasoning": reasoning or chat,
        "routing": rag_config.get("routing_model") or reasoning or chat,
        "faithfulness": rag_config.get("faithfulness_model") or chat,
        "reranker": rag_config.get("reranker_model"),
        "sparse": query_settings.get("rag_sparse_model"),
        "answer_verifier": (
            query_settings.get("evaluation_answer_llm_verifier_model")
            or reasoning
            or chat
        ),
    }


def _active_documents(
    repository: DocumentRepository,
    *,
    user: UserContext,
    group_path: str | None,
    document_ids: Sequence[str],
) -> list[DocumentRecord]:
    selected = set(document_ids)
    scope = normalize_group_path(group_path) if group_path else None
    documents: list[DocumentRecord] = []
    for document in repository.list_documents(state="active"):
        if not document.is_current or not can_read_document(user, document):
            continue
        if selected and document.id not in selected:
            continue
        if scope and scope not in {
            normalize_group_path(path) for path in document.access_group_paths
        }:
            continue
        documents.append(document)
    return documents


def _content_hash(documents: Sequence[DocumentRecord]) -> tuple[str | None, int]:
    identities: list[tuple[str, str]] = []
    for document in documents:
        if not document.content_hash:
            return None, 0
        identities.append((document.id, document.content_hash))
    identities.sort()
    return _digest(identities), len(identities)


def _generation_hash(documents: Sequence[DocumentRecord]) -> str:
    identities: list[tuple[str, str]] = []
    for document in documents:
        identities.append(
            (document.id, document.active_index_generation_id or "legacy")
        )
    identities.sort()
    return _digest(identities)


def _stable_rag_config(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    stable = dict(snapshot)
    stable.pop(RUNTIME_PINS_KEY, None)
    stable.pop("health", None)
    return stable


def _digest(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _invalid_pins() -> EvaluationRuntimePinError:
    return EvaluationRuntimePinError(
        "evaluation_runtime_pins_invalid",
        "Evaluation run runtime pins are invalid.",
    )
