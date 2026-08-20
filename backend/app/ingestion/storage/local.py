import hashlib
import io
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import BinaryIO, Never

from app.ingestion.contracts import StorageKey, StoredObject
from app.ingestion.errors import IngestionErrorCode, ObjectStorageError
from app.ingestion.limits import DEFAULT_LIMITS, IngestionLimits


def _raise(code: IngestionErrorCode) -> Never:
    raise ObjectStorageError(code, "Document storage operation failed.")


class LocalObjectStorage:
    """Development object storage with generated keys and path confinement."""

    def __init__(self, root: str | Path, limits: IngestionLimits = DEFAULT_LIMITS) -> None:
        self.root = Path(root).expanduser().resolve()
        self.limits = limits
        try:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.root.chmod(0o700)
        except OSError:
            _raise(IngestionErrorCode.STORAGE_UNAVAILABLE)

    def _path(self, key: StorageKey, *, create_parent: bool = False) -> Path:
        candidate = self.root.joinpath(*key.value.split("/"))
        try:
            if create_parent:
                candidate.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            resolved_parent = candidate.parent.resolve(strict=False)
            resolved_parent.relative_to(self.root)
            if candidate.is_symlink():
                _raise(IngestionErrorCode.STORAGE_KEY_INVALID)
        except (OSError, ValueError):
            _raise(IngestionErrorCode.STORAGE_KEY_INVALID)
        return candidate

    def put_stream(self, key: StorageKey, stream: BinaryIO) -> StoredObject:
        target = self._path(key, create_parent=True)
        temporary_path: Path | None = None
        digest = hashlib.sha256()
        size = 0
        try:
            descriptor, temporary_name = tempfile.mkstemp(prefix=".staging-", dir=target.parent)
            temporary_path = Path(temporary_name)
            os.chmod(temporary_path, 0o600)
            with os.fdopen(descriptor, "wb") as destination:
                while True:
                    chunk = stream.read(self.limits.stream_chunk_bytes)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > self.limits.upload_bytes:
                        _raise(IngestionErrorCode.FILE_TOO_LARGE)
                    digest.update(chunk)
                    destination.write(chunk)
                destination.flush()
                os.fsync(destination.fileno())
            if size == 0:
                _raise(IngestionErrorCode.MALFORMED_FILE)
            try:
                os.link(temporary_path, target)
            except FileExistsError:
                _raise(IngestionErrorCode.STORAGE_CONFLICT)
            temporary_path.unlink()
            temporary_path = None
            return StoredObject(key=key, size_bytes=size, sha256=digest.hexdigest())
        except ObjectStorageError:
            raise
        except OSError:
            _raise(IngestionErrorCode.STORAGE_UNAVAILABLE)
        finally:
            if temporary_path is not None:
                with suppress(OSError):
                    temporary_path.unlink(missing_ok=True)

    def put_bytes(self, key: StorageKey, data: bytes) -> StoredObject:
        return self.put_stream(key, io.BytesIO(data))

    def read(self, key: StorageKey) -> bytes:
        path = self._path(key)
        try:
            if not path.is_file() or path.is_symlink():
                _raise(IngestionErrorCode.STORAGE_UNAVAILABLE)
            data = path.read_bytes()
        except ObjectStorageError:
            raise
        except OSError:
            _raise(IngestionErrorCode.STORAGE_UNAVAILABLE)
        if len(data) > self.limits.upload_bytes:
            _raise(IngestionErrorCode.FILE_TOO_LARGE)
        return data

    def delete(self, key: StorageKey) -> None:
        path = self._path(key)
        try:
            if path.is_symlink():
                _raise(IngestionErrorCode.STORAGE_KEY_INVALID)
            path.unlink(missing_ok=True)
            parent = path.parent
            while parent != self.root:
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
        except ObjectStorageError:
            raise
        except OSError:
            _raise(IngestionErrorCode.STORAGE_UNAVAILABLE)

    def exists(self, key: StorageKey) -> bool:
        path = self._path(key)
        return path.is_file() and not path.is_symlink()
