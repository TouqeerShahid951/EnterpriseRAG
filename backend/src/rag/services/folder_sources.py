"""Folder source adapters for scheduled ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..core.config import settings


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


class MinioPrefixSource:
    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        secure: bool,
    ) -> None:
        try:
            from minio import Minio
        except ImportError as exc:
            raise RuntimeError("minio package is required for MinIO folder sync") from exc
        self._client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)

    def list_objects(self, *, bucket: str, prefix: str) -> list[SourceObject]:
        objects = self._client.list_objects(bucket, prefix=prefix, recursive=True)
        return [
            SourceObject(bucket=bucket, object_name=item.object_name, size_bytes=int(item.size or 0))
            for item in objects
            if item.object_name and not item.object_name.endswith("/")
        ]

    def read_object(self, *, bucket: str, object_name: str) -> bytes:
        response = self._client.get_object(bucket, object_name)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()


def default_minio_prefix_source() -> MinioPrefixSource:
    return MinioPrefixSource(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


def get_minio_prefix_source() -> MinioPrefixSource:
    return default_minio_prefix_source()


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


class LocalFolderSource:
    def list_objects(self, *, root_path: str) -> list[LocalFolderObject]:
        root = resolve_local_folder_path(root_path)
        objects: list[LocalFolderObject] = []
        for item in root.rglob("*"):
            if item.is_symlink() or not item.is_file():
                continue
            try:
                stat = item.stat()
            except OSError:
                continue
            relative_path = item.relative_to(root).as_posix()
            objects.append(LocalFolderObject(root_path=str(root), relative_path=relative_path, size_bytes=int(stat.st_size)))
        return sorted(objects, key=lambda item: item.source_path)

    def read_object(self, *, root_path: str, relative_path: str) -> bytes:
        root = resolve_local_folder_path(root_path)
        target = (root / relative_path).resolve()
        if root != target and root not in target.parents:
            raise RuntimeError("local folder source path escaped the configured root")
        if target.is_symlink() or not target.is_file():
            raise RuntimeError("local folder source file is no longer readable")
        return target.read_bytes()


def resolve_local_folder_path(value: str) -> Path:
    path = Path(value.strip()).expanduser()
    if not path.is_absolute():
        path = path.resolve()
    else:
        path = path.resolve()
    if not path.exists() or not path.is_dir():
        raise RuntimeError("local folder source path must be an existing readable directory")
    return path


def list_local_folder_directories(*, root_path: str | None = None, current_path: str | None = None) -> tuple[Path, Path, Path | None, list[LocalFolderDirectory]]:
    root = resolve_local_folder_path(root_path or settings.folder_sources_root)
    current = root if not current_path else resolve_local_folder_path(current_path)
    if current != root and root not in current.parents:
        raise RuntimeError("local folder browser path escaped the configured root")

    parent = current.parent if current != root and (current.parent == root or root in current.parent.parents) else None
    directories: list[LocalFolderDirectory] = []
    for item in current.iterdir():
        try:
            if item.is_symlink() or not item.is_dir():
                continue
            directories.append(
                LocalFolderDirectory(
                    name=item.name,
                    path=str(item.resolve()),
                    has_children=_has_child_directory(item),
                )
            )
        except OSError:
            continue
    return root, current, parent, sorted(directories, key=lambda item: item.name.lower())


def _has_child_directory(path: Path) -> bool:
    try:
        return any(not child.is_symlink() and child.is_dir() for child in path.iterdir())
    except OSError:
        return False


def get_local_folder_source() -> LocalFolderSource:
    return LocalFolderSource()
