"""Small HMAC token helper used until a dedicated auth library is introduced."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any


class TokenError(ValueError):
    pass


def create_token(
    *,
    secret_key: str,
    subject: str,
    email: str,
    account_type: str,
    group_paths: list[str],
    clearance_level: str,
    permission_version: int,
    token_type: str,
    ttl: timedelta,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "email": email,
        "account_type": account_type,
        "group_paths": group_paths,
        "clearance_level": clearance_level,
        "permission_version": permission_version,
        "typ": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "jti": secrets.token_urlsafe(16),
    }
    return _sign(payload, secret_key)


def decode_token(token: str, *, secret_key: str, expected_type: str) -> dict[str, Any]:
    try:
        header_text, payload_text, signature = token.split(".", 2)
    except ValueError as exc:
        raise TokenError("malformed token") from exc

    expected_signature = _signature(f"{header_text}.{payload_text}", secret_key)
    if not hmac.compare_digest(signature, expected_signature):
        raise TokenError("invalid token signature")

    try:
        header = json.loads(_decode(header_text).decode("utf-8"))
        payload = json.loads(_decode(payload_text).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise TokenError("invalid token payload") from exc

    if header.get("alg") != "HS256" or header.get("typ") != "JWT":
        raise TokenError("unsupported token header")
    if payload.get("typ") != expected_type:
        raise TokenError("unexpected token type")
    if int(payload.get("exp", 0)) < int(datetime.now(UTC).timestamp()):
        raise TokenError("expired token")
    return payload


def _sign(payload: dict[str, Any], secret_key: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_text = _encode(json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    payload_text = _encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signed_text = f"{header_text}.{payload_text}"
    return f"{signed_text}.{_signature(signed_text, secret_key)}"


def _signature(payload_text: str, secret_key: str) -> str:
    digest = hmac.new(secret_key.encode("utf-8"), payload_text.encode("ascii"), hashlib.sha256).digest()
    return _encode(digest)


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
