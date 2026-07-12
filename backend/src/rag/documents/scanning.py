"""Malware-scanning contract for uploaded document source files."""

from __future__ import annotations

from typing import Protocol


class ScannerUnavailableError(RuntimeError):
    pass


class MalwareDetectedError(RuntimeError):
    pass


class FileScanner(Protocol):
    def scan(self, content: bytes) -> None: ...
