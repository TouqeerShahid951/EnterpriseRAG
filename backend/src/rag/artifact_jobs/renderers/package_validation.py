"""Validate rendered packages and optionally smoke-check Office documents."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

from ..types import ArtifactFormat


def validate_package(artifact_format: ArtifactFormat, content: bytes) -> None:
    if len(content) < 100:
        raise RuntimeError(f"{artifact_format} renderer returned an empty package")
    if artifact_format == "pdf":
        if not content.startswith(b"%PDF"):
            raise RuntimeError("PDF renderer returned an invalid document")
        return
    required = "word/document.xml" if artifact_format == "docx" else "ppt/presentation.xml"
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            if required not in archive.namelist():
                raise RuntimeError(f"{artifact_format} package is missing {required}")
            archive.testzip()
    except zipfile.BadZipFile as exc:
        raise RuntimeError(f"{artifact_format} renderer returned an invalid OpenXML package") from exc


def office_smoke_check(
    *,
    artifact_format: ArtifactFormat,
    content: bytes,
    require_libreoffice: bool,
) -> tuple[str, ...]:
    if artifact_format == "pdf":
        return ()
    executable = shutil.which("libreoffice") or shutil.which("soffice")
    if executable is None:
        if require_libreoffice:
            raise RuntimeError("LibreOffice is required for generated artifact smoke checks")
        return ("LibreOffice smoke check skipped because LibreOffice is unavailable.",)
    with tempfile.TemporaryDirectory(prefix="artifact-smoke-") as temp_dir:
        source = Path(temp_dir) / f"artifact.{artifact_format}"
        source.write_bytes(content)
        result = subprocess.run(
            [executable, "--headless", "--convert-to", "pdf", "--outdir", temp_dir, str(source)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        converted = Path(temp_dir) / "artifact.pdf"
        if result.returncode != 0 or not converted.exists() or converted.stat().st_size < 500:
            message = f"LibreOffice smoke check failed: {(result.stderr or result.stdout)[-500:]}"
            if require_libreoffice:
                raise RuntimeError(message)
            return (message,)
        pdftotext = shutil.which("pdftotext")
        if pdftotext:
            text_result = subprocess.run(
                [pdftotext, "-layout", str(converted), "-"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            pages = text_result.stdout.split("\f")
            if any(not page.strip() for page in pages[:-1]):
                message = "LibreOffice smoke check found a blank output page"
                if require_libreoffice:
                    raise RuntimeError(message)
                return (message,)
    return ()
