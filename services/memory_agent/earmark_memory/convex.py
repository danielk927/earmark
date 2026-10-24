"""Read-only access to Earmark's Convex HTTP actions.

`ConvexReader` is the interface; `HttpConvexReader` talks to a real deployment over HTTPS
and `fixture.FixtureConvexReader` serves the same contract offline. Every response is parsed
with the `earmark_contracts` pydantic models, so anything off-contract is rejected here.
"""
from __future__ import annotations

import ipaddress
import logging
import time
from typing import Literal, Protocol, TypeVar
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ValidationError

from earmark_contracts import (
    AdherenceResponse,
    DailySummaryResponse,
    ErrorResponse,
    HistoryResponse,
    ObjectLookupResponse,
    ObjectsResponse,
)

from .config import CONVEX_TIMEOUT_S
from .household import HouseholdClock

log = logging.getLogger("earmark.memory.convex")

ErrorKind = Literal["timeout", "unreachable", "unauthorized", "not_found", "bad_request", "bad_response", "http_error"]
M = TypeVar("M", bound=BaseModel)
SECRET_HEADER = "X-Earmark-Secret"


class ConvexError(Exception):
    """A read failed. `str(err)` is safe to show a user and to log (it never contains secrets)."""

    def __init__(self, kind: ErrorKind, message: str):
        super().__init__(message)
        self.kind = kind


class ConvexReader(Protocol):
    source: str  # "convex" or "fixture", for logs

    async def clock(self) -> HouseholdClock: ...
    async def find_object(self, name: str) -> ObjectLookupResponse: ...
    async def list_objects(self) -> ObjectsResponse: ...
    async def history(self, object_id: str, since_t: float | None = None) -> HistoryResponse: ...
    async def adherence(self, date: str | None = None) -> AdherenceResponse: ...
    async def daily_summary(self, date: str | None = None) -> DailySummaryResponse: ...
    async def aclose(self) -> None: ...


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_site_url(url: str) -> str:
    """HTTPS only, so the shared secret never crosses a network in cleartext (plain HTTP allowed on loopback)."""
    parts = urlsplit(url)
    if parts.scheme == "https" and parts.hostname:
        return url.rstrip("/")
    if parts.scheme == "http" and parts.hostname and _is_loopback(parts.hostname):
        return url.rstrip("/")
    raise ValueError(
        f"CONVEX_SITE_URL must be an https:// URL (your deployment's .convex.site URL); got {url!r}. "
        "Plain http:// is only allowed for localhost."
    )


class HttpConvexReader:
    source = "convex"

    def __init__(
        self,
        site_url: str,
        read_secret: str,
        *,
        timeout_s: float = CONVEX_TIMEOUT_S,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if not read_secret:
            raise ValueError("EARMARK_READ_SECRET is required to call Convex")
        self._base = validate_site_url(site_url)
        self._timeout_s = timeout_s
        self._client = httpx.AsyncClient(
            base_url=self._base,
            headers={SECRET_HEADER: read_secret, "Accept": "application/json"},
            timeout=httpx.Timeout(timeout_s, connect=min(timeout_s, 3.0)),
            transport=transport,
            follow_redirects=False,
        )
        self._timezone: str | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, str | None], model: type[M]) -> M:
        query = {k: v for k, v in params.items() if v is not None}
        started = time.perf_counter()
        try:
            resp = await self._client.get(path, params=query)
        except httpx.TimeoutException as exc:
            raise ConvexError("timeout", f"Earmark's records did not answer within {self._timeout_s:g} s") from exc
        except httpx.TransportError as exc:
            raise ConvexError("unreachable", f"Earmark's records are unreachable ({type(exc).__name__})") from exc
        ms = (time.perf_counter() - started) * 1000
        log.debug("GET %s %s -> %d in %.0f ms", path, query, resp.status_code, ms)

        if resp.status_code != 200:
            detail = _error_detail(resp)
            if resp.status_code in (401, 403):
                raise ConvexError("unauthorized", "Convex rejected the read secret (check EARMARK_READ_SECRET)")
            if resp.status_code == 404:
                raise ConvexError("not_found", detail or "not found")
            if resp.status_code == 400:
                raise ConvexError("bad_request", detail or "bad request")
            raise ConvexError("http_error", f"Convex returned HTTP {resp.status_code}" + (f": {detail}" if detail else ""))
        try:
            return model.model_validate(resp.json())
        except ValueError as exc:  # JSONDecodeError and pydantic ValidationError are both ValueErrors
            what = "an off-contract response" if isinstance(exc, ValidationError) else "a non-JSON response"
            raise ConvexError("bad_response", f"Convex sent {what} for {path}") from exc

    async def clock(self) -> HouseholdClock:
        """Household time. The timezone comes from Convex once, then the local clock supplies "now"."""
        if self._timezone is None:
            self._timezone = (await self.adherence(None)).timezone
        return HouseholdClock(now_t=time.time(), timezone=self._timezone)

    async def find_object(self, name: str) -> ObjectLookupResponse:
        return await self._get("/api/object", {"name": name}, ObjectLookupResponse)

    async def list_objects(self) -> ObjectsResponse:
        return await self._get("/api/objects", {}, ObjectsResponse)

    async def history(self, object_id: str, since_t: float | None = None) -> HistoryResponse:
        since = None if since_t is None else f"{since_t:.3f}".rstrip("0").rstrip(".")
        return await self._get("/api/history", {"objectId": object_id, "since": since}, HistoryResponse)

    async def adherence(self, date: str | None = None) -> AdherenceResponse:
        return await self._get("/api/adherence", {"date": date}, AdherenceResponse)

    async def daily_summary(self, date: str | None = None) -> DailySummaryResponse:
        return await self._get("/api/daily-summary", {"date": date}, DailySummaryResponse)


def _error_detail(resp: httpx.Response) -> str | None:
    """The `error` string of a contract error body, if the body is one (bodies may be plain text)."""
    try:
        return ErrorResponse.model_validate(resp.json()).error
    except ValueError:
        return None
