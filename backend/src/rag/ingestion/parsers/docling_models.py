"""Docling model-cache helpers for offline ingestion runtimes."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from pathlib import Path

DEFAULT_DOCLING_ARTIFACTS_PATH = Path("/models/docling")
DEFAULT_RAPIDOCR_BACKEND = "onnxruntime"
DEFAULT_RAPIDOCR_LANGS = ("english",)

_RAPIDOCR_LANG_ALIASES = {
    "ch": "chinese",
    "chi": "chinese",
    "chinese": "chinese",
    "cn": "chinese",
    "en": "english",
    "eng": "english",
    "english": "english",
    "zh": "chinese",
    "zh-cn": "chinese",
}


def configured_docling_artifacts_path() -> Path | None:
    value = os.getenv("DOCLING_ARTIFACTS_PATH", "").strip()
    return Path(value) if value else None


def configured_rapidocr_backend() -> str:
    value = os.getenv("DOCLING_OCR_BACKEND", DEFAULT_RAPIDOCR_BACKEND).strip().lower()
    return value or DEFAULT_RAPIDOCR_BACKEND


def configured_rapidocr_langs() -> tuple[str, ...]:
    value = os.getenv(
        "DOCLING_OCR_LANGS",
        os.getenv("DOCLING_OCR_LANG", ",".join(DEFAULT_RAPIDOCR_LANGS)),
    )
    languages = [_normalize_rapidocr_lang(part) for part in value.replace(";", ",").split(",")]
    deduped = tuple(dict.fromkeys(language for language in languages if language))
    return deduped or DEFAULT_RAPIDOCR_LANGS


def build_rapidocr_options() -> object:
    from docling.datamodel.pipeline_options import RapidOcrOptions

    return RapidOcrOptions(
        lang=list(configured_rapidocr_langs()),
        backend=configured_rapidocr_backend(),
    )


def verify_docling_offline_artifacts(
    output_dir: Path,
    *,
    require_ocr: bool = True,
    ocr_langs: Iterable[str] | None = None,
    ocr_backends: Iterable[str] | None = None,
) -> None:
    """Raise RuntimeError when the local Docling/RapidOCR cache is incomplete."""

    output_dir = Path(output_dir)
    missing: list[Path] = []
    if not output_dir.exists():
        missing.append(output_dir)
    else:
        missing.extend(_missing_required_docling_dirs(output_dir))
        if require_ocr:
            missing.extend(
                _missing_rapidocr_files(
                    output_dir,
                    ocr_langs=ocr_langs or configured_rapidocr_langs(),
                    ocr_backends=ocr_backends or (configured_rapidocr_backend(),),
                )
            )
    if missing:
        preview = ", ".join(str(path) for path in missing[:10])
        suffix = "" if len(missing) <= 10 else f", ... and {len(missing) - 10} more"
        raise RuntimeError(
            "Docling offline artifacts are missing or incomplete under "
            f"{output_dir}. Missing: {preview}{suffix}. "
            "Seed the backend-docling-cache volume while connected with "
            "`docker compose --profile prewarm run --rm docling-prewarm`."
        )


def rapidocr_cache_matrix() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return the RapidOCR language/backend matrix supported by installed Docling."""

    from docling.models.stages.ocr.rapid_ocr_model import RapidOcrModel

    models_by_language = getattr(RapidOcrModel, "_models_by_language", {})
    languages = tuple(sorted(str(language) for language in models_by_language))
    backends = sorted(
        {
            str(backend)
            for backend_models in models_by_language.values()
            for backend in getattr(backend_models, "keys", lambda: [])()
        }
    )
    return languages, tuple(backends)


def _missing_required_docling_dirs(output_dir: Path) -> list[Path]:
    from docling.datamodel.pipeline_options import LayoutOptions
    from docling.models.stages.table_structure.table_structure_model import TableStructureModel

    required_dirs = [
        output_dir / LayoutOptions().model_spec.model_repo_folder,
        output_dir / TableStructureModel._model_repo_folder,
    ]
    return [path for path in required_dirs if not _is_nonempty_dir(path)]


def _missing_rapidocr_files(
    output_dir: Path,
    *,
    ocr_langs: Iterable[str],
    ocr_backends: Iterable[str],
) -> list[Path]:
    return [
        path
        for path in _rapidocr_model_paths(output_dir, ocr_langs=ocr_langs, ocr_backends=ocr_backends)
        if not path.exists()
    ]


def _rapidocr_model_paths(
    output_dir: Path,
    *,
    ocr_langs: Iterable[str],
    ocr_backends: Iterable[str],
) -> list[Path]:
    from docling.models.stages.ocr.rapid_ocr_model import RapidOcrModel

    model_root = output_dir / getattr(RapidOcrModel, "_model_repo_folder", "RapidOcr")
    models_by_language = getattr(RapidOcrModel, "_models_by_language", {})
    normalized_langs = tuple(dict.fromkeys(_normalize_rapidocr_lang(language) for language in ocr_langs))
    normalized_backends = tuple(
        dict.fromkeys(str(backend).strip().lower() for backend in ocr_backends if str(backend).strip())
    )
    paths: list[Path] = []
    seen: set[Path] = set()
    for language in normalized_langs:
        backend_models = models_by_language.get(language)
        if backend_models is None:
            raise ValueError(f"Unsupported RapidOCR language for Docling: {language!r}")
        for backend in normalized_backends:
            model_set = backend_models.get(backend)
            if model_set is None:
                raise ValueError(f"Unsupported RapidOCR backend for Docling: {backend!r}")
            for model_details in _model_detail_values(model_set):
                relative_path = str(model_details.get("path", "")).strip()
                if not relative_path:
                    continue
                path = model_root / relative_path
                if path not in seen:
                    paths.append(path)
                    seen.add(path)
    return paths


def _model_detail_values(model_set: object) -> Iterable[Mapping[str, object]]:
    values = getattr(model_set, "values", None)
    if values is None:
        return ()
    return (detail for detail in values() if isinstance(detail, Mapping))


def _normalize_rapidocr_lang(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    return _RAPIDOCR_LANG_ALIASES.get(normalized, normalized)


def _is_nonempty_dir(path: Path) -> bool:
    return path.is_dir() and any(path.iterdir())
