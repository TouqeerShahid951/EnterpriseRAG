"""Dependency boundaries for artifact-job application and adapter code."""

from _dependency_scanner import RAG_ROOT, assert_no_violations, find_violations


ARTIFACT_APPLICATION_FILES = (
    RAG_ROOT / "artifact_jobs" / "cleanup.py",
    RAG_ROOT / "artifact_jobs" / "publisher.py",
    RAG_ROOT / "artifact_jobs" / "queue.py",
    RAG_ROOT / "artifact_jobs" / "retrieval.py",
    RAG_ROOT / "artifact_jobs" / "service.py",
    RAG_ROOT / "artifact_jobs" / "storage.py",
    RAG_ROOT / "artifact_jobs" / "task_execution.py",
)
ARTIFACT_SUBMISSION_FILE = RAG_ROOT / "artifact_jobs" / "submission.py"
ARTIFACT_RETRIEVAL_FILE = RAG_ROOT / "artifact_jobs" / "retrieval.py"
ARTIFACT_EXECUTION_FILE = RAG_ROOT / "artifact_jobs" / "execution" / "executor.py"
ARTIFACT_GENERATION_PORT_FILE = (
    RAG_ROOT / "artifact_jobs" / "generation" / "contracts.py"
)
ARTIFACT_REQUEST_TEXT_FILE = RAG_ROOT / "artifact_jobs" / "request_text.py"
ARTIFACT_QUERY_COMPOSITION_FILE = RAG_ROOT / "artifact_jobs" / "dependencies.py"
ARTIFACT_QUERY_GENERATION_ADAPTER_FILE = (
    RAG_ROOT / "artifact_jobs" / "adapters" / "query_generation.py"
)
ARTIFACT_GENERATION_APPLICATION_FILES = (
    RAG_ROOT / "artifact_jobs" / "execution" / "bundle_repair.py",
    RAG_ROOT / "artifact_jobs" / "generation" / "composer.py",
    RAG_ROOT / "artifact_jobs" / "generation" / "composition.py",
    RAG_ROOT / "artifact_jobs" / "generation" / "composition_deadline.py",
    RAG_ROOT / "artifact_jobs" / "execution" / "executor.py",
    RAG_ROOT / "artifact_jobs" / "generation" / "fallback_composition.py",
    RAG_ROOT / "artifact_jobs" / "generation" / "format_adaptation.py",
    RAG_ROOT / "artifact_jobs" / "generation" / "llm_json.py",
    RAG_ROOT / "artifact_jobs" / "generation" / "planner.py",
)
QUERY_RETRIEVAL_IMPLEMENTATION_MODULES = frozenset(
    {
        "rag.query.routing.intent_router",
        "rag.query.qdrant",
        "rag.query.retrieval.query_retrieval",
        "rag.query.configuration.models",
        "rag.query.reranker",
        "rag.query.sources",
        "rag.query.state",
        "rag.query.retrieval.temporal",
    }
)


def test_artifact_jobs_do_not_import_query_schemas() -> None:
    violations = find_violations(
        (RAG_ROOT / "artifact_jobs").rglob("*.py"),
        lambda target: target == "rag.query.schemas"
        or target.startswith("rag.query.schemas."),
        resolve_relative_imports=True,
    )

    assert_no_violations(violations)


def test_artifact_submission_contract_is_dependency_light() -> None:
    violations = find_violations(
        (ARTIFACT_SUBMISSION_FILE,),
        lambda target: (
            target == "fastapi"
            or target.startswith("fastapi.")
            or target == "celery"
            or target.startswith("celery.")
            or target == "rag.core.config"
            or target.startswith("rag.artifact_jobs.adapters.")
            or target == "rag.query"
            or target.startswith("rag.query.")
            or target == "rag.documents"
            or target.startswith("rag.documents.")
        ),
        resolve_relative_imports=True,
    )

    assert_no_violations(violations)


def test_artifact_generation_port_is_dependency_light() -> None:
    allowed_imports = frozenset({"__future__", "typing"})
    violations = find_violations(
        (ARTIFACT_GENERATION_PORT_FILE,),
        lambda target: not any(
            target == allowed or target.startswith(f"{allowed}.")
            for allowed in allowed_imports
        ),
        resolve_relative_imports=True,
    )

    assert_no_violations(violations)


def test_artifact_request_text_is_dependency_light() -> None:
    allowed_imports = frozenset({"__future__", "re"})
    violations = find_violations(
        (ARTIFACT_REQUEST_TEXT_FILE,),
        lambda target: not any(
            target == allowed or target.startswith(f"{allowed}.")
            for allowed in allowed_imports
        ),
        resolve_relative_imports=True,
    )

    assert_no_violations(violations)


def test_artifact_query_imports_are_confined_to_composition_and_adapter() -> None:
    allowed_files = {
        ARTIFACT_QUERY_COMPOSITION_FILE,
        ARTIFACT_QUERY_GENERATION_ADAPTER_FILE,
    }
    application_files = (
        path
        for path in (RAG_ROOT / "artifact_jobs").rglob("*.py")
        if path not in allowed_files
    )
    violations = find_violations(
        application_files,
        lambda target: target == "rag.query" or target.startswith("rag.query."),
        resolve_relative_imports=True,
    )

    assert_no_violations(violations)


def test_artifact_query_composition_imports_are_explicitly_allowlisted() -> None:
    allowed_imports = {
        ARTIFACT_QUERY_COMPOSITION_FILE: frozenset(
            {
                "rag.query.inference",
                "rag.query.inference.build_inference_client",
                "rag.query.configuration.repository",
                "rag.query.configuration.repository.effective_rag_config",
            }
        ),
        ARTIFACT_QUERY_GENERATION_ADAPTER_FILE: frozenset(
            {
                "rag.query.http",
                "rag.query.http.ServiceRequestError",
                "rag.query.inference",
                "rag.query.inference.InferenceClient",
            }
        ),
    }
    violations: list[str] = []
    for path, allowed in allowed_imports.items():
        violations.extend(
            find_violations(
                (path,),
                lambda target, allowed=allowed: (
                    (target == "rag.query" or target.startswith("rag.query."))
                    and target not in allowed
                ),
                resolve_relative_imports=True,
            )
        )

    assert_no_violations(violations)


def test_artifact_generation_application_does_not_import_concrete_adapters() -> None:
    violations = find_violations(
        ARTIFACT_GENERATION_APPLICATION_FILES,
        lambda target: target == "rag.artifact_jobs.adapters"
        or target.startswith("rag.artifact_jobs.adapters."),
        resolve_relative_imports=True,
    )

    assert_no_violations(violations)


def test_artifact_retrieval_application_does_not_import_query_implementation() -> None:
    violations = find_violations(
        (ARTIFACT_RETRIEVAL_FILE,),
        lambda target: target == "rag.query"
        or target.startswith("rag.query.")
        or target == "rag.core.config",
        resolve_relative_imports=True,
    )

    assert_no_violations(violations)


def test_artifact_feature_does_not_import_query_retrieval_implementation() -> None:
    violations = find_violations(
        (RAG_ROOT / "artifact_jobs").rglob("*.py"),
        lambda target: any(
            target == module or target.startswith(f"{module}.")
            for module in QUERY_RETRIEVAL_IMPLEMENTATION_MODULES
        ),
        resolve_relative_imports=True,
    )

    assert_no_violations(violations)


def test_artifact_executor_does_not_receive_query_runtime_types() -> None:
    violations = find_violations(
        (ARTIFACT_EXECUTION_FILE,),
        lambda target: target == "rag.query" or target.startswith("rag.query."),
        resolve_relative_imports=True,
    )

    assert_no_violations(violations)


def test_artifact_application_code_is_transport_and_settings_independent() -> None:
    violations = find_violations(
        ARTIFACT_APPLICATION_FILES,
        lambda target: (
            target == "celery"
            or target.startswith("celery.")
            or target == "fastapi"
            or target.startswith("fastapi.")
            or target == "rag.core.config"
            or target.startswith("rag.artifact_jobs.adapters.")
        ),
        resolve_relative_imports=True,
    )

    assert_no_violations(violations)
