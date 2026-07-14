"""Static contracts for reproducible backend dependency ownership."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[2]
DOCUMENT_WORKER_ROOT = (
    BACKEND_ROOT / "apps" / "workers" / "document_pipeline"
)
PYTORCH_CPU_INDEX_URL = "https://download.pytorch.org/whl/cpu"

RUNTIME_PROJECTS = (
    (
        BACKEND_ROOT,
        BACKEND_ROOT / "apps" / "api" / "Dockerfile",
        frozenset({"pyproject.toml", "uv.lock"}),
    ),
    (
        DOCUMENT_WORKER_ROOT,
        DOCUMENT_WORKER_ROOT / "Dockerfile",
        frozenset(
            {
                "apps/workers/document_pipeline/pyproject.toml",
                "apps/workers/document_pipeline/uv.lock",
            }
        ),
    ),
)

_REQUIREMENT_PATTERN = re.compile(
    r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?:\[([^]]+)\])?\s*(.*?)\s*$"
)
_PIP_INSTALL_PATTERN = re.compile(
    r"(?:\bpython\s+-m\s+)?\bpip\s+install\b([^;&]*)"
)
_SYNC_PATTERN = re.compile(r"\buv\s+sync\b([^;&]*)")


def test_runtime_projects_own_adjacent_lockfiles() -> None:
    for project_root, _, _ in RUNTIME_PROJECTS:
        assert (project_root / "pyproject.toml").is_file()
        assert (project_root / "uv.lock").is_file()
        _root_lock_package(project_root)

    assert not (DOCUMENT_WORKER_ROOT / "constraints.txt").exists()


@pytest.mark.parametrize(
    ("project_root", "dockerfile", "required_copy_sources"),
    RUNTIME_PROJECTS,
    ids=("api", "document-worker"),
)
def test_runtime_dockerfiles_copy_manifests_and_locks_before_sync(
    project_root: Path,
    dockerfile: Path,
    required_copy_sources: frozenset[str],
) -> None:
    del project_root
    instructions = _dockerfile_instructions(dockerfile)
    copy_index = next(
        (
            index
            for index, instruction in enumerate(instructions)
            if instruction.startswith("COPY ")
            and required_copy_sources <= frozenset(instruction.split()[1:-1])
        ),
        None,
    )
    sync_index = next(
        (
            index
            for index, instruction in enumerate(instructions)
            if _SYNC_PATTERN.search(instruction)
        ),
        None,
    )

    assert copy_index is not None, (
        f"{dockerfile} must copy its pyproject.toml and uv.lock together"
    )
    assert sync_index is not None, f"{dockerfile} must install with uv sync"
    assert copy_index < sync_index


@pytest.mark.parametrize(
    ("project_root", "dockerfile", "required_copy_sources"),
    RUNTIME_PROJECTS,
    ids=("api", "document-worker"),
)
def test_runtime_images_use_locked_production_sync(
    project_root: Path,
    dockerfile: Path,
    required_copy_sources: frozenset[str],
) -> None:
    del project_root, required_copy_sources
    source = "\n".join(_dockerfile_instructions(dockerfile))
    sync_commands = _SYNC_PATTERN.findall(source)

    assert sync_commands, f"{dockerfile} must install from uv.lock"
    for command in sync_commands:
        flags = frozenset(re.findall(r"--[a-z][a-z-]*", command))
        assert "--locked" in flags, (
            f"{dockerfile} must fail when pyproject.toml and uv.lock disagree"
        )
        assert "--no-dev" in flags, (
            f"{dockerfile} must omit development dependencies"
        )

    assert "tomllib" not in source
    assert "requirements.txt" not in source
    assert "constraints.txt" not in source

    for pip_arguments in _PIP_INSTALL_PATTERN.findall(source):
        assert "--no-deps" in pip_arguments and re.search(
            r"(?:^|\s)(?:/app|\.)(?:\s|$)", pip_arguments
        ), (
            f"{dockerfile} may use pip only for a dependency-free local project "
            "install; external packages must come from uv.lock"
        )


@pytest.mark.parametrize(
    ("project_root", "dockerfile", "required_copy_sources"),
    RUNTIME_PROJECTS,
    ids=("api", "document-worker"),
)
def test_lock_metadata_matches_declared_direct_dependencies(
    project_root: Path,
    dockerfile: Path,
    required_copy_sources: frozenset[str],
) -> None:
    del dockerfile, required_copy_sources
    project = _read_toml(project_root / "pyproject.toml")
    lock_package = _root_lock_package(project_root)

    declared = {
        _parse_requirement(requirement)
        for requirement in project["project"]["dependencies"]
    }
    locked = {
        (
            _normalize_name(requirement["name"]),
            tuple(sorted(requirement.get("extras", ()))),
            requirement.get("specifier", ""),
        )
        for requirement in lock_package["metadata"]["requires-dist"]
        if "marker" not in requirement
    }

    assert locked == declared


def test_document_worker_cpu_torch_policy_is_project_and_lock_owned() -> None:
    project = _read_toml(DOCUMENT_WORKER_ROOT / "pyproject.toml")
    lock = _read_toml(DOCUMENT_WORKER_ROOT / "uv.lock")
    dependencies = {
        name: specifier
        for name, _, specifier in (
            _parse_requirement(requirement)
            for requirement in project["project"]["dependencies"]
        )
    }
    sources = project["tool"]["uv"]["sources"]
    indexes = {
        index["name"]: index for index in project["tool"]["uv"]["index"]
    }
    locked_package_names = {
        _normalize_name(package["name"]) for package in lock["package"]
    }
    accelerator_packages = sorted(
        name
        for name in locked_package_names
        if name.startswith(("cuda-", "nvidia-", "triton"))
    )

    assert accelerator_packages == [], (
        "the CPU document-worker lock must not include CUDA or Triton packages"
    )

    for package_name in ("torch", "torchvision"):
        specifier = dependencies[package_name]
        assert re.fullmatch(r"==[^,]+", specifier), (
            f"{package_name} must stay an exact worker baseline pin"
        )
        expected_version = specifier.removeprefix("==")
        index = indexes[sources[package_name]["index"]]
        assert index["url"].rstrip("/") == PYTORCH_CPU_INDEX_URL
        assert index.get("explicit") is True

        lock_packages = [
            package
            for package in lock["package"]
            if _normalize_name(package["name"]) == package_name
        ]
        assert lock_packages
        for lock_package in lock_packages:
            assert lock_package["version"] in {
                expected_version,
                f"{expected_version}+cpu",
            }
            assert (
                lock_package["source"]["registry"].rstrip("/")
                == PYTORCH_CPU_INDEX_URL
            )


def _dockerfile_instructions(path: Path) -> list[str]:
    instructions: list[str] = []
    current = ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        current = f"{current} {line}".strip()
        if current.endswith("\\"):
            current = current[:-1].rstrip()
            continue
        instructions.append(current)
        current = ""

    assert not current, f"unterminated Dockerfile continuation in {path}"
    return instructions


def _parse_requirement(requirement: str) -> tuple[str, tuple[str, ...], str]:
    match = _REQUIREMENT_PATTERN.fullmatch(requirement)
    assert match is not None, f"unsupported direct requirement: {requirement}"
    extras = tuple(
        sorted(
            extra.strip()
            for extra in (match.group(2) or "").split(",")
            if extra.strip()
        )
    )
    return (
        _normalize_name(match.group(1)),
        extras,
        match.group(3).replace(" ", ""),
    )


def _normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _root_lock_package(project_root: Path) -> dict[str, Any]:
    project = _read_toml(project_root / "pyproject.toml")
    lock = _read_toml(project_root / "uv.lock")
    project_name = _normalize_name(project["project"]["name"])
    matches = [
        package
        for package in lock["package"]
        if _normalize_name(package["name"]) == project_name
    ]
    assert len(matches) == 1
    return matches[0]


def _read_toml(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))
