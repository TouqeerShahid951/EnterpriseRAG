"""Deterministic topic and document-type classification."""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_DOC_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "policy": ("policy", "rules", "governance", "shall", "compliance"),
    "procedure": ("procedure", "process", "step", "workflow", "sop"),
    "report": ("report", "findings", "analysis", "summary", "metrics"),
    "contract": ("contract", "agreement", "party", "vendor", "terms"),
    "memo": ("memo", "memorandum", "note", "subject"),
    "manual": ("manual", "guide", "instructions", "operation", "troubleshooting"),
}
_TOPIC_HINTS: dict[str, tuple[str, ...]] = {
    "hr_policy": ("hr", "human", "employee", "staff", "personnel"),
    "it_policy": ("it", "system", "server", "software", "network", "security"),
    "health_safety": ("health", "safety", "incident", "hazard", "ppe"),
}


def classify_topics(text: str, taxonomy: tuple[str, ...], *, max_topics: int = 5) -> tuple[list[str], dict[str, float]]:
    tokens = _tokens(text)
    if not tokens:
        return [], {}
    scored: list[tuple[str, float]] = []
    for topic in taxonomy:
        hints = set(_tokens(topic.replace("_", " "))) | set(_TOPIC_HINTS.get(topic, ()))
        overlap = tokens & hints
        if overlap:
            score = min(1.0, len(overlap) / max(1, len(hints)))
            scored.append((topic, round(score, 3)))
    scored.sort(key=lambda item: (-item[1], item[0]))
    selected = scored[:max_topics]
    return [topic for topic, _ in selected], {topic: score for topic, score in selected}


def classify_doc_type(text: str) -> tuple[str, float]:
    tokens = _tokens(text)
    scored: list[tuple[str, float]] = []
    for doc_type, keywords in _DOC_TYPE_KEYWORDS.items():
        overlap = tokens & set(keywords)
        if overlap:
            scored.append((doc_type, min(0.99, 0.55 + (0.12 * len(overlap)))))
    if not scored:
        return "other", 0.0
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored[0]


def _tokens(text: str) -> set[str]:
    return {token for token in _TOKEN_RE.findall(text.lower()) if len(token) > 1}

