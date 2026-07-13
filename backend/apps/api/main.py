from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from rag.api.routes import (
    admin_routes,
    audit_routes,
    auth_routes,
    connector_routes,
    evaluation_routes,
    query_routes,
    review_routes,
)
from rag.artifact_jobs import routes as artifact_routes
from rag.bootstrap.schema import ensure_postgres_schema
from rag.core.config import settings
from rag.documents import routes as document_routes
from rag.documents import upload_routes
from rag.graphrag import (
    document_routes as graphrag_document_routes,
    job_routes as graphrag_job_routes,
)
from rag.ingestion import (
    document_routes as ingestion_document_routes,
    job_routes as ingestion_job_routes,
)
from rag.ingestion.folders import routes as folder_schedule_routes
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
from rag.schemas.common import ErrorDetail, ErrorResponse, HealthResponse
from rag.services.bootstrap_admin import ensure_initial_platform_admin


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    ensure_postgres_schema(settings)
    repository_provider = app.dependency_overrides.get(get_identity_repository, get_identity_repository)
    ensure_initial_platform_admin(
        repository_provider(),
        email=settings.bootstrap_admin_email,
        name=settings.bootstrap_admin_name,
        password=settings.bootstrap_admin_password,
    )
    yield


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
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        _ = request
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        code = detail.get("code") if isinstance(detail.get("code"), str) else "request_failed"
        message = detail.get("message") if isinstance(detail.get("message"), str) else str(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            headers=exc.headers,
            content=ErrorResponse(error=ErrorDetail(code=code, message=message)).model_dump(),
        )

    @app.get("/health/live", response_model=HealthResponse, tags=["health"])
    async def live() -> HealthResponse:
        return HealthResponse(status="ok", ready=True)

    @app.get("/health/ready", response_model=HealthResponse, tags=["health"])
    async def ready() -> HealthResponse:
        return HealthResponse(
            status="ok",
            ready=True,
            detail="Backend is ready; query depends on the configured inference provider and Qdrant at request time.",
        )

    for router in (
        auth_routes.router,
        upload_routes.router,
        connector_routes.router,
        folder_schedule_routes.router,
        ingestion_job_routes.router,
        graphrag_job_routes.router,
        document_routes.router,
        ingestion_document_routes.router,
        graphrag_document_routes.router,
        admin_routes.router,
        audit_routes.router,
        review_routes.router,
        evaluation_routes.router,
        query_routes.router,
        artifact_routes.router,
    ):
        app.include_router(router, prefix=settings.public_api_prefix)

    for router in (
        abac_filter_routes.router,
        internal_artifact_job_routes.router,
        claim_routes.router,
        document_supersession_routes.router,
        ingest_config_routes.router,
        ingest_status_routes.router,
        rag_config_routes.router,
        review_batch_routes.router,
    ):
        app.include_router(router, prefix=settings.internal_api_prefix)

    return app


app = create_app()
