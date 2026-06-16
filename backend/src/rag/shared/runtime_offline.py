"""Runtime offline controls for model-loading libraries."""

from __future__ import annotations

import os


OFFLINE_ENV_DEFAULTS = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "HF_HUB_DISABLE_XET": "1",
    "DO_NOT_TRACK": "1",
}

_FALSE_VALUES = {"0", "false", "no", "off"}


def runtime_offline_enabled() -> bool:
    return os.getenv("AIRGAP_RUNTIME_OFFLINE", "0").strip().lower() not in _FALSE_VALUES


def apply_runtime_offline_defaults() -> None:
    if not runtime_offline_enabled():
        return
    for key, value in OFFLINE_ENV_DEFAULTS.items():
        os.environ.setdefault(key, value)
