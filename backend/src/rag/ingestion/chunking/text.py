"""Text splitting helpers for ingestion chunking."""

from __future__ import annotations

import re

SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
CHARS_PER_TOKEN_GUARD = 3


def split_text(text: str, *, target_tokens: int, overlap_tokens: int) -> list[str]:
    max_chars = target_tokens * CHARS_PER_TOKEN_GUARD
    sentences = [item.strip() for item in SENTENCE_BOUNDARY.split(text) if item.strip()]
    if len(sentences) > 1:
        chunks = _pack_sentences(sentences, target_tokens, max_chars)
    else:
        chunks = _token_windows(text.split(), target_tokens, overlap_tokens, max_chars)
    return [chunk for chunk in chunks if chunk]


def _pack_sentences(sentences: list[str], target_tokens: int, max_chars: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    for sentence in sentences:
        candidate = " ".join([*current, sentence])
        if current and _too_large(candidate, target_tokens, max_chars):
            chunks.append(" ".join(current))
            current = []
        if _too_large(sentence, target_tokens, max_chars):
            chunks.extend(_token_windows(sentence.split(), target_tokens, 0, max_chars))
        else:
            current.append(sentence)
    if current:
        chunks.append(" ".join(current))
    return chunks


def _token_windows(tokens: list[str], target_tokens: int, overlap_tokens: int, max_chars: int) -> list[str]:
    tokens = _split_large_tokens(tokens, max_chars)
    chunks: list[str] = []
    start = 0
    while start < len(tokens):
        end = min(len(tokens), start + target_tokens)
        chunks.extend(_char_windows(" ".join(tokens[start:end]), max_chars))
        if end == len(tokens):
            break
        start = max(0, end - overlap_tokens)
    return chunks


def _split_large_tokens(tokens: list[str], max_chars: int) -> list[str]:
    split: list[str] = []
    for token in tokens:
        split.extend(_char_windows(token, max_chars))
    return split


def _char_windows(text: str, max_chars: int) -> list[str]:
    return [text[start : start + max_chars] for start in range(0, len(text), max_chars)] if len(text) > max_chars else [text]


def _too_large(text: str, target_tokens: int, max_chars: int) -> bool:
    return _token_count(text) > target_tokens or len(text) > max_chars


def _token_count(text: str) -> int:
    return len(text.split())
