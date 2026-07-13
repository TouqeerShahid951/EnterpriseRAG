"""Execution engine for durable RAG evaluation runs."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import re
from typing import Any

from ..auth.abac import build_abac_filter
from ..auth.context import UserContext
from ..core.config import Settings, settings
from ..query.qdrant import SearchHit
from ..query.query_retrieval import add_document_scope, add_expiry_scope
from ..query.reranker import rerank_hits
from ..query.service import LocalRagService
from ..query.sparse import embed_sparse_text
from ..documents.repository import get_document_repository
from ..documents.models import DocumentRepository
from ..schemas.evaluations import EvaluationCase
from ..query.schemas import QueryRequest, RAGResponse
from ..shared.evaluation.answer_checks import LiteralCheckResult
from .answer_verifier import verify_answer_content_with_llm
from .models import EvaluationRepository, EvaluationRunRecord
from .scoring import score_case_result, summarize_results


class EvaluationRunCancelled(RuntimeError):
    pass


class EvaluationRunExecutor:
    def __init__(
        self,
        *,
        repo_factory: Callable[[], EvaluationRepository],
        document_repo_factory: Callable[[], DocumentRepository],
        rag_service_factory: Callable[[], LocalRagService],
        config: Settings = settings,
        interrupt_error_types: tuple[type[Exception], ...] = (),
    ) -> None:
        self.repo_factory = repo_factory
        self.document_repo_factory = document_repo_factory
        self.rag_service_factory = rag_service_factory
        self.config = config
        self.interrupt_error_types = interrupt_error_types

    def execute(self, run_id: str) -> EvaluationRunRecord:
        repo = self.repo_factory()
        run, started = repo.start_attempt(run_id)
        if run is None:
            raise RuntimeError("evaluation run was not found")
        if not started:
            return run
        repo.clear_case_results(run.id)
        dataset = repo.get_dataset(run.dataset_id)
        if dataset is None:
            return self._fail(run.id, code="evaluation_dataset_not_found", message="Evaluation dataset was not found.")
        cases = _selected_cases(list(dataset.cases), run.selected_case_ids)
        if not cases:
            return self._fail(run.id, code="evaluation_run_empty", message="Evaluation run did not contain any cases.")

        service = self.rag_service_factory()
        document_repo = self.document_repo_factory()
        user = _user_context(run)
        answer_content_judge = self._answer_content_judge(service)
        summary_rows: list[dict[str, Any]] = []
        passed_count = 0
        failed_count = 0
        for index, case in enumerate(cases):
            self._raise_if_cancelled(run.id)
            repo.heartbeat(run.id)
            diagnostic = self._diagnostic(case, run=run, user=user, service=service, document_repo=document_repo)
            response: RAGResponse | None = None
            error_message: str | None = None
            try:
                response = service.answer_query(
                    QueryRequest(query=case.question, group_path=run.group_path, document_ids=list(run.document_ids)),
                    user,
                )
            except Exception as exc:  # noqa: BLE001 - evaluation records per-case runtime failures
                if isinstance(exc, self.interrupt_error_types):
                    raise
                error_message = f"{type(exc).__name__}: {exc}"
            scored = score_case_result(
                case,
                response=response,
                diagnostic=diagnostic,
                error_message=error_message,
                answer_content_judge=answer_content_judge,
                interrupt_error_types=self.interrupt_error_types,
            )
            latency_ms = response.latency_ms if response else 0
            status = "error" if error_message else "ok"
            repo.add_case_result(
                run_id=run.id,
                case_id=case.id,
                case_index=index,
                question=case.question,
                status=status,
                passed=scored["passed"],
                primary_failure_stage=scored["primary_failure_stage"],
                failure_stages=scored["failure_stages"],
                checks_json=scored["checks"],
                answer=response.answer if response else "",
                sources_json=[source.model_dump(mode="json") for source in response.sources] if response else [],
                diagnostic_json=diagnostic,
                trace_id=response.trace_id if response else None,
                node_timings_json=[timing.model_dump(mode="json") for timing in response.node_timings] if response else [],
                faithfulness_score=response.faithfulness_score if response else None,
                faithfulness_status=response.faithfulness_status if response else None,
                unfounded_claims=response.unfounded_claims if response else [],
                degraded=response.degraded if response else False,
                degraded_reason=response.degraded_reason if response else None,
                latency_ms=latency_ms,
                error_message_safe=error_message[:500] if error_message else None,
            )
            passed_count += 1 if scored["passed"] else 0
            failed_count += 0 if scored["passed"] else 1
            completed = index + 1
            summary_rows.append(
                {
                    "passed": scored["passed"],
                    "primary_failure_stage": scored["primary_failure_stage"],
                    "checks": scored["checks"],
                    "latency_ms": latency_ms,
                }
            )
            repo.update_run(run.id, {
                "stage": f"case {completed} of {len(cases)}",
                "progress_pct": int(completed / len(cases) * 100),
                "completed_count": completed,
                "passed_count": passed_count,
                "failed_count": failed_count,
            })

        summary = summarize_results(summary_rows)
        return repo.update_run(run.id, {
            "status": "complete",
            "stage": "complete",
            "progress_pct": 100,
            "summary_json": summary,
            "completed_at": datetime.now(UTC),
        }) or run

    def _diagnostic(
        self,
        case: EvaluationCase,
        *,
        run: EvaluationRunRecord,
        user: UserContext,
        service: LocalRagService,
        document_repo: DocumentRepository,
    ) -> dict[str, Any]:
        indexed_titles, missing_titles = _indexed_expected_docs(case, document_repo=document_repo)
        diagnostic: dict[str, Any] = {
            "top_k": self.config.evaluation_diagnostic_top_k,
            "indexed_source_docs": indexed_titles,
            "missing_indexed_source_docs": missing_titles,
            "expected_docs_indexed": not missing_titles,
        }
        try:
            dense = service.ollama.embed(case.question)
            service.qdrant.prepare_for_query(len(dense))
            sparse = embed_sparse_text(
                case.question,
                model_name=self.config.rag_sparse_model,
                cache_dir=self.config.rag_sparse_cache_dir,
            )
            scoped_user = _diagnostic_user_context(user, run.group_path)
            qdrant_filter = add_expiry_scope(build_abac_filter(scoped_user, is_current_only=True))
            qdrant_filter = add_document_scope(qdrant_filter, list(run.document_ids))
            hits = service.qdrant.hybrid_search(
                dense_vector=dense,
                sparse_vector=sparse.as_qdrant(),
                limit=self.config.evaluation_diagnostic_top_k,
                qdrant_filter=qdrant_filter,
            )
            rows = _candidate_rows(hits)
            rerank_top_k = min(self.config.rag_top_k, self.config.evaluation_diagnostic_top_k)
            reranked_hits = rerank_hits(
                case.question,
                hits,
                top_k=rerank_top_k,
                max_candidates=self.config.rag_reranker_max_candidates,
                model_name=service.rag_config.reranker_model,
                cache_dir=self.config.rag_reranker_cache_dir,
            )
            reranked_rows = _candidate_rows(reranked_hits)
            retrieved_titles = [str(row.get("doc_title") or "") for row in rows]
            reranked_titles = [str(row.get("doc_title") or "") for row in reranked_rows]
            retrieved_pages = sorted(
                {
                    int(row["page"])
                    for row in rows
                    if isinstance(row.get("page"), int) or str(row.get("page") or "").isdigit()
                }
            )
            diagnostic.update(
                {
                    "status": "ok",
                    "retrieved_source_docs": retrieved_titles,
                    "reranked_source_docs": reranked_titles,
                    "retrieved_pages": retrieved_pages,
                    "retrieval_candidates": rows,
                    "hits": rows,
                    "reranked_candidates": reranked_rows,
                    "reranker_model": service.rag_config.reranker_model,
                    "reranker_top_k": rerank_top_k,
                    "reranker_max_candidates": self.config.rag_reranker_max_candidates,
                    "expected_docs_retrieved": _expected_docs_retrieved(case.expected_source_docs, retrieved_titles),
                    "expected_pages_retrieved": _expected_pages_retrieved(case.acceptable_source_pages, retrieved_pages),
                }
            )
        except Exception as exc:  # noqa: BLE001 - diagnostic errors should not hide generation results
            if isinstance(exc, self.interrupt_error_types):
                raise
            diagnostic.update(
                {
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "retrieved_source_docs": [],
                    "reranked_source_docs": [],
                    "retrieved_pages": [],
                    "retrieval_candidates": [],
                    "hits": [],
                    "reranked_candidates": [],
                    "expected_docs_retrieved": not case.expected_source_docs,
                    "expected_pages_retrieved": not case.acceptable_source_pages,
                }
            )
        return diagnostic

    def _raise_if_cancelled(self, run_id: str) -> None:
        run = self.repo_factory().get_run(run_id)
        if run is None or run.cancellation_requested or run.status == "cancelled":
            raise EvaluationRunCancelled("evaluation run was cancelled")

    def _answer_content_judge(self, service: LocalRagService):
        if not self.config.evaluation_answer_llm_verifier_enabled:
            return None
        llm = service.ollama
        if getattr(llm, "generate_json", None) is None:
            return None
        model = (
            self.config.evaluation_answer_llm_verifier_model
            or service.rag_config.effective_reasoning_model
            or service.rag_config.chat_model
        )

        def judge(case: EvaluationCase, response: RAGResponse, literal: LiteralCheckResult) -> dict[str, object]:
            return verify_answer_content_with_llm(
                llm,
                case=case,
                response=response,
                literal=literal,
                model=model,
                interrupt_error_types=self.interrupt_error_types,
            )

        return judge

    def _fail(self, run_id: str, *, code: str, message: str) -> EvaluationRunRecord:
        run = self.repo_factory().update_run(run_id, {
            "status": "failed",
            "stage": "failed",
            "progress_pct": 100,
            "error_code": code,
            "error_message_safe": message,
            "completed_at": datetime.now(UTC),
        })
        if run is None:
            raise RuntimeError(message)
        return run


def _selected_cases(cases: list[EvaluationCase], selected_case_ids: tuple[str, ...]) -> list[EvaluationCase]:
    if not selected_case_ids:
        return cases
    allowed = set(selected_case_ids)
    return [case for case in cases if case.id in allowed]


def _user_context(run: EvaluationRunRecord) -> UserContext:
    return UserContext(
        user_id=run.user_id,
        email=run.user_email,
        account_type=run.account_type,
        group_paths=run.group_paths,
        clearance_level=run.clearance_level,
        permission_version=run.permission_version,
    )


def _diagnostic_user_context(user: UserContext, group_path: str | None) -> UserContext:
    if not group_path:
        return user
    return UserContext(
        user_id=user.user_id,
        email=user.email,
        account_type=user.account_type,
        group_paths=(group_path,),
        clearance_level=user.clearance_level,
        permission_version=user.permission_version,
    )


def _candidate_rows(hits: list[SearchHit]) -> list[dict[str, Any]]:
    return [_candidate_row(hit, rank=index + 1) for index, hit in enumerate(hits)]


def _candidate_row(hit: SearchHit, *, rank: int) -> dict[str, Any]:
    payload = hit.payload
    row = {
        "rank": rank,
        "score": hit.score,
        "retrieval_score": hit.score,
        "doc_title": _optional_str(payload.get("doc_title")),
        "doc_id": _optional_str(payload.get("doc_id")),
        "chunk_id": _optional_str(payload.get("chunk_id")) or hit.point_id,
        "page": _optional_int(payload.get("page")),
        "page_start": _optional_int(payload.get("page_start")),
        "page_end": _optional_int(payload.get("page_end")),
        "group_path": _optional_str(payload.get("group_path")),
        "chunk_type": _optional_str(payload.get("chunk_type")),
        "structured_origin": _optional_str(payload.get("structured_origin")),
        "rerank_score": _optional_float(payload.get("_rerank_score")),
        "rerank_adjusted_score": _optional_float(payload.get("_rerank_adjusted_score")),
        "rerank_status": _optional_str(payload.get("_rerank_status")),
        "rerank_error": _optional_str(payload.get("_rerank_error")),
        "low_value_penalty": _optional_float(payload.get("_low_value_penalty")),
        "low_value_reasons": _optional_str_list(payload.get("_low_value_reasons")),
    }
    return {key: value for key, value in row.items() if value is not None}


def _indexed_expected_docs(
    case: EvaluationCase,
    *,
    document_repo: DocumentRepository,
) -> tuple[list[str], list[str]]:
    if not case.expected_source_docs:
        return [], []
    documents = document_repo.list_documents(state="active")
    titles = [str(document.title or "") for document in documents if document.is_current and document.ingest_status == "complete"]
    normalized_titles = {_normalize_title(title): title for title in titles}
    found: list[str] = []
    missing: list[str] = []
    for expected in case.expected_source_docs:
        normalized = _normalize_title(expected)
        if normalized in normalized_titles:
            found.append(normalized_titles[normalized])
        else:
            missing.append(expected)
    return found, missing


def _expected_docs_retrieved(expected_docs: list[str], actual_titles: list[str]) -> bool:
    if not expected_docs:
        return True
    actual = {_normalize_title(title) for title in actual_titles}
    return {_normalize_title(title) for title in expected_docs}.issubset(actual)


def _expected_pages_retrieved(expected_pages: list[int], actual_pages: list[int]) -> bool:
    if not expected_pages:
        return True
    return bool(set(expected_pages).intersection(actual_pages))


def _normalize_title(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _optional_str_list(value: object) -> list[str] | None:
    if not isinstance(value, list):
        return None
    return [str(item) for item in value if str(item).strip()]


def default_evaluation_run_executor(
    config: Settings | None = None,
    *,
    interrupt_error_types: tuple[type[Exception], ...] = (),
) -> EvaluationRunExecutor:
    from .repository import get_evaluation_repository

    return EvaluationRunExecutor(
        repo_factory=get_evaluation_repository,
        document_repo_factory=get_document_repository,
        rag_service_factory=LocalRagService,
        config=config or settings,
        interrupt_error_types=interrupt_error_types,
    )
