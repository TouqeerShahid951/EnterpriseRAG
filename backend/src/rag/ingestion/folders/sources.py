"""Ports and value objects for scheduled folder-ingestion sources."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class SourceObject:
    bucket: str
    object_name: str
    size_bytes: int

    @property
    def source_path(self) -> str:
        return self.object_name

    @property
    def filename(self) -> str:
        return self.object_name.rsplit("/", 1)[-1] or self.object_name

    @property
    def object_path(self) -> str:
        return f"minio://{self.bucket}/{self.object_name}"


@dataclass(frozen=True)
class LocalFolderObject:
    root_path: str
    relative_path: str
    size_bytes: int

    @property
    def source_path(self) -> str:
        return self.relative_path

    @property
    def filename(self) -> str:
        return self.relative_path.rsplit("/", 1)[-1] or self.relative_path


@dataclass(frozen=True)
class LocalFolderDirectory:
    name: str
    path: str
    has_children: bool


class MinioPrefixSource(Protocol):
    def list_objects(self, *, bucket: str, prefix: str) -> list[SourceObject]: ...

    def read_object(self, *, bucket: str, object_name: str) -> bytes: ...


class LocalFolderSource(Protocol):
    def resolve_root_path(self, value: str) -> str: ...

    def list_objects(self, *, root_path: str) -> list[LocalFolderObject]: ...

    def read_object(self, *, root_path: str, relative_path: str) -> bytes: ...

    def list_directories(
        self,
        *,
        root_path: str,
        current_path: str | None = None,
    ) -> tuple[Path, Path, Path | None, list[LocalFolderDirectory]]: ...


def list_local_folder_directories(
    *,
    source: LocalFolderSource,
    root_path: str,
    current_path: str | None = None,
) -> tuple[Path, Path, Path | None, list[LocalFolderDirectory]]:
    """List directories through the source port without exposing its adapter."""

    return source.list_directories(root_path=root_path, current_path=current_path)
