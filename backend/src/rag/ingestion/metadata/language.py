"""Document language detection."""

from __future__ import annotations

import re

_ARABIC_SCRIPT_RE = re.compile(r"[\u0600-\u06ff]")


def detect_language(text: str) -> str:
    sample = text.strip()
    if not sample:
        return "unknown"
    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0
        return detect(sample[:5000])
    except Exception:
        if _ARABIC_SCRIPT_RE.search(sample):
            return "ur"
        return "en"

