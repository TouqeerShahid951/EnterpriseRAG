"""Download the Docling artifacts used by the ingestion pipeline."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

DEFAULT_ARTIFACTS_PATH = Path("/models/docling")


def prewarm_docling_models(output_dir: Path) -> Path:
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

    from docling.utils.model_downloader import download_models

    return download_models(
        output_dir=output_dir,
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(os.getenv("DOCLING_ARTIFACTS_PATH", DEFAULT_ARTIFACTS_PATH)),
    )
    args = parser.parse_args()
    output_dir = prewarm_docling_models(args.output_dir)
    print(f"Docling models downloaded to {output_dir}")


if __name__ == "__main__":
    main()
