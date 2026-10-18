"""Open the store a command was asked for, from the environment.

``--store`` takes a directory that exists, or ``r2`` for the bucket. R2 is
reached through its S3 API with:

    R2_BUCKET                 bucket name
    R2_ACCOUNT_ID             or CLOUDFLARE_ACCOUNT_ID
    R2_ACCESS_KEY_ID          an R2 API token's key pair ...
    R2_SECRET_ACCESS_KEY
    CLOUDFLARE_API_TOKEN      ... or a Cloudflare API token with R2 access

Cloudflare documents that an API token doubles as S3 credentials: its id is the
access key and the SHA-256 of its value is the secret. That lets a workflow
publish with the secret the repository already has.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from f1data.store import DirectoryStore, ObjectStore, S3Store

# Where a comment begins in a value that is not quoted.
_INLINE_COMMENT = re.compile(r"\s#")

_TOKEN_VERIFY_URLS = (
    "https://api.cloudflare.com/client/v4/user/tokens/verify",
    "https://api.cloudflare.com/client/v4/accounts/{account_id}/tokens/verify",
)


class ConfigError(RuntimeError):
    """The environment does not say how to reach the store."""


@dataclass(frozen=True)
class R2Settings:
    account_id: str
    bucket: str
    access_key_id: str
    secret_access_key: str

    @property
    def endpoint_url(self) -> str:
        return f"https://{self.account_id}.r2.cloudflarestorage.com"


def load_env_file(path: Path, environ: dict[str, str] | None = None) -> None:
    """Read ``KEY=VALUE`` lines into the environment without replacing what is set.

    A value in quotes is what is between them. One that is not ends where a
    ``#`` follows a space or a tab: what comes after is a comment. The file
    may begin with a byte order mark, which Windows PowerShell 5.1 writes
    with ``Out-File`` and ``Set-Content -Encoding utf8``: read as part of
    the first name, it made ``F1DATA_STORE`` a name nothing asks for.
    """
    environ = os.environ if environ is None else environ
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        value = _value(value)
        if name and name not in environ:
            environ[name] = value


def _value(written: str) -> str:
    """A value as ``.env`` gives it, from what follows the ``=``: between its quotes, or up to a comment."""
    quoted = written.strip()
    if quoted[:1] in ("'", '"'):
        end = quoted.find(quoted[0], 1)
        if end > 0:
            return quoted[1:end]
    # Looked for before the spaces after the `=` are taken off: in
    # `NAME= # none yet` the comment is all there is.
    comment = _INLINE_COMMENT.search(written)
    return (written[: comment.start()] if comment else written).strip()


def r2_settings(environ: Mapping[str, str] | None = None) -> R2Settings:
    environ = os.environ if environ is None else environ
    account_id = environ.get("R2_ACCOUNT_ID") or environ.get("CLOUDFLARE_ACCOUNT_ID")
    bucket = environ.get("R2_BUCKET")
    missing = [name for name, value in (("R2_ACCOUNT_ID", account_id), ("R2_BUCKET", bucket)) if not value]
    if missing:
        raise ConfigError(f"Set {' and '.join(missing)} to use the R2 store.")

    access_key_id = environ.get("R2_ACCESS_KEY_ID")
    secret_access_key = environ.get("R2_SECRET_ACCESS_KEY")
    if not (access_key_id and secret_access_key):
        token = environ.get("CLOUDFLARE_API_TOKEN")
        if not token:
            raise ConfigError(
                "Set R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY, or CLOUDFLARE_API_TOKEN, to use the R2 store."
            )
        access_key_id = _api_token_id(token, str(account_id))
        secret_access_key = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return R2Settings(str(account_id), str(bucket), access_key_id, secret_access_key)


def open_store(spec: str, environ: Mapping[str, str] | None = None, prefix: str = "") -> ObjectStore:
    """``r2`` for the bucket in the environment, or a directory that exists.

    A directory store is made on its first write, so any other name used to
    be a store: ``r2  # the bucket``, from a ``.env`` that a comment had been
    added to, archived every fetch into a new directory of that name, and
    every build published there. A directory store has to be made first.
    """
    if spec.strip().lower() == "r2":
        return open_r2_store(r2_settings(environ), prefix=prefix)
    if not Path(spec).is_dir():
        raise ConfigError(
            f"The store {spec!r} is neither r2 nor a directory that exists. For a new directory store, make "
            "the directory first."
        )
    return DirectoryStore(Path(spec))


def open_r2_store(settings: R2Settings, prefix: str = "") -> S3Store:
    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        endpoint_url=settings.endpoint_url,
        aws_access_key_id=settings.access_key_id,
        aws_secret_access_key=settings.secret_access_key,
        region_name="auto",
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 5, "mode": "standard"},
            # A generation is uploaded by a pool of threads sharing this client.
            max_pool_connections=32,
            # boto3 adds a CRC32 trailer to every upload by default since 1.36;
            # R2 asks S3 clients to send checksums only when an operation
            # requires one.
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )
    return S3Store(client, settings.bucket, prefix=prefix)


def _api_token_id(token: str, account_id: str) -> str:
    import requests

    errors = []
    for template in _TOKEN_VERIFY_URLS:
        url = template.format(account_id=account_id)
        response = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        token_id = (payload.get("result") or {}).get("id")
        if response.ok and token_id:
            return str(token_id)
        errors.append(f"{url.rsplit('/client/v4', 1)[-1]}: HTTP {response.status_code}")
    raise ConfigError(f"Cloudflare did not verify CLOUDFLARE_API_TOKEN ({'; '.join(errors)}).")
