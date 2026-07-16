"""Dependency and ownership checks for shared feature contracts."""

import ast

from _dependency_scanner import (
    RAG_ROOT,
    assert_no_violations,
    find_violations,
    module_name,
)


AUTHORIZED_CORPUS_CONTRACT_FILE = RAG_ROOT / "retrieval" / "contracts.py"
SHARED_EVIDENCE_CONTRACT_FILE = RAG_ROOT / "shared" / "contracts" / "evidence.py"
EVIDENCE_CONTRACT_NAMES = frozenset(
    {
        "ConflictPair",
        "EvidenceField",
        "EvidenceWindow",
        "HighlightRange",
        "SourceAnchor",
        "SourceRegion",
    }
)
QUERY_EVIDENCE_REEXPORT_TARGETS = frozenset(
    f"rag.query.schemas.{name}" for name in EVIDENCE_CONTRACT_NAMES
)
ALLOWED_SHARED_EVIDENCE_IMPORTS = frozenset(
    {
        "pydantic",
        "rag.shared.contracts.http",
        "rag.shared.contracts.clearance",
        "typing",
    }
)


def test_query_schemas_are_transport_and_runtime_independent() -> None:
    violations = find_violations(
        (RAG_ROOT / "query" / "schemas.py",),
        lambda target: (
            target == "fastapi"
            or target.startswith("fastapi.")
            or target == "rag.core.config"
            or target.startswith("rag.query.adapters.")
            or target in {
                "rag.query.routes",
                "rag.query.execution_routes",
                "rag.query.history_routes",
                "rag.query.sources.source_routes",
                "rag.query.service",
            }
        ),
        resolve_relative_imports=True,
    )

    assert_no_violations(violations)


def test_shared_evidence_contracts_have_exactly_one_class_owner() -> None:
    actual_owners: dict[str, list[str]] = {
        name: [] for name in EVIDENCE_CONTRACT_NAMES
    }
    for path in sorted(RAG_ROOT.rglob("*.py")):
        module = module_name(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name in actual_owners:
                actual_owners[node.name].append(module)

    assert {name: tuple(owners) for name, owners in actual_owners.items()} == {
        name: ("rag.shared.contracts.evidence",)
        for name in EVIDENCE_CONTRACT_NAMES
    }


def test_shared_evidence_contracts_are_dependency_light() -> None:
    violations = find_violations(
        (SHARED_EVIDENCE_CONTRACT_FILE,),
        lambda target: not any(
            target == allowed or target.startswith(f"{allowed}.")
            for allowed in ALLOWED_SHARED_EVIDENCE_IMPORTS
        ),
        resolve_relative_imports=True,
    )

    assert_no_violations(violations)


def test_production_code_uses_canonical_shared_evidence_contracts() -> None:
    violations = find_violations(
        RAG_ROOT.rglob("*.py"),
        lambda target: target in QUERY_EVIDENCE_REEXPORT_TARGETS,
        resolve_relative_imports=True,
    )

    assert_no_violations(violations)


def test_authorized_corpus_contract_is_dependency_light() -> None:
    allowed_imports = frozenset(
        {
            "__future__",
            "dataclasses",
            "hashlib",
            "rag.auth.context",
            "typing",
        }
    )
    violations = find_violations(
        (AUTHORIZED_CORPUS_CONTRACT_FILE,),
        lambda target: not any(
            target == allowed or target.startswith(f"{allowed}.")
            for allowed in allowed_imports
        ),
        resolve_relative_imports=True,
    )

    assert_no_violations(violations)
