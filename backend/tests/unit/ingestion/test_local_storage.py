import io
import os
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.ingestion.contracts import StorageKey
from app.ingestion.errors import IngestionErrorCode, ObjectStorageError
from app.ingestion.limits import IngestionLimits
from app.ingestion.storage import LocalObjectStorage


def generated_key() -> StorageKey:
    return StorageKey.generate(uuid4(), uuid4(), uuid4())


def test_streaming_write_is_atomic_private_and_hashes_content(tmp_path: object) -> None:
    storage = LocalObjectStorage(tmp_path)  # type: ignore[arg-type]
    key = generated_key()
    data = b"synthetic document bytes"

    stored = storage.put_stream(key, io.BytesIO(data))

    assert stored.key == key
    assert stored.size_bytes == len(data)
    assert storage.read(key) == data
    assert storage.exists(key)
    path = storage.root.joinpath(*key.value.split("/"))
    assert path.stat().st_mode & 0o777 == 0o600
    assert not list(path.parent.glob(".staging-*"))


def test_collision_does_not_overwrite_existing_object(tmp_path: object) -> None:
    storage = LocalObjectStorage(tmp_path)  # type: ignore[arg-type]
    key = generated_key()
    storage.put_bytes(key, b"first")

    with pytest.raises(ObjectStorageError) as captured:
        storage.put_bytes(key, b"second")

    assert captured.value.code == IngestionErrorCode.STORAGE_CONFLICT
    assert storage.read(key) == b"first"


def test_oversized_stream_is_removed_without_partial_object(tmp_path: object) -> None:
    storage = LocalObjectStorage(
        tmp_path,  # type: ignore[arg-type]
        IngestionLimits(upload_bytes=4, stream_chunk_bytes=2),
    )
    key = generated_key()

    with pytest.raises(ObjectStorageError) as captured:
        storage.put_stream(key, io.BytesIO(b"12345"))

    assert captured.value.code == IngestionErrorCode.FILE_TOO_LARGE
    assert not storage.exists(key)


def test_delete_is_idempotent_and_removes_object(tmp_path: object) -> None:
    storage = LocalObjectStorage(tmp_path)  # type: ignore[arg-type]
    key = generated_key()
    storage.put_bytes(key, b"delete me")

    storage.delete(key)
    storage.delete(key)

    assert not storage.exists(key)


def test_key_rejects_paths_and_symlink_cannot_escape_root(tmp_path: object) -> None:
    with pytest.raises(ValidationError):
        StorageKey(value="../../outside")

    storage = LocalObjectStorage(tmp_path)  # type: ignore[arg-type]
    key = generated_key()
    target = storage.root.joinpath(*key.value.split("/"))
    target.parent.mkdir(parents=True)
    outside = storage.root.parent / "outside-object"
    outside.write_bytes(b"secret")
    os.symlink(outside, target)

    with pytest.raises(ObjectStorageError) as captured:
        storage.read(key)

    assert captured.value.code == IngestionErrorCode.STORAGE_KEY_INVALID
    assert outside.read_bytes() == b"secret"
