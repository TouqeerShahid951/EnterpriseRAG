"""Download the Docling artifacts used by the ingestion pipeline."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from rag_ingestion.docling_models import (
    DEFAULT_DOCLING_ARTIFACTS_PATH,
    rapidocr_cache_matrix,
    verify_docling_offline_artifacts,
)


def prewarm_docling_models(output_dir: Path, *, force: bool = False, verify_only: bool = False) -> Path:
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

    if verify_only:
        verify_docling_offline_artifacts(output_dir)
        return output_dir

    from docling.utils.model_downloader import download_models

    output_dir = download_models(
        output_dir=output_dir,
        force=force,
        progress=True,
        with_layout=True,
        with_tableformer=True,
        with_tableformer_v2=False,
        with_code_formula=False,
        with_picture_classifier=False,
        with_smolvlm=False,
        with_granitedocling=False,
        with_granitedocling_mlx=False,
        with_granitedocling_2stage=False,
        with_smoldocling=False,
        with_smoldocling_mlx=False,
        with_granite_vision=False,
        with_granite_chart_extraction=False,
        with_granite_chart_extraction_v4=False,
        with_rapidocr=True,
        with_easyocr=False,
    )
    rapidocr_langs, rapidocr_backends = rapidocr_cache_matrix()
    verify_docling_offline_artifacts(
        output_dir,
        ocr_langs=rapidocr_langs,
        ocr_backends=rapidocr_backends,
    )
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(os.getenv("DOCLING_ARTIFACTS_PATH", DEFAULT_DOCLING_ARTIFACTS_PATH)),
    )
    parser.add_argument("--force", action="store_true", help="Refresh artifacts even when files already exist.")
    parser.add_argument("--verify-only", action="store_true", help="Validate the local cache without downloading.")
    args = parser.parse_args()
    output_dir = prewarm_docling_models(args.output_dir, force=args.force, verify_only=args.verify_only)
    action = "verified" if args.verify_only else "downloaded and verified"
    print(f"Docling models {action} at {output_dir}")


if __name__ == "__main__":
    main()
