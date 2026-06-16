"""Runtime policy and execution for constrained artifact build programs."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

from rag.artifact_jobs.renderer import CONTENT_TYPES, _office_smoke_check, _validate_package
from rag.artifact_jobs.sandbox_contracts import (
    ArtifactSandboxRenderRequest,
    ArtifactSandboxRenderResult,
    RenderedSandboxFile,
)
from .program_policy import validate_program_policy

_LOCK = threading.Lock()


def render_request(request: ArtifactSandboxRenderRequest, *, work_root: Path) -> ArtifactSandboxRenderResult:
    _validate_request(request)
    validate_program_policy(request.program.python_code)
    with _LOCK:
        _prepare_work_root(work_root)
        out_dir = work_root / "out"
        input_path = work_root / "input.json"
        program_path = work_root / "program.py"
        _write_inputs(request, input_path, program_path)
        _run_program(program_path, work_root, out_dir, request.policy.timeout_seconds)
        return _collect_outputs(request, out_dir)


def _validate_request(request: ArtifactSandboxRenderRequest) -> None:
    expected = {output.format for output in request.program.expected_outputs}
    requested = set(request.formats)
    if expected != requested:
        raise ValueError("program expected outputs must match requested formats")


def _prepare_work_root(work_root: Path) -> None:
    work_root.mkdir(parents=True, exist_ok=True)
    for child in work_root.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    (work_root / "out").mkdir()


def _write_inputs(request: ArtifactSandboxRenderRequest, input_path: Path, program_path: Path) -> None:
    input_path.write_text(
        json.dumps({"generated_at": request.generated_at, "bundle": request.bundle.model_dump(mode="json")}),
        encoding="utf-8",
    )
    program_path.write_text(request.program.python_code, encoding="utf-8")


def _run_program(program_path: Path, work_root: Path, out_dir: Path, timeout_seconds: float) -> None:
    bootstrap = work_root / "bootstrap.py"
    bootstrap.write_text(
        "import runpy, socket\n"
        "def _blocked(*_args, **_kwargs):\n"
        "    raise RuntimeError('network access is disabled in artifact sandbox')\n"
        "socket.create_connection = _blocked\n"
        "socket.create_server = _blocked\n"
        f"runpy.run_path({str(program_path)!r}, run_name='__main__')\n",
        encoding="utf-8",
    )
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
        "HOME": str(work_root),
        "ARTIFACT_SANDBOX_OUT_DIR": str(out_dir),
    }
    result = subprocess.run(
        [sys.executable, str(bootstrap)],
        cwd=str(work_root),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout)[-4000:]
        raise RuntimeError(f"artifact build program failed: {detail}")


def _collect_outputs(request: ArtifactSandboxRenderRequest, out_dir: Path) -> ArtifactSandboxRenderResult:
    files: list[RenderedSandboxFile] = []
    warnings: list[str] = []
    max_bytes = request.policy.max_file_mb * 1024 * 1024
    for output in request.program.expected_outputs:
        path = out_dir / output.filename
        if not path.exists():
            warnings.append(f"{output.format} output was not created")
            continue
        content = path.read_bytes()
        if len(content) > max_bytes:
            warnings.append(f"{output.format} output exceeded max file size")
            continue
        try:
            _validate_package(output.format, content)
            smoke = _office_smoke_check(
                artifact_format=output.format,
                content=content,
                require_libreoffice=request.policy.require_libreoffice,
            )
        except Exception as exc:
            warnings.append(f"{output.format} output failed validation: {type(exc).__name__}")
            continue
        files.append(RenderedSandboxFile(
            filename=output.filename,
            format=output.format,
            content_type=CONTENT_TYPES[output.format],
            content_base64=base64.b64encode(content).decode("ascii"),
            size_bytes=len(content),
            warnings=list(smoke),
        ))
    return ArtifactSandboxRenderResult(files=files, warnings=warnings)
