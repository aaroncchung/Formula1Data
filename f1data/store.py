"""The one store, with writes that can be made conditional.

Everything that changes in place (a pointer, the index, standings) is written
against the version that was read, so two publishers cannot silently overwrite
each other: the store refuses the second write and the loser decides again
(docs/architecture-review-findings.md, section 6, rule 2). The old publisher
went through one ``wrangler`` process per object, which cannot tell "not
found" from "read failed" (AR-04); here a missing object is ``None`` and every
other failure raises.

Three implementations share one contract, checked by one test suite:
``MemoryStore`` for tests, ``DirectoryStore`` for local development and for
spooling a fetch before upload, and ``S3Store`` for R2.
"""

from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

JSON_CONTENT_TYPE = "application/json; charset=utf-8"
BINARY_CONTENT_TYPE = "application/octet-stream"


class PreconditionFailed(Exception):
    """A conditional write lost: the object is not in the state the writer read."""


@dataclass(frozen=True)
class ObjectInfo:
    key: str
    size: int
    etag: str


@dataclass(frozen=True)
class StoredObject:
    key: str
    data: bytes
    etag: str


class ObjectStore(Protocol):
    def get(self, key: str) -> StoredObject | None:
        """The object and its version, or ``None`` when it does not exist."""

    def head(self, key: str) -> ObjectInfo | None: ...

    def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str = JSON_CONTENT_TYPE,
        cache_control: str | None = None,
        if_match: str | None = None,
        if_absent: bool = False,
    ) -> str:
        """Write and return the new ETag.

        ``if_match`` writes only over the version with that ETag; ``if_absent``
        writes only when nothing is there. Either raises ``PreconditionFailed``
        when the condition does not hold.
        """

    def put_file(self, key: str, path: Path, *, content_type: str = BINARY_CONTENT_TYPE) -> None:
        """Upload a file that may be too large to hold in memory. Unconditional."""

    def download_file(self, key: str, path: Path) -> bool:
        """Download to ``path``. ``False`` when the object does not exist."""

    def list(self, prefix: str) -> Iterator[ObjectInfo]: ...


class MemoryStore:
    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> StoredObject | None:
        with self._lock:
            data = self._objects.get(key)
        return None if data is None else StoredObject(key, data, _etag(data))

    def head(self, key: str) -> ObjectInfo | None:
        found = self.get(key)
        return None if found is None else ObjectInfo(key, len(found.data), found.etag)

    def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str = JSON_CONTENT_TYPE,
        cache_control: str | None = None,
        if_match: str | None = None,
        if_absent: bool = False,
    ) -> str:
        with self._lock:
            _check_precondition(key, self._objects.get(key), if_match, if_absent)
            self._objects[key] = bytes(data)
        return _etag(data)

    def put_file(self, key: str, path: Path, *, content_type: str = BINARY_CONTENT_TYPE) -> None:
        self.put(key, Path(path).read_bytes(), content_type=content_type)

    def download_file(self, key: str, path: Path) -> bool:
        found = self.get(key)
        if found is None:
            return False
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(found.data)
        return True

    def list(self, prefix: str) -> Iterator[ObjectInfo]:
        with self._lock:
            matching = sorted((key, data) for key, data in self._objects.items() if key.startswith(prefix))
        for key, data in matching:
            yield ObjectInfo(key, len(data), _etag(data))


class DirectoryStore:
    """Objects as files under a directory, with the key as the relative path.

    Conditional writes hold within one process. That is enough for what this is
    used for: the sample dataset, a local build, and a fetch waiting for upload.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._lock = threading.Lock()

    def _path(self, key: str) -> Path:
        parts = key.split("/")
        if not key or key.startswith("/") or any(part in {"", ".", ".."} for part in parts) or "\\" in key:
            raise ValueError(f"Invalid object key: {key!r}")
        return self.root.joinpath(*parts)

    def get(self, key: str) -> StoredObject | None:
        path = self._path(key)
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            return None
        return StoredObject(key, data, _etag(data))

    def head(self, key: str) -> ObjectInfo | None:
        found = self.get(key)
        return None if found is None else ObjectInfo(key, len(found.data), found.etag)

    def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str = JSON_CONTENT_TYPE,
        cache_control: str | None = None,
        if_match: str | None = None,
        if_absent: bool = False,
    ) -> str:
        path = self._path(key)
        with self._lock:
            current = self.get(key)
            _check_precondition(key, None if current is None else current.data, if_match, if_absent)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
            temporary.write_bytes(data)
            os.replace(temporary, path)
        return _etag(data)

    def put_file(self, key: str, path: Path, *, content_type: str = BINARY_CONTENT_TYPE) -> None:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f"{target.name}.{os.getpid()}.tmp")
        with Path(path).open("rb") as source, temporary.open("wb") as sink:
            while chunk := source.read(1024 * 1024):
                sink.write(chunk)
        os.replace(temporary, target)

    def download_file(self, key: str, path: Path) -> bool:
        source = self._path(key)
        if not source.is_file():
            return False
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as reader, Path(path).open("wb") as writer:
            while chunk := reader.read(1024 * 1024):
                writer.write(chunk)
        return True

    def list(self, prefix: str) -> Iterator[ObjectInfo]:
        if not self.root.is_dir():
            return
        keys = sorted(
            path.relative_to(self.root).as_posix()
            for path in self.root.rglob("*")
            if path.is_file() and not path.name.endswith(".tmp")
        )
        for key in keys:
            if key.startswith(prefix):
                path = self._path(key)
                yield ObjectInfo(key, path.stat().st_size, _file_etag(path))


class S3Store:
    """R2 through its S3-compatible API.

    ``prefix`` namespaces every key, so the contract tests can run against the
    real bucket without touching published data.
    """

    def __init__(self, client: Any, bucket: str, prefix: str = "") -> None:
        self._client = client
        self._bucket = bucket
        self._prefix = prefix

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def get(self, key: str) -> StoredObject | None:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=self._key(key))
        except Exception as exc:
            if _error_code(exc) in {"NoSuchKey", "404", "NotFound"}:
                return None
            raise
        with response["Body"] as body:
            data = body.read()
        return StoredObject(key, data, str(response["ETag"]))

    def head(self, key: str) -> ObjectInfo | None:
        try:
            response = self._client.head_object(Bucket=self._bucket, Key=self._key(key))
        except Exception as exc:
            if _error_code(exc) in {"NoSuchKey", "404", "NotFound"}:
                return None
            raise
        return ObjectInfo(key, int(response["ContentLength"]), str(response["ETag"]))

    def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str = JSON_CONTENT_TYPE,
        cache_control: str | None = None,
        if_match: str | None = None,
        if_absent: bool = False,
    ) -> str:
        if if_match is not None and if_absent:
            raise ValueError("if_match and if_absent cannot be combined")
        arguments: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": self._key(key),
            "Body": data,
            "ContentType": content_type,
        }
        if cache_control:
            arguments["CacheControl"] = cache_control
        if if_match is not None:
            arguments["IfMatch"] = if_match
        if if_absent:
            arguments["IfNoneMatch"] = "*"
        try:
            response = self._client.put_object(**arguments)
        except Exception as exc:
            # 412 is the condition failing. 409 is S3's answer when two
            # conditional writes to one key overlap; the loser has to read
            # again either way.
            if _error_code(exc) in {"PreconditionFailed", "412", "ConditionalRequestConflict", "409"}:
                raise PreconditionFailed(key) from exc
            raise
        return str(response["ETag"])

    def put_file(self, key: str, path: Path, *, content_type: str = BINARY_CONTENT_TYPE) -> None:
        self._client.upload_file(
            str(path), self._bucket, self._key(key), ExtraArgs={"ContentType": content_type}
        )

    def download_file(self, key: str, path: Path) -> bool:
        if self.head(key) is None:
            return False
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._client.download_file(self._bucket, self._key(key), str(path))
        return True

    def list(self, prefix: str) -> Iterator[ObjectInfo]:
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=self._key(prefix)):
            for item in page.get("Contents", []):
                yield ObjectInfo(
                    str(item["Key"])[len(self._prefix):], int(item["Size"]), str(item["ETag"])
                )

    def delete(self, key: str) -> None:
        """Only the contract tests delete, to clean up after themselves."""
        self._client.delete_object(Bucket=self._bucket, Key=self._key(key))


def _check_precondition(key: str, current: bytes | None, if_match: str | None, if_absent: bool) -> None:
    if if_match is not None and if_absent:
        raise ValueError("if_match and if_absent cannot be combined")
    if if_absent and current is not None:
        raise PreconditionFailed(key)
    if if_match is not None and (current is None or _etag(current) != if_match):
        raise PreconditionFailed(key)


def _etag(data: bytes) -> str:
    return f'"{hashlib.md5(data, usedforsecurity=False).hexdigest()}"'


def _file_etag(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return f'"{digest.hexdigest()}"'


def _error_code(exc: Exception) -> str | None:
    """The S3 error code of a botocore ``ClientError``, or ``None`` for anything else."""
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return None
    code = (response.get("Error") or {}).get("Code")
    return str(code) if code is not None else None
