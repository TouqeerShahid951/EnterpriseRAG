"""FastAPI app for the offline artifact sandbox service."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException

from rag.artifact_jobs.sandbox_contracts import ArtifactSandboxRenderRequest, ArtifactSandboxRenderResult
from rag.schemas.common import HealthResponse

from .runtime import render_request


app = FastAPI(title="AgenticRAG Artifact Sandbox", version="0.0.0")


@app.get("/health/live", response_model=HealthResponse)
def live() -> HealthResponse:
    return HealthResponse(status="ok", ready=True, detail="artifact sandbox live")


@app.get("/health/ready", response_model=HealthResponse)
def ready() -> HealthResponse:
    work_root = _work_root()
    try:
        work_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return HealthResponse(status="ok", ready=False, detail=str(exc))
    return HealthResponse(status="ok", ready=True, detail="artifact sandbox ready")


@app.post("/v1/render", response_model=ArtifactSandboxRenderResult)
def render(payload: ArtifactSandboxRenderRequest) -> ArtifactSandboxRenderResult:
    try:
        return render_request(payload, work_root=_work_root())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "sandbox_policy_rejected", "message": str(exc)}) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=408, detail={"code": "sandbox_timeout", "message": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"code": "sandbox_render_failed", "message": str(exc)[:4000]}) from exc


def _work_root() -> Path:
    return Path(os.getenv("ARTIFACT_SANDBOX_WORK_ROOT", "/work"))
