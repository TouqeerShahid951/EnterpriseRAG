"""Persistence contract for checkpoint references."""

from __future__ import annotations

from typing import Protocol
from datetime import datetime

from .models import CheckpointDescriptor


class CheckpointRepository(Protocol):
    def commit(
        self, descriptor: CheckpointDescriptor, *, run_token: str
    ) -> CheckpointDescriptor: ...

    def invalidate(self, descriptor: CheckpointDescriptor, *, run_token: str) -> bool: ...

    def get(
        self, *, job_id: str, stage_key: str, run_token: str | None = None
    ) -> CheckpointDescriptor | None: ...

    def list(self, *, job_id: str, stage_prefix: str) -> tuple[CheckpointDescriptor, ...]: ...

    def expired(self, *, before: datetime, limit: int) -> tuple[CheckpointDescriptor, ...]: ...

    def delete(self, *, job_id: str, stage_key: str) -> bool: ...
