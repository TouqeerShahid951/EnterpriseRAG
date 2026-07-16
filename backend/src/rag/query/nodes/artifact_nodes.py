"""Artifact planning, composition, validation, and generation graph nodes."""

from __future__ import annotations

from ..artifact_composer import artifact_response_summary, compose_artifact_content
from ..artifact_models import ArtifactValidation
from ..artifact_pipeline import plan_artifact_request, validate_artifact_content
from ..cancellation import cancellation_token_from_context
from rag.query.routing.routing_logs import (
    log_artifact_composition,
    log_artifact_plan,
    log_artifact_result,
    log_artifact_validation,
    log_faithfulness_result,
)
from rag.query.sources import sources_from_hits
from ..state import QueryContext
from rag.query.answering.synthesis import build_rag_response
from .node_support import _mark_execution, _raise_if_cancelled


class ArtifactNodes:
    def artifact_planner(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        artifact_request = ctx.get("artifact_request")
        if artifact_request is None or artifact_request.needs_clarification:
            raise RuntimeError("artifact planner requires a complete artifact request")
        plan = plan_artifact_request(artifact_request, document_ids=ctx["request"].document_ids)
        ctx["artifact_plan"] = plan
        _mark_execution(
            ctx,
            "artifact_planner",
            "deterministic",
            f"{plan.artifact_type}:{','.join(plan.operations)}",
        )
        log_artifact_plan(ctx)
        return ctx

    def artifact_composer(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        artifact_plan = ctx.get("artifact_plan")
        artifact_request = ctx.get("artifact_request")
        coverage = ctx.get("artifact_coverage")
        units = ctx.get("artifact_evidence", ())
        if artifact_plan is None or artifact_request is None:
            raise RuntimeError("artifact composer requires an artifact plan")
        if coverage is None or not units:
            ctx["degraded"] = True
            ctx["degraded_reason"] = ctx["degraded_reason"] or "artifact_no_relevant_evidence"
            ctx["response"] = build_rag_response(
                ctx,
                answer="No relevant authorized evidence was found for the requested artifact.",
                sources=[],
            )
            _mark_execution(ctx, "artifact_composer", "deterministic", "no_relevant_evidence")
            return ctx
        content = compose_artifact_content(
            plan=artifact_plan,
            units=units,
            coverage=coverage,
            ollama=self.ollama,
            cancellation_token=cancellation_token_from_context(ctx),
        )
        ctx["artifact_content"] = content
        mode = "deterministic" if artifact_plan.primary_operation in {"enumerate", "extract"} else "ai_assisted"
        _mark_execution(ctx, "artifact_composer", mode, ",".join(artifact_plan.operations))
        log_artifact_composition(ctx)
        ctx["response"] = build_rag_response(
            ctx,
            answer=artifact_response_summary(content, requested_formats=artifact_request.formats),
            sources=sources_from_hits(ctx["retrieved_hits"], query=artifact_plan.objective),
        )
        return ctx

    def artifact_content_validator(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        content = ctx.get("artifact_content")
        plan = ctx.get("artifact_plan")
        if "response" not in ctx:
            raise RuntimeError("artifact content validator requires a response")
        if content is None or plan is None:
            ctx["artifact_validation"] = ArtifactValidation(
                passed=False,
                support_score=0.0,
                errors=("Artifact content was not composed.",),
                warnings=(),
            )
        else:
            ctx["artifact_validation"] = validate_artifact_content(content, plan)
        validation = ctx["artifact_validation"]
        if not validation.passed:
            ctx["degraded"] = True
            ctx["degraded_reason"] = ctx["degraded_reason"] or "artifact_content_validation_failed"
        ctx["faithfulness_score"] = validation.support_score
        ctx["unfounded_claims"] = list(validation.errors)
        ctx["response"] = ctx["response"].model_copy(update={
            "faithfulness_score": validation.support_score,
            "faithfulness_status": "checked" if validation.passed else "failed",
            "unfounded_claims": list(validation.errors),
            "degraded": ctx["degraded"],
            "degraded_reason": ctx["degraded_reason"],
        })
        _mark_execution(
            ctx,
            "artifact_content_validator",
            "deterministic",
            "passed" if validation.passed else ",".join(validation.errors),
        )
        log_artifact_validation(ctx)
        log_faithfulness_result(ctx, failed=not validation.passed)
        return ctx

    def artifact_generator(self, ctx: QueryContext) -> QueryContext:
        _raise_if_cancelled(ctx)
        if "response" not in ctx:
            raise RuntimeError("artifact generator requires a synthesized response")
        artifact_request = ctx.get("artifact_request")
        if artifact_request is None or artifact_request.needs_clarification:
            log_artifact_result(
                ctx,
                requested=artifact_request is not None,
                skipped_reason="needs_clarification" if artifact_request is not None else "not_requested",
            )
            return ctx
        response = ctx["response"]
        if response.degraded and not response.sources:
            log_artifact_result(ctx, requested=True, skipped_reason="degraded_without_sources")
            return ctx
        validation = ctx.get("artifact_validation")
        artifact_content = ctx.get("artifact_content")
        if validation is not None and not validation.passed:
            log_artifact_result(ctx, requested=True, skipped_reason="content_validation_failed")
            ctx["response"] = response.model_copy(update={
                "answer": "Artifact content could not be validated, so no file was created.",
            })
            return ctx
        if artifact_content is None:
            log_artifact_result(ctx, requested=True, skipped_reason="content_missing")
            ctx["response"] = response.model_copy(update={
                "answer": "Artifact content was unavailable, so no file was created.",
            })
            return ctx
        result = self.artifact_service.create_for_response(
            artifact_request=artifact_request,
            response=response,
            artifact_content=artifact_content,
            user=ctx["user"],
            session_id=ctx["session_id"],
            trace_id=ctx["trace_id"],
        )
        degraded = ctx["degraded"]
        degraded_reason = ctx["degraded_reason"]
        if result.failures:
            degraded = True
            degraded_reason = degraded_reason or (
                "artifact_generation_failed" if not result.artifacts else "artifact_generation_partial"
            )
        if not result.artifacts:
            answer = "Artifact generation failed; no requested files were created."
        elif result.failures:
            generated_formats = ", ".join(artifact.format.upper() for artifact in result.artifacts)
            failed_formats = ", ".join(item.upper() for item in result.failures)
            answer = f"Generated {generated_formats}. Failed formats: {failed_formats}."
        else:
            answer = artifact_response_summary(artifact_content, requested_formats=artifact_request.formats)
        ctx["degraded"] = degraded
        ctx["degraded_reason"] = degraded_reason
        ctx["response"] = ctx["response"].model_copy(update={
            "answer": answer,
            "artifacts": result.artifacts,
            "degraded": degraded,
            "degraded_reason": degraded_reason,
        })
        log_artifact_result(
            ctx,
            requested=True,
            artifact_count=len(result.artifacts),
            failure_count=len(result.failures),
            formats=[artifact.format for artifact in result.artifacts],
            failure_details=result.failure_details or (),
        )
        return ctx
