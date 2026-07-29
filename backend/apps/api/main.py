from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from rag.audit import routes as audit_routes
from rag.abbreviations import routes as abbreviation_routes
from rag.auth import routes as auth_routes
from rag.artifact_jobs import routes as artifact_routes
from rag.bootstrap.schema import ensure_postgres_schema
from rag.core.config import settings
from rag.documents import routes as document_routes
from rag.documents.upload import routes as upload_routes
from rag.connectors import routes as connector_routes
from rag.deployment import routes as deployment_routes
from rag.evaluations import routes as evaluation_routes
from rag.graphrag import (
    document_routes as graphrag_document_routes,
    job_routes as graphrag_job_routes,
)
from rag.ingestion import (
    document_routes as ingestion_document_routes,
    job_routes as ingestion_job_routes,
)
from rag.ingestion.configuration import routes as ingest_configuration_routes
from rag.ingestion.folders import routes as folder_schedule_routes
from rag.ingestion.publication import routes as index_publication_routes
from rag.ingestion.review import routes as review_routes
from rag.query import routes as query_routes
from rag.query.configuration import routes as rag_configuration_routes
from rag.query.configuration.repository import effective_rag_config
from rag.query.runtime_warmup import warm_query_fastembed_runtime
from rag.internal import (
    abac_filter_routes,
    artifact_job_routes as internal_artifact_job_routes,
    claim_routes,
    document_supersession_routes,
    ingest_config_routes,
    ingest_status_routes,
    rag_config_routes,
    review_batch_routes,
)
from rag.auth.identity_repository import get_identity_repository
from rag.shared.contracts.http import ErrorDetail, ErrorResponse, HealthResponse
from rag.shared.persistence import close_postgres_pools
from rag.auth.bootstrap import ensure_initial_platform_admin

from apps.api.readiness import probe_readiness


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    ensure_postgres_schema(settings)
    repository_provider = app.dependency_overrides.get(
        get_identity_repository, get_identity_repository
    )
    ensure_initial_platform_admin(
        repository_provider(),
        email=settings.bootstrap_admin_email,
        name=settings.bootstrap_admin_name,
        password=settings.bootstrap_admin_password,
    )
    try:
        warm_query_fastembed_runtime(
            app_settings=settings,
            rag_config=effective_rag_config(config=settings),
        )
        yield
    finally:
        close_postgres_pools()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.api_version,
        description="Local AgenticRAG with authenticated Document ingestion and grounded query.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["content-type", "x-csrf-token"],
    )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        _ = request
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        code = (
            detail.get("code")
            if isinstance(detail.get("code"), str)
            else "request_failed"
        )
        message = (
            detail.get("message")
            if isinstance(detail.get("message"), str)
            else str(exc.detail)
        )
        return JSONResponse(
            status_code=exc.status_code,
            headers=exc.headers,
            content=ErrorResponse(
                error=ErrorDetail(code=code, message=message)
            ).model_dump(),
        )

    @app.get("/health/live", response_model=HealthResponse, tags=["health"])
    async def live() -> HealthResponse:
        return HealthResponse(status="ok", ready=True)

    @app.get("/health/ready", response_model=HealthResponse, tags=["health"])
    async def ready(
        response: Response,
        unavailable: tuple[str, ...] = Depends(probe_readiness),
    ) -> HealthResponse:
        if unavailable:
            response.status_code = 503
            return HealthResponse(
                status="unavailable",
                ready=False,
                detail=f"Unavailable dependencies: {', '.join(unavailable)}.",
            )
        return HealthResponse(
            status="ok",
            ready=True,
            detail="Required dependencies are available.",
        )

    for router in (
        auth_routes.router,
        abbreviation_routes.router,
        upload_routes.router,
        connector_routes.router,
        folder_schedule_routes.router,
        ingestion_job_routes.router,
        graphrag_job_routes.router,
        document_routes.router,
        ingestion_document_routes.router,
        graphrag_document_routes.router,
        ingest_configuration_routes.router,
        rag_configuration_routes.router,
        deployment_routes.router,
        audit_routes.router,
        review_routes.router,
        evaluation_routes.router,
        query_routes.router,
        artifact_routes.router,
    ):
        app.include_router(router, prefix=settings.public_api_prefix)

    for router in (
        abbreviation_routes.internal_router,
        abac_filter_routes.router,
        internal_artifact_job_routes.router,
        claim_routes.router,
        document_supersession_routes.router,
        ingest_config_routes.router,
        index_publication_routes.router,
        ingest_status_routes.router,
        rag_config_routes.router,
        review_batch_routes.router,
    ):
        app.include_router(router, prefix=settings.internal_api_prefix)

    return app


app = create_app()
