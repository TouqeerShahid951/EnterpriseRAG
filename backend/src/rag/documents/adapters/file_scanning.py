"""No-op and ClamAV adapters for uploaded document source files."""

from __future__ import annotations

import socket
import struct

from ..scanning import MalwareDetectedError, ScannerUnavailableError


class NoopFileScanner:
    def scan(self, content: bytes) -> None:
        _ = content


class ClamAvFileScanner:
    def __init__(self, *, host: str, port: int, timeout_seconds: float) -> None:
        self.host = host
        self.port = port
        self.timeout_seconds = timeout_seconds

    def scan(self, content: bytes) -> None:
        try:
            with socket.create_connection(
                (self.host, self.port), timeout=self.timeout_seconds
            ) as sock:
                sock.settimeout(self.timeout_seconds)
                sock.sendall(b"zINSTREAM\0")
                for index in range(0, len(content), 1024 * 1024):
                    chunk = content[index : index + 1024 * 1024]
                    sock.sendall(struct.pack(">I", len(chunk)))
                    sock.sendall(chunk)
                sock.sendall(struct.pack(">I", 0))
                response = sock.recv(4096).decode("utf-8", errors="replace")
        except OSError as exc:
            raise ScannerUnavailableError(str(exc)) from exc

        if "FOUND" in response:
            raise MalwareDetectedError(response.strip())
        if "OK" not in response:
            raise ScannerUnavailableError(
                response.strip() or "clamav returned an empty response"
            )
