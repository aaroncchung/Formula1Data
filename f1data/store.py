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
import re
import secrets
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

JSON_CONTENT_TYPE = "application/json; charset=utf-8"
# R2 takes up to about 5 GB in one PUT. A session's archive is about 14 MB.
SINGLE_PART_LIMIT_BYTES = 1024 * 1024 * 1024
_KEY_PART = re.compile(r"^[A-Za-z0-9._-]+$")
BINARY_CONTENT_TYPE = "application/octet-stream"
# The file a directory store's writers lock, and how long one waits for it.
# It is held for a comparison and a rename.
_DIRECTORY_LOCK = ".f1data-lock"
_DIRECTORY_LOCK_WAIT_SECONDS = 60.0


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

    Conditional writes hold for everything that writes to the directory:
    another instance of this class, another process. Each write takes a lock
    on a file in the root for the moment of its check and its rename, and the
    operating system releases that lock if the writer dies holding it. A
    scheduled run and one started by hand can therefore share a directory, as
    two publishers share the bucket (rule 2).
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    @contextmanager
    def _writing(self) -> Iterator[None]:
        """Hold the directory's lock. One writer at a time, whoever it is."""
        self.root.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + _DIRECTORY_LOCK_WAIT_SECONDS
        with (self.root / _DIRECTORY_LOCK).open("a+b") as handle:
            while not _try_lock(handle):
                if time.monotonic() > deadline:
                    raise TimeoutError(f"{self.root} has been locked by another writer for too long")
                time.sleep(0.005)
            try:
                yield
            finally:
                _unlock(handle)

    def _replace(self, key: str, temporary: Path, if_match: str | None, if_absent: bool) -> None:
        """Put a finished file in place under the lock, if the precondition still holds."""
        path = self._path(key)
        try:
            with self._writing():
                if if_match is not None or if_absent:
                    current = self.get(key)
                    _check_precondition(key, None if current is None else current.data, if_match, if_absent)
                os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _temporary(self, key: str) -> Path:
        # A name of its own: two threads of one process may write one key.
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path.with_name(f"{path.name}.{os.getpid()}-{secrets.token_hex(4)}.tmp")

    def _path(self, key: str) -> Path:
        # A key is slash-separated names of letters, digits, dots, hyphens and
        # underscores. That leaves out a drive letter ("D:/x" joined to a root
        # replaces the root on Windows), an alternate data stream, a backslash
        # and every other way a key could name something outside the root.
        parts = key.split("/")
        if any(part in {".", ".."} or not _KEY_PART.match(part) for part in parts) or parts[0] == _DIRECTORY_LOCK:
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
        if if_match is not None and if_absent:
            raise ValueError("if_match and if_absent cannot be combined")
        # Written in full beside its place first, so the lock is held only
        # for the check and the rename, and a reader never sees half a file.
        temporary = self._temporary(key)
        temporary.write_bytes(data)
        self._replace(key, temporary, if_match, if_absent)
        return _etag(data)

    def put_file(self, key: str, path: Path, *, content_type: str = BINARY_CONTENT_TYPE) -> None:
        temporary = self._temporary(key)
        with Path(path).open("rb") as source, temporary.open("wb") as sink:
            while chunk := source.read(1024 * 1024):
                sink.write(chunk)
        self._replace(key, temporary, None, False)

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
        # Only the directory the prefix names is walked. A prefix ends in a
        # directory or part-way into a name, so the walk starts at whatever
        # comes before its last slash. Walking the whole store for every
        # listing made a run over many sessions visit every published file
        # once for each of them.
        directory = prefix.rsplit("/", 1)[0] if "/" in prefix else ""
        start = self._path(directory) if directory else self.root
        if not start.is_dir():
            return
        keys = sorted(
            path.relative_to(self.root).as_posix()
            for path in start.rglob("*")
            if path.is_file() and not path.name.endswith(".tmp") and path.name != _DIRECTORY_LOCK
        )
        for key in keys:
            if key.startswith(prefix):
                path = self._path(key)
                yield ObjectInfo(key, path.stat().st_size, file_etag(path))


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
        from boto3.s3.transfer import TransferConfig

        # In one piece up to the size of any snapshot, so that the object's
        # ETag is the MD5 of its bytes like every other object's. A multipart
        # upload gets an ETag that says nothing about the content, and then a
        # copy cannot be checked without downloading it.
        self._client.upload_file(
            str(path),
            self._bucket,
            self._key(key),
            ExtraArgs={"ContentType": content_type},
            Config=TransferConfig(multipart_threshold=SINGLE_PART_LIMIT_BYTES),
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


def _try_lock(handle: Any) -> bool:
    """Take an exclusive lock on an open file without waiting. False if another holds it.

    The lock belongs to this open file: another thread's own handle, or
    another process's, is refused while it is held, and the operating system
    drops it when the file is closed, however that comes about.
    """
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(handle: Any) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _check_precondition(key: str, current: bytes | None, if_match: str | None, if_absent: bool) -> None:
    if if_match is not None and if_absent:
        raise ValueError("if_match and if_absent cannot be combined")
    if if_absent and current is not None:
        raise PreconditionFailed(key)
    if if_match is not None and (current is None or _etag(current) != if_match):
        raise PreconditionFailed(key)


def content_etag(data: bytes) -> str:
    """The ETag every store gives an object written in one piece: its quoted MD5."""
    return f'"{hashlib.md5(data, usedforsecurity=False).hexdigest()}"'


_etag = content_etag


def file_etag(path: Path) -> str:
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
