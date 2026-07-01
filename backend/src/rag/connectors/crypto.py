"""Encrypted-at-rest connector secret envelope helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from typing import Any

try:  # pragma: no cover - exercised when production dependency is installed.
    from cryptography.fernet import Fernet, InvalidToken
except Exception:  # pragma: no cover - fallback is covered by unit tests.
    Fernet = None  # type: ignore[assignment]

    class InvalidToken(Exception):
        pass


@dataclass(frozen=True)
class SecretKey:
    key_id: str
    value: bytes


def keyring_from_settings(primary: str, ring: str = "") -> list[SecretKey]:
    values = [primary, *[part.strip() for part in ring.split(",") if part.strip()]]
    keys: list[SecretKey] = []
    for index, value in enumerate(values):
        cleaned = value.strip()
        if not cleaned:
            continue
        keys.append(SecretKey(key_id=f"k{index}", value=cleaned.encode("utf-8")))
    if not keys:
        raise ValueError("CONNECTOR_SECRETS_KEY must be configured")
    return keys


def encrypt_secret(payload: dict[str, Any], keys: list[SecretKey]) -> str:
    if not keys:
        raise ValueError("connector secret keyring is empty")
    plaintext = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    key = keys[0]
    if Fernet is not None:
        token = Fernet(_fernet_key(key.value)).encrypt(plaintext).decode("ascii")
        return f"fernet:v1:{key.key_id}:{token}"
    nonce = secrets.token_bytes(16)
    ciphertext = _xor(plaintext, _stream_key(key.value, nonce, len(plaintext)))
    tag = hmac.new(_mac_key(key.value), b"std:v1:" + key.key_id.encode("ascii") + nonce + ciphertext, hashlib.sha256).digest()
    token = base64.urlsafe_b64encode(nonce + ciphertext + tag).decode("ascii")
    return f"std:v1:{key.key_id}:{token}"


def decrypt_secret(envelope: str, keys: list[SecretKey]) -> dict[str, Any]:
    parts = envelope.split(":", 3)
    if len(parts) != 4:
        raise ValueError("connector secret envelope is invalid")
    scheme, version, key_id, token = parts
    if version != "v1":
        raise ValueError("connector secret envelope version is unsupported")
    ordered = _candidate_keys(keys, key_id)
    last_error: Exception | None = None
    for key in ordered:
        try:
            plaintext = _decrypt_with_key(scheme, token, key_id, key)
            value = json.loads(plaintext.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("connector secret payload must be an object")
            return value
        except Exception as exc:
            last_error = exc
            continue
    raise ValueError("connector secret could not be decrypted") from last_error


def redact_secrets(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: "********" for key in payload}


def _decrypt_with_key(scheme: str, token: str, key_id: str, key: SecretKey) -> bytes:
    if scheme == "fernet":
        if Fernet is None:
            raise ValueError("cryptography is required to decrypt Fernet connector secrets")
        try:
            return Fernet(_fernet_key(key.value)).decrypt(token.encode("ascii"))
        except InvalidToken as exc:
            raise ValueError("invalid connector secret token") from exc
    if scheme == "std":
        raw = base64.urlsafe_b64decode(token.encode("ascii"))
        if len(raw) < 16 + 32:
            raise ValueError("connector secret token is too short")
        nonce = raw[:16]
        tag = raw[-32:]
        ciphertext = raw[16:-32]
        expected = hmac.new(_mac_key(key.value), b"std:v1:" + key_id.encode("ascii") + nonce + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise ValueError("connector secret authentication failed")
        return _xor(ciphertext, _stream_key(key.value, nonce, len(ciphertext)))
    raise ValueError("connector secret envelope scheme is unsupported")


def _candidate_keys(keys: list[SecretKey], key_id: str) -> list[SecretKey]:
    preferred = [key for key in keys if key.key_id == key_id]
    fallback = [key for key in keys if key.key_id != key_id]
    return [*preferred, *fallback]


def _fernet_key(value: bytes) -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256(value).digest())


def _stream_key(value: bytes, nonce: bytes, length: int) -> bytes:
    key = _enc_key(value)
    output = bytearray()
    counter = 0
    while len(output) < length:
        output.extend(hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest())
        counter += 1
    return bytes(output[:length])


def _xor(left: bytes, right: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(left, right))


def _enc_key(value: bytes) -> bytes:
    return hashlib.sha256(b"connector-secret-encryption:" + value).digest()


def _mac_key(value: bytes) -> bytes:
    return hashlib.sha256(b"connector-secret-authentication:" + value).digest()
