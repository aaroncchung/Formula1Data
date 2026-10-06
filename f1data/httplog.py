"""Record every HTTP request a fetch makes, with its status.

FastF1 turns a failed feed into ``None`` and then into an empty table, and logs
no status on the way (``fastf1/_api.py``, ``fetch_page``). A refusal by F1 and a
session F1 does not hold therefore look the same from the outside. Recording at
``requests.Session.send`` sees each request FastF1 actually puts on the wire:
its two-level cache answers above this point, so a cached feed leaves no entry.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlsplit

import requests

# Enough to tell a CDN refusal from an origin error without keeping a response.
_DIAGNOSTIC_HEADERS = ("server", "x-cache", "x-amz-cf-pop", "cf-mitigated")
_BODY_EXCERPT_CHARS = 200


@dataclass(frozen=True)
class HttpRecord:
    method: str
    host: str
    path: str
    status: int | None
    elapsed_ms: int
    size_bytes: int | None = None
    error: str | None = None
    headers: dict[str, str] | None = None
    body_excerpt: str | None = None

    @property
    def failed(self) -> bool:
        return self.status is None or self.status >= 400


class ForbiddenHostError(RuntimeError):
    """A request was about to go to a host this stage must not contact."""


class HttpRecorder:
    """Context manager that records requests made through ``requests``.

    ``forbid_hosts`` turns it into a guard as well: a request to one of those
    hosts is refused before it is sent and kept in ``forbidden``. FastF1
    swallows the exception and carries on with an empty feed, so the caller has
    to check ``forbidden`` afterwards. ``forbid_all`` refuses every request,
    whatever its host.
    """

    def __init__(self, forbid_hosts: frozenset[str] = frozenset(), forbid_all: bool = False) -> None:
        self.records: list[HttpRecord] = []
        self.forbidden: list[str] = []
        self._forbid_hosts = forbid_hosts
        self._forbid_all = forbid_all
        self._original_send: Any = None

    def __enter__(self) -> "HttpRecorder":
        if self._original_send is not None:
            raise RuntimeError("HttpRecorder is already active")
        original = requests.Session.send
        recorder = self

        def send(session: requests.Session, request: requests.PreparedRequest, **kwargs: Any):
            host = urlsplit(request.url or "").netloc
            if recorder._forbid_all or host in recorder._forbid_hosts:
                recorder.forbidden.append(request.url or host)
                raise ForbiddenHostError(f"This stage must not contact {host}")
            started = time.perf_counter()
            try:
                response = original(session, request, **kwargs)
            except Exception as exc:
                recorder._record(request, started, error=f"{type(exc).__name__}: {exc}")
                raise
            recorder._record(request, started, response=response)
            return response

        self._original_send = original
        requests.Session.send = send  # type: ignore[method-assign]
        return self

    def __exit__(self, *exc_info: object) -> None:
        requests.Session.send = self._original_send  # type: ignore[method-assign]
        self._original_send = None

    def _record(
        self,
        request: requests.PreparedRequest,
        started: float,
        response: requests.Response | None = None,
        error: str | None = None,
    ) -> None:
        parts = urlsplit(request.url or "")
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        status = response.status_code if response is not None else None
        headers = None
        body_excerpt = None
        size_bytes = None
        if response is not None:
            declared = response.headers.get("content-length")
            size_bytes = int(declared) if declared and declared.isdigit() else None
            if response.status_code >= 400:
                headers = {
                    name: response.headers[name]
                    for name in _DIAGNOSTIC_HEADERS
                    if name in response.headers
                }
                body_excerpt = _excerpt(response)
        self.records.append(
            HttpRecord(
                method=request.method or "",
                host=parts.netloc,
                path=parts.path,
                status=status,
                elapsed_ms=elapsed_ms,
                size_bytes=size_bytes,
                error=error,
                headers=headers,
                body_excerpt=body_excerpt,
            )
        )

    @property
    def failures(self) -> list[HttpRecord]:
        return [record for record in self.records if record.failed]

    def summary(self) -> dict[str, dict[str, int]]:
        """Request counts by host, then by status (or ``error``)."""
        counts: dict[str, Counter[str]] = {}
        for record in self.records:
            outcome = str(record.status) if record.status is not None else "error"
            counts.setdefault(record.host, Counter())[outcome] += 1
        return {host: dict(sorted(by_status.items())) for host, by_status in sorted(counts.items())}

    def to_json(self) -> list[dict[str, Any]]:
        return [_compact(record) for record in self.records]

    def failure_kinds(self) -> list[dict[str, Any]]:
        """Distinct failures with a count, leaving out the path and the timing.

        A refused session fails every feed the same way; sixty identical lines
        say no more than one.
        """
        kinds: dict[str, dict[str, Any]] = {}
        for record in self.failures:
            kind = _compact(record)
            for varying in ("path", "elapsed_ms", "size_bytes"):
                kind.pop(varying, None)
            key = repr(sorted(kind.items(), key=lambda item: item[0]))
            kinds.setdefault(key, {**kind, "count": 0, "example_path": record.path})["count"] += 1
        return list(kinds.values())


def _compact(record: HttpRecord) -> dict[str, Any]:
    return {key: value for key, value in asdict(record).items() if value is not None}


def _excerpt(response: requests.Response) -> str | None:
    try:
        text = response.text
    except Exception:
        return None
    text = " ".join(text.split())
    return text[:_BODY_EXCERPT_CHARS] or None
