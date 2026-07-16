"""Execution engine for durable RAG evaluation runs."""

from __future__ import annotations

from collections.abc import Callable
import logging

from ..auth.context import UserContext
from ..core.config import Settings, settings
from rag.query.retrieval.retrieval_trace import RetrievalTrace
from ..query.configuration.mapping import rag_config_from_snapshot
from ..query.configuration.models import RagConfigRecord
from ..query.service import LocalRagService
from ..documents.repository import get_document_repository
from ..documents.models import DocumentRepository
from rag.evaluations.schemas import EvaluationCase
from ..query.schemas import QueryRequest, RAGResponse
from ..shared.evaluation.answer_checks import LiteralCheckResult
from .answer_verifier import verify_answer_content_with_llm
from .case_execution.diagnostics import build_diagnostic
from .models import (
    EvaluationCaseResultPayload,
    EvaluationRunRecord,
)
from .runtime_pins import EvaluationRuntimePinError, resolve_pinned_runtime
from .scoring import score_case_result


logger = logging.getLogger(__name__)
_INVALID_SNAPSHOT_CODE = "evaluation_rag_config_snapshot_invalid"
_INVALID_SNAPSHOT_MESSAGE = "Evaluation run RAG configuration snapshot is invalid."


class EvaluationCaseExecutor:
    def __init__(
        self,
        *,
        document_repo_factory: Callable[[], DocumentRepository],
        rag_service_factory: Callable[[RagConfigRecord, Settings], LocalRagService],
        config: Settings = settings,
        interrupt_error_types: tuple[type[Exception], ...] = (),
    ) -> None:
        self.document_repo_factory = document_repo_factory
        self.rag_service_factory = rag_service_factory
        self.config = config
        self.interrupt_error_types = interrupt_error_types

    def execute_case(
        self,
        run: EvaluationRunRecord,
        case: EvaluationCase,
    ) -> EvaluationCaseResultPayload:
        """Run and score one case without mutating evaluation persistence."""
        document_repo = self.document_repo_factory()
        user = _user_context(run)
        try:
            rag_config_snapshot, frozen_config = resolve_pinned_runtime(
                run.rag_config_snapshot,
                current_config=self.config,
                document_repo=document_repo,
                user=user,
                group_path=run.group_path,
                document_ids=run.document_ids,
            )
        except EvaluationRuntimePinError as exc:
            logger.warning(
                "evaluation runtime pin rejected run_id=%s case_id=%s code=%s",
                run.id,
                case.id,
                exc.code,
            )
            return _runtime_error_payload(case.question, exc.code, exc.message)
        try:
            snapshot_config = rag_config_from_snapshot(rag_config_snapshot)
        except Exception as exc:  # noqa: BLE001 - invalid snapshots fail closed
            logger.warning(
                "evaluation RAG config snapshot invalid run_id=%s case_id=%s error_type=%s",
                run.id,
                case.id,
                type(exc).__name__,
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            return _invalid_snapshot_payload(case.question)
        service = self.rag_service_factory(snapshot_config, frozen_config)
        answer_content_judge = self._answer_content_judge(
            service, config=frozen_config
        )
        response: RAGResponse | None = None
        error_message: str | None = None
        retrieval_trace = RetrievalTrace()
        try:
            execution = service.execute_query(
                QueryRequest(
                    query=case.question,
                    group_path=run.group_path,
                    document_ids=list(run.document_ids),
                ),
                user,
                capture_retrieval_trace=True,
                force_faithfulness_check=(
                    case.must_cite_source or case.min_faithfulness_score > 0
                ),
            )
            response = execution.response
            retrieval_trace = execution.retrieval_trace
        except Exception as exc:  # noqa: BLE001 - runtime failures are case results
            if isinstance(exc, self.interrupt_error_types):
                raise
            error_type = type(exc).__name__
            logger.warning(
                "evaluation case query failed run_id=%s case_id=%s error_type=%s",
                run.id,
                case.id,
                error_type,
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            error_message = f"Evaluation query execution failed ({error_type})."
        diagnostic = build_diagnostic(
            case,
            trace=retrieval_trace,
            document_repo=document_repo,
            reranker_model=getattr(
                getattr(service, "rag_config", None), "reranker_model", None
            ),
        )
        scored = score_case_result(
            case,
            response=response,
            diagnostic=diagnostic,
            error_message=error_message,
            answer_content_judge=answer_content_judge,
            interrupt_error_types=self.interrupt_error_types,
        )
        return EvaluationCaseResultPayload(
            question=case.question,
            status="error" if error_message else "ok",
            passed=bool(scored["passed"]),
            primary_failure_stage=(
                str(scored["primary_failure_stage"])
                if scored["primary_failure_stage"]
                else None
            ),
            failure_stages=tuple(str(item) for item in scored["failure_stages"]),
            checks_json=dict(scored["checks"]),
            answer=response.answer if response else "",
            sources_json=(
                tuple(source.model_dump(mode="json") for source in response.sources)
                if response
                else ()
            ),
            diagnostic_json=diagnostic,
            trace_id=response.trace_id if response else None,
            node_timings_json=(
                tuple(
                    timing.model_dump(mode="json") for timing in response.node_timings
                )
                if response
                else ()
            ),
            faithfulness_score=response.faithfulness_score if response else None,
            faithfulness_status=response.faithfulness_status if response else None,
            unfounded_claims=(tuple(response.unfounded_claims) if response else ()),
            degraded=response.degraded if response else False,
            degraded_reason=response.degraded_reason if response else None,
            latency_ms=response.latency_ms if response else 0,
            error_message_safe=error_message[:500] if error_message else None,
        )

    def _diagnostic(
        self,
        case: EvaluationCase,
        *,
        trace: RetrievalTrace,
        document_repo: DocumentRepository,
        reranker_model: str | None,
    ) -> dict[str, object]:
        """Compatibility delegate for callers that exercised diagnostics directly."""
        return build_diagnostic(
            case,
            trace=trace,
            document_repo=document_repo,
            reranker_model=reranker_model,
        )

    def _answer_content_judge(self, service: LocalRagService, *, config: Settings):
        if not config.evaluation_answer_llm_verifier_enabled:
            return None
        llm = service.ollama
        if getattr(llm, "generate_json", None) is None:
            return None
        model = (
            config.evaluation_answer_llm_verifier_model
            or service.rag_config.effective_reasoning_model
            or service.rag_config.chat_model
        )

        def judge(
            case: EvaluationCase, response: RAGResponse, literal: LiteralCheckResult
        ) -> dict[str, object]:
            return verify_answer_content_with_llm(
                llm,
                case=case,
                response=response,
                literal=literal,
                model=model,
                interrupt_error_types=self.interrupt_error_types,
            )

        return judge


def _user_context(run: EvaluationRunRecord) -> UserContext:
    return UserContext(
        user_id=run.user_id,
        email=run.user_email,
        account_type=run.account_type,
        group_paths=run.group_paths,
        clearance_level=run.clearance_level,
        permission_version=run.permission_version,
    )


def _invalid_snapshot_payload(question: str) -> EvaluationCaseResultPayload:
    return _runtime_error_payload(
        question,
        _INVALID_SNAPSHOT_CODE,
        _INVALID_SNAPSHOT_MESSAGE,
    )


def _runtime_error_payload(
    question: str, code: str, message: str
) -> EvaluationCaseResultPayload:
    error = {
        "passed": False,
        "code": code,
        "error": message,
    }
    return EvaluationCaseResultPayload(
        question=question,
        status="error",
        passed=False,
        primary_failure_stage="runtime",
        failure_stages=("runtime",),
        checks_json={"runtime": error},
        answer="",
        sources_json=(),
        diagnostic_json={
            "status": "error",
            "error_code": code,
            "error": message,
        },
        trace_id=None,
        node_timings_json=(),
        faithfulness_score=None,
        faithfulness_status=None,
        unfounded_claims=(),
        degraded=False,
        degraded_reason=None,
        latency_ms=0,
        error_message_safe=message,
    )


def default_evaluation_case_executor(
    config: Settings | None = None,
    *,
    interrupt_error_types: tuple[type[Exception], ...] = (),
) -> EvaluationCaseExecutor:
    runtime_config = config or settings

    def service_from_snapshot(
        rag_config: RagConfigRecord, frozen_config: Settings
    ) -> LocalRagService:
        return LocalRagService(config=frozen_config, rag_config=rag_config)

    return EvaluationCaseExecutor(
        document_repo_factory=get_document_repository,
        rag_service_factory=service_from_snapshot,
        config=runtime_config,
        interrupt_error_types=interrupt_error_types,
    )
