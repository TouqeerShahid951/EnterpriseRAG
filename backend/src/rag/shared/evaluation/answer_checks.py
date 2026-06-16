"""Conservative literal and claim-polarity checks for generated answers."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from collections.abc import Sequence


LITERAL_CHECK_VERSION = "v2"

_CITATION_RE = re.compile(r"\[[^\[\]\r\n]{1,200}:\d+\]")
_DIMENSION_QUOTE_RE = re.compile(r'(?<=\d)["\u201d\u2033]')
_TOKEN_RE = re.compile(r"\d+(?:\.\d+)?|[a-z]+|[+/]")
_RATIO_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*$")
_CONTRACTIONS = {
    "can't": "cannot",
    "cannot": "cannot",
    "doesn't": "does not",
    "don't": "do not",
    "isn't": "is not",
    "aren't": "are not",
    "wasn't": "was not",
    "weren't": "were not",
    "won't": "will not",
}
_NEGATION_TOKENS = {"cannot", "neither", "never", "no", "not", "unsupported", "without"}
_NEGATIVE_EXPECTATION_TOKENS = _NEGATION_TOKENS | {"fail", "fails", "failed"}
_POLARITY_TOKENS = {
    "allow",
    "allowed",
    "allows",
    "available",
    "include",
    "included",
    "includes",
    "provide",
    "provided",
    "provides",
    "support",
    "supported",
    "supports",
}


@dataclass(frozen=True)
class LiteralCheckResult:
    """Result of checking required and forbidden answer content."""

    missing_must_include: tuple[str, ...]
    present_must_not_include: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.missing_must_include and not self.present_must_not_include


def evaluate_literal_checks(
    answer: str,
    must_include: Sequence[str],
    must_not_include: Sequence[str],
) -> LiteralCheckResult:
    """Evaluate answer requirements without using broad fuzzy similarity."""

    if not isinstance(answer, str):
        raise TypeError("answer must be a string")
    required = _validate_requirements("must_include", must_include)
    forbidden = _validate_requirements("must_not_include", must_not_include)
    answer_tokens = _tokenize(answer)

    missing = tuple(
        requirement
        for requirement in required
        if not _required_content_is_present(answer_tokens, requirement)
    )
    present_forbidden = tuple(
        requirement
        for requirement in forbidden
        if _forbidden_claim_is_present(answer_tokens, requirement)
    )
    return LiteralCheckResult(
        missing_must_include=missing,
        present_must_not_include=present_forbidden,
    )


def _validate_requirements(name: str, values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise TypeError(f"{name} must be a sequence of strings")
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} entries must be non-empty strings")
        normalized.append(value)
    return tuple(normalized)


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = _CITATION_RE.sub(" ", normalized)
    normalized = _DIMENSION_QUOTE_RE.sub(" inch ", normalized)
    normalized = normalized.lower()
    for contraction, expansion in _CONTRACTIONS.items():
        normalized = normalized.replace(contraction, expansion)
    normalized = normalized.replace("\u00d7", " x ")
    normalized = re.sub(r"[\u2010-\u2015\u2212-]", " ", normalized)
    normalized = re.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", " ", normalized)
    return normalized


def _tokenize(text: str) -> tuple[str, ...]:
    return tuple(_TOKEN_RE.findall(_normalize_text(text)))


def _singular(token: str) -> str:
    if len(token) <= 3 or token.endswith(("is", "ss", "us")):
        return token
    if token.endswith("ies") and len(token) > 4:
        return f"{token[:-3]}y"
    if token.endswith("s"):
        return token[:-1]
    return token


def _tokens_equal(left: str, right: str) -> bool:
    return left == right or _singular(left) == _singular(right)


def _find_ordered_matches(
    answer_tokens: tuple[str, ...],
    expected_tokens: tuple[str, ...],
    *,
    max_gap: int = 2,
) -> tuple[tuple[int, ...], ...]:
    if not expected_tokens or not answer_tokens:
        return ()

    matches: list[tuple[int, ...]] = []
    for start, answer_token in enumerate(answer_tokens):
        if not _tokens_equal(answer_token, expected_tokens[0]):
            continue
        positions = [start]
        cursor = start + 1
        for expected_token in expected_tokens[1:]:
            stop = min(len(answer_tokens), cursor + max_gap + 1)
            position = next(
                (
                    index
                    for index in range(cursor, stop)
                    if _tokens_equal(answer_tokens[index], expected_token)
                ),
                None,
            )
            if position is None:
                break
            positions.append(position)
            cursor = position + 1
        if len(positions) == len(expected_tokens):
            matches.append(tuple(positions))
    return tuple(matches)


def _contains_negative_expectation(tokens: tuple[str, ...]) -> bool:
    return any(token in _NEGATIVE_EXPECTATION_TOKENS for token in tokens)


def _contains_polarity_assertion(tokens: tuple[str, ...]) -> bool:
    return any(token in _POLARITY_TOKENS for token in tokens)


def _match_is_negated(answer_tokens: tuple[str, ...], positions: tuple[int, ...]) -> bool:
    start = max(0, positions[0] - 3)
    stop = min(len(answer_tokens), positions[-1] + 4)
    return any(token in _NEGATION_TOKENS for token in answer_tokens[start:stop])


def _required_content_is_present(answer_tokens: tuple[str, ...], requirement: str) -> bool:
    expected_tokens = _tokenize(requirement)
    expects_negation = _contains_negative_expectation(expected_tokens)
    checks_polarity = _contains_polarity_assertion(expected_tokens)
    for positions in _find_ordered_matches(answer_tokens, expected_tokens):
        if expects_negation or not checks_polarity or not _match_is_negated(answer_tokens, positions):
            return True

    ratio = _RATIO_RE.fullmatch(_normalize_text(requirement))
    if ratio and _nearby_numeric_pair_is_present(answer_tokens, ratio.group(1), ratio.group(2)):
        return True

    if expected_tokens == ("no",):
        return _has_bare_negative_answer(answer_tokens)
    if expected_tokens == ("not", "supported"):
        return _has_bare_negative_answer(answer_tokens)
    return False


def _forbidden_claim_is_present(answer_tokens: tuple[str, ...], requirement: str) -> bool:
    expected_tokens = _tokenize(requirement)
    expects_negation = _contains_negative_expectation(expected_tokens)
    for positions in _find_ordered_matches(answer_tokens, expected_tokens, max_gap=0):
        if expects_negation or not _match_is_negated(answer_tokens, positions):
            return True
    return False


def _nearby_numeric_pair_is_present(
    answer_tokens: tuple[str, ...],
    first: str,
    second: str,
) -> bool:
    for index, token in enumerate(answer_tokens):
        if token != first:
            continue
        stop = min(len(answer_tokens), index + 6)
        if second in answer_tokens[index + 1 : stop]:
            return True
    return False


def _has_bare_negative_answer(answer_tokens: tuple[str, ...]) -> bool:
    if any(token in {"cannot", "unsupported"} for token in answer_tokens):
        return True
    return any(
        answer_tokens[index + 1] == "not"
        for index, token in enumerate(answer_tokens[:-1])
        if token in {"are", "do", "does", "is", "was", "were", "will"}
    )
