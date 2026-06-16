"""LLM generation of constrained artifact sandbox programs."""

from __future__ import annotations

import ast
from collections.abc import Sequence
import json
import re

from ..repositories.artifact_jobs import ArtifactJobRecord
from .contracts import ArtifactContentBundle, DocumentPlan
from .llm_json import generate_contract
from .sandbox_contracts import ArtifactBuildProgram, ArtifactExpectedOutput


BUILD_PROGRAM_PROMPT_VERSION = "artifact-build-program-v1.1"


def generate_build_program(
    job: ArtifactJobRecord,
    plan: DocumentPlan,
    bundle: ArtifactContentBundle,
    *,
    inference: object,
    model: str | None,
    requested_formats: Sequence[str] | None = None,
) -> ArtifactBuildProgram:
    selected_formats = tuple(job.requested_formats if requested_formats is None else requested_formats)
    outputs = _requested_outputs(bundle, selected_formats)
    output_json = [output.model_dump(mode="json") for output in outputs]
    prompt = (
        "Create a constrained Python artifact build program that chooses the document layout. "
        "The program must use only the local artifact SDK and must not access networks, app "
        "internals, secrets, databases, or storage. It must read /work/input.json and write only "
        "declared files under /work/out. Return only JSON matching the schema.\n\n"
        "The app owns output policy. Set expected_outputs exactly to the Requested outputs JSON "
        "below, with no extra formats and no missing formats. The python_code must create exactly "
        "those files under /work/out.\n\n"
        "You MUST use SDK layout primitives, not one-shot deterministic renderers. Available "
        "entry points: doc.create_docx(path), doc.create_pdf(path), doc.create_pptx(path). "
        "DOCX/PDF builders support add_heading, add_paragraph, add_bullet_list, "
        "add_numbered_list, add_table, add_callout, add_page_break, add_references, finalize. "
        "PPTX builders support add_title_slide, add_slide, add_heading, add_paragraph, "
        "add_bullet_list, add_numbered_list, add_table, add_callout, add_references_slide, "
        "finalize. The old doc.write_docx/write_pptx/write_pdf methods are forbidden.\n\n"
        "Use the validated bundle through doc.title, doc.subtitle, doc.purpose, doc.sections, "
        "section.blocks, doc.citations, and "
        "block evidence_ids so citations and references stay grounded. Choose headings, tables, "
        "callouts, slide breaks, and ordering to match the user request. Block fields include "
        "kind, text, evidence_ids, list_items, entries, and table. Table blocks expose "
        "block.table.headers and block.table.rows; row.values is already a list of strings, and "
        "row objects also expose evidence_ids. List items expose text and evidence_ids. Prefer "
        "passing block.list_items to add_bullet_list/add_numbered_list and block.table.rows to "
        "add_table; if extracting text manually, pass flat evidence_ids, not nested "
        "[item.evidence_ids for item in ...] lists.\n\n"
        "Example program shape:\n"
        "from rag.artifact_sandbox.sdk import ArtifactDocument\n"
        "doc = ArtifactDocument.from_input('/work/input.json')\n"
        "pdf = doc.create_pdf('/work/out/example.pdf', title=doc.title, subtitle=doc.subtitle)\n"
        "pdf.add_heading('Executive Summary')\n"
        "pdf.add_paragraph(doc.bundle.content.purpose)\n"
        "for section in doc.sections:\n"
        "    pdf.add_heading(section.title, level=2)\n"
        "    for block in section.blocks:\n"
        "        if block.text:\n"
        "            pdf.add_paragraph(block.text, evidence_ids=block.evidence_ids)\n"
        "pdf.add_references()\n"
        "pdf.finalize()\n\n"
        f"Original request:\n{job.original_request}\n\n"
        f"Document plan:\n{plan.model_dump_json()}\n\n"
        f"Requested outputs:\n{json.dumps(output_json, ensure_ascii=True)}\n\n"
        f"Validated content shape:\n{json.dumps(_bundle_layout_summary(bundle), ensure_ascii=True)}\n\n"
        f"Return JSON schema:\n{json.dumps(ArtifactBuildProgram.model_json_schema(), separators=(',', ':'))}"
    )
    program = generate_contract(
        inference=inference,
        model=model,
        system="You generate constrained offline document build programs.",
        prompt=prompt,
        contract=ArtifactBuildProgram,
    )
    if _output_signature(program.expected_outputs) != _output_signature(outputs):
        program = _repair_requested_outputs(
            program,
            outputs,
            inference=inference,
            model=model,
        )
    _validate_requested_outputs(program, outputs)
    _validate_layout_program(program)
    return program


def _requested_outputs(bundle: ArtifactContentBundle, requested_formats: tuple[str, ...]) -> list[ArtifactExpectedOutput]:
    return [
        ArtifactExpectedOutput(format=artifact_format, filename=f"{_safe_filename(bundle.content.title)}.{artifact_format}")  # type: ignore[arg-type]
        for artifact_format in requested_formats
    ]


def _repair_requested_outputs(
    program: ArtifactBuildProgram,
    outputs: list[ArtifactExpectedOutput],
    *,
    inference: object,
    model: str | None,
) -> ArtifactBuildProgram:
    output_json = [output.model_dump(mode="json") for output in outputs]
    prompt = (
        "Repair this ArtifactBuildProgram. Keep the layout intent, but the app owns the output "
        "contract. expected_outputs must exactly equal the Requested outputs JSON. python_code "
        "must create only those declared files under /work/out using the matching create_* SDK "
        "methods, and must remove any create_* calls for unrequested formats. Return only JSON "
        "matching the schema.\n\n"
        f"Requested outputs:\n{json.dumps(output_json, ensure_ascii=True)}\n\n"
        f"Invalid ArtifactBuildProgram:\n{program.model_dump_json()}\n\n"
        f"Return JSON schema:\n{json.dumps(ArtifactBuildProgram.model_json_schema(), separators=(',', ':'))}"
    )
    return generate_contract(
        inference=inference,
        model=model,
        system="You repair constrained offline document build programs.",
        prompt=prompt,
        contract=ArtifactBuildProgram,
    )


def _bundle_layout_summary(bundle: ArtifactContentBundle) -> dict[str, object]:
    sections: list[dict[str, object]] = []
    for section in bundle.content.sections[:24]:
        blocks: list[dict[str, object]] = []
        for block in section.blocks[:8]:
            summary: dict[str, object] = {"kind": block.kind}
            if block.kind in {"bullet_list", "numbered_list"}:
                summary["items"] = len(block.list_items or block.items)
            if block.kind == "table" and block.table is not None:
                summary["headers"] = block.table.headers[:12]
                summary["rows"] = len(block.table.rows)
            if block.text:
                summary["text_preview"] = _compact(block.text, 160)
            blocks.append(summary)
        sections.append({"title": section.title, "blocks": blocks})
    return {
        "title": bundle.content.title,
        "purpose": _compact(bundle.content.purpose, 260),
        "sections": sections,
        "citation_count": len(bundle.content.citations),
        "presentation_slides": len(bundle.presentation.slides),
    }


def _validate_requested_outputs(program: ArtifactBuildProgram, outputs: list[ArtifactExpectedOutput]) -> None:
    if _output_signature(program.expected_outputs) != _output_signature(outputs):
        raise ValueError("build program expected outputs must match requested formats")


def _output_signature(outputs: list[ArtifactExpectedOutput]) -> list[tuple[str, str]]:
    return [(output.format, output.filename) for output in outputs]


def _validate_layout_program(program: ArtifactBuildProgram) -> None:
    called_methods = _called_methods(program.python_code)
    forbidden = {"write_docx", "write_pptx", "write_pdf", "write_format"}
    if called_methods.intersection(forbidden):
        raise ValueError("build program must use layout primitives, not deterministic write_* calls")
    if "finalize" not in called_methods:
        raise ValueError("build program must finalize generated files")
    if not any(method.startswith("add_") for method in called_methods):
        raise ValueError("build program must add layout content with SDK primitives")
    required = {"docx": "create_docx", "pptx": "create_pptx", "pdf": "create_pdf"}
    for output in program.expected_outputs:
        if required[output.format] not in called_methods:
            raise ValueError(f"build program must call {required[output.format]} for {output.format}")


def _called_methods(code: str) -> set[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ValueError(f"build program contains invalid Python: {exc}") from exc
    return {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def _safe_filename(value: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip(".-")
    return _compact(candidate or "evidence-artifact", 80).strip(".-") or "evidence-artifact"


def _compact(value: str, limit: int) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    return normalized if len(normalized) <= limit else normalized[: max(0, limit - 3)].rstrip() + "..."
