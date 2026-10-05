"""Open the store a command was asked for, from the environment.

``--store`` takes a directory path, or ``r2`` for the bucket. R2 is reached
through its S3 API with:

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
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from f1data.store import DirectoryStore, ObjectStore, S3Store

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
    """Read ``KEY=VALUE`` lines into the environment without replacing what is set."""
    environ = os.environ if environ is None else environ
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if name and name not in environ:
            environ[name] = value


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
    """``r2`` for the bucket in the environment, anything else is a directory."""
    if spec.strip().lower() == "r2":
        return open_r2_store(r2_settings(environ), prefix=prefix)
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
