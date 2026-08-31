"""Stage 1: the polite fetcher.

Section 15.2 states the operating rule and the reason for it: identify the crawler honestly with
a contact address, cache aggressively so the same page is never fetched twice, back off
immediately on 429 or 503, and respect robots.txt. The goal is to be the least burdensome
consumer of these systems, because access is the business and burning it is unrecoverable.

Three things here are load bearing rather than decoration.

``RobotsCache`` fetches and honours robots.txt per host, and a disallowed path raises rather
than being worked around. There is no override flag. A flag that exists gets used.

``HostRateLimiter`` is per host, not global. One county's slow portal must not throttle the
other eleven, and a shared limiter would make that happen.

Every attempt lands in ``fetch_attempt`` whether it succeeded or not, and repeated failures land
in ``dead_letter``. Government sites go down constantly; the failure mode that matters is not
an outage, it is an outage nobody noticed.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from auspice.config import Settings, get_settings
from auspice.db import schema
from auspice.errors import ConfigurationError, FetchError, RateLimitedError
from auspice.logging import get_logger
from auspice.pipeline.ingest.store import RawStore, StoredObject, get_raw_store

log = get_logger(__name__, _stage="ingest")

RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


@dataclass(slots=True)
class FetchOutcome:
    url: str
    status_code: int | None
    outcome: str
    duration_ms: int
    stored: StoredObject | None = None
    error: str | None = None
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.outcome in {"stored", "unchanged"}


class RobotsCache:
    """One robots.txt per host, fetched once, honoured always."""

    def __init__(self, *, user_agent: str, timeout: float) -> None:
        self._user_agent = user_agent
        self._timeout = timeout
        self._parsers: dict[str, RobotFileParser | None] = {}
        self._crawl_delay: dict[str, float | None] = {}

    def _origin(self, url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    async def _load(self, origin: str, client: httpx.AsyncClient) -> RobotFileParser | None:
        parser = RobotFileParser()
        parser.set_url(f"{origin}/robots.txt")
        try:
            response = await client.get(f"{origin}/robots.txt", timeout=self._timeout)
        except httpx.HTTPError as exc:
            log.debug("robots unreachable, treating as permissive", origin=origin, error=str(exc))
            return None
        if response.status_code == 404:
            # No robots.txt means no restrictions. That is the standard reading.
            return None
        if response.status_code >= 400:
            log.debug(
                "robots returned an error, treating as permissive",
                origin=origin,
                status=response.status_code,
            )
            return None
        parser.parse(response.text.splitlines())
        return parser

    async def allowed(self, url: str, client: httpx.AsyncClient) -> bool:
        origin = self._origin(url)
        if origin not in self._parsers:
            parser = await self._load(origin, client)
            self._parsers[origin] = parser
            raw_delay = parser.crawl_delay(self._user_agent) if parser is not None else None
            self._crawl_delay[origin] = float(raw_delay) if raw_delay else None
        parser = self._parsers[origin]
        if parser is None:
            return True
        return parser.can_fetch(self._user_agent, url)

    def crawl_delay(self, url: str) -> float | None:
        delay = self._crawl_delay.get(self._origin(url))
        return float(delay) if delay is not None else None


class HostRateLimiter:
    """Per host token spacing. Per host on purpose: see the module docstring."""

    def __init__(self, requests_per_minute: int) -> None:
        self._min_interval = 60.0 / max(requests_per_minute, 1)
        self._last: dict[str, float] = defaultdict(float)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._overrides: dict[str, float] = {}

    def set_minimum_interval(self, host: str, seconds: float) -> None:
        """Honour a Crawl-delay directive that is slower than our own default."""
        if seconds > self._min_interval:
            self._overrides[host] = seconds

    async def acquire(self, url: str) -> None:
        host = urlparse(url).netloc
        interval = self._overrides.get(host, self._min_interval)
        async with self._locks[host]:
            wait = self._last[host] + interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last[host] = time.monotonic()


def _log_retry(state: RetryCallState) -> None:
    log.warning(
        "retrying fetch",
        attempt=state.attempt_number,
        error=str(state.outcome.exception()) if state.outcome else None,
    )


class Fetcher:
    """The only thing in the system that makes an outbound request to a government site."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        store: RawStore | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        if not self.settings.crawler_contact:
            raise ConfigurationError(
                "AUSPICE_CRAWLER_CONTACT is not set. Section 15.2 requires the crawler to "
                "identify itself with a contact address before it touches a government site."
            )
        self.store = store or get_raw_store(self.settings)
        self._robots = RobotsCache(
            user_agent=self.settings.crawler_user_agent,
            timeout=self.settings.crawler_timeout_seconds,
        )
        self._limiter = HostRateLimiter(self.settings.crawler_requests_per_minute)
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=self.settings.crawler_timeout_seconds,
            follow_redirects=True,
            http2=True,
            headers={
                "User-Agent": self.settings.crawler_user_agent,
                "From": self.settings.crawler_contact,
                "Accept-Encoding": "gzip, deflate",
            },
        )

    async def __aenter__(self) -> Fetcher:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def fetch(
        self,
        url: str,
        *,
        jurisdiction_id: int | None = None,
        source_id: int | None = None,
        kind: str = "other",
        known_etag: str | None = None,
    ) -> FetchOutcome:
        started = time.monotonic()

        if not await self._robots.allowed(url, self._client):
            log.info("robots disallows", url=url)
            return FetchOutcome(
                url=url,
                status_code=None,
                outcome="robots_disallowed",
                duration_ms=int((time.monotonic() - started) * 1000),
                error="robots.txt disallows this path",
            )

        delay = self._robots.crawl_delay(url)
        if delay is not None:
            self._limiter.set_minimum_interval(urlparse(url).netloc, delay)
        await self._limiter.acquire(url)

        headers = {"If-None-Match": known_etag} if known_etag else {}

        try:
            response = await self._request(url, headers)
        except RateLimitedError as exc:
            return FetchOutcome(
                url=url,
                status_code=exc.status_code,
                outcome="http_error",
                duration_ms=int((time.monotonic() - started) * 1000),
                error=str(exc),
            )
        except httpx.TimeoutException as exc:
            return FetchOutcome(
                url=url,
                status_code=None,
                outcome="timeout",
                duration_ms=int((time.monotonic() - started) * 1000),
                error=str(exc),
            )
        except (httpx.HTTPError, FetchError) as exc:
            status = getattr(exc, "status_code", None)
            return FetchOutcome(
                url=url,
                status_code=status,
                outcome="http_error",
                duration_ms=int((time.monotonic() - started) * 1000),
                error=str(exc),
            )

        duration_ms = int((time.monotonic() - started) * 1000)

        if response.status_code == 304:
            return FetchOutcome(
                url=url,
                status_code=304,
                outcome="unchanged",
                duration_ms=duration_ms,
                headers=dict(response.headers),
            )

        stored = self.store.put(
            response.content,
            metadata={
                "url": url,
                "final_url": str(response.url),
                "fetched_at": datetime.now(UTC).isoformat(),
                "status_code": response.status_code,
                "response_headers": dict(response.headers),
                "jurisdiction_id": jurisdiction_id,
                "source_id": source_id,
                "kind": kind,
                "crawler": self.settings.crawler_user_agent,
            },
            suffix=_suffix_for(response),
        )

        return FetchOutcome(
            url=url,
            status_code=response.status_code,
            outcome="unchanged" if stored.already_present else "stored",
            duration_ms=duration_ms,
            stored=stored,
            headers=dict(response.headers),
        )

    @retry(
        retry=retry_if_exception_type((RateLimitedError, httpx.TransportError)),
        wait=wait_exponential_jitter(initial=2.0, max=60.0),
        stop=stop_after_attempt(4),
        before_sleep=_log_retry,
        reraise=True,
    )
    async def _request(self, url: str, headers: dict[str, str]) -> httpx.Response:
        response = await self._client.get(url, headers=headers)
        if response.status_code in {429, 503}:
            raise RateLimitedError(
                f"{response.status_code} from {urlparse(url).netloc}",
                url=url,
                status_code=response.status_code,
            )
        if response.status_code in RETRYABLE_STATUS:
            raise FetchError(
                f"retryable {response.status_code}", url=url, status_code=response.status_code
            )
        if response.status_code >= 400 and response.status_code != 304:
            raise FetchError(
                f"{response.status_code} from {url}", url=url, status_code=response.status_code
            )
        return response


def _suffix_for(response: httpx.Response) -> str:
    """A file extension on the stored object, purely so a human can browse the corpus."""
    media_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    return {
        "application/pdf": ".pdf",
        "text/html": ".html",
        "application/xhtml+xml": ".html",
        "application/json": ".json",
        "text/plain": ".txt",
        "text/csv": ".csv",
        "application/rss+xml": ".xml",
        "application/xml": ".xml",
        "text/xml": ".xml",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "video/mp4": ".mp4",
    }.get(media_type, "")


# ---------------------------------------------------------------------------
# Recording what happened
# ---------------------------------------------------------------------------
def record_attempt(
    conn: Connection,
    outcome: FetchOutcome,
    *,
    source_id: int | None,
    document_id: str | None,
) -> None:
    conn.execute(
        schema.fetch_attempt.insert().values(
            source_id=source_id,
            url=outcome.url,
            status_code=outcome.status_code,
            duration_ms=outcome.duration_ms,
            document_id=document_id,
            outcome=outcome.outcome,
            error=outcome.error,
        )
    )


def register_document(
    conn: Connection,
    outcome: FetchOutcome,
    *,
    jurisdiction_id: int | None,
    source_id: int | None,
    kind: str,
    title: str | None = None,
    published_on: Any = None,
) -> str | None:
    """Insert the document row for a stored object, or do nothing if it is already known."""
    if outcome.stored is None:
        return None

    stored = outcome.stored
    statement = (
        pg_insert(schema.document)
        .values(
            id=stored.digest,
            jurisdiction_id=jurisdiction_id,
            source_id=source_id,
            kind=kind,
            source_url=outcome.url,
            title=title,
            media_type=outcome.headers.get("content-type", "").split(";")[0].strip() or None,
            byte_size=stored.byte_size,
            fetched_at=datetime.now(UTC),
            published_on=published_on,
            storage_key=stored.key,
            response_headers=outcome.headers,
        )
        .on_conflict_do_nothing(index_elements=[schema.document.c.id])
    )
    conn.execute(statement)
    return stored.digest


def record_dead_letter(
    conn: Connection,
    *,
    stage: str,
    subject: str,
    jurisdiction_id: int | None,
    error_type: str,
    error_message: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Push a failure into the dead letter queue, incrementing the attempt count if it repeats.

    The queue is drained weekly to zero, per section 16.2. A queue nobody drains is a queue that
    hides a broken adapter.
    """
    statement = pg_insert(schema.dead_letter).values(
        stage=stage,
        subject=subject,
        jurisdiction_id=jurisdiction_id,
        error_type=error_type,
        error_message=error_message,
        payload=payload or {},
    )
    conn.execute(
        statement.on_conflict_do_update(
            index_elements=[schema.dead_letter.c.stage, schema.dead_letter.c.subject],
            set_={
                "attempts": schema.dead_letter.c.attempts + 1,
                "last_seen_at": datetime.now(UTC),
                "error_type": statement.excluded.error_type,
                "error_message": statement.excluded.error_message,
                "resolved_at": None,
                "resolution": None,
            },
        )
    )


def mark_source_result(conn: Connection, source_id: int, *, ok: bool) -> None:
    if ok:
        conn.execute(
            text(
                """
                UPDATE source
                SET last_checked_at = now(), last_success_at = now(), consecutive_failures = 0
                WHERE id = :id
                """
            ).bindparams(id=source_id)
        )
    else:
        conn.execute(
            text(
                """
                UPDATE source
                SET last_checked_at = now(), consecutive_failures = consecutive_failures + 1
                WHERE id = :id
                """
            ).bindparams(id=source_id)
        )


def freshness_report(conn: Connection) -> list[dict[str, Any]]:
    """Per source staleness against its own SLA.

    Section 6.12: stale data is the real outage in this business, and silent staleness is the
    fastest way to lose the one asset that matters.
    """
    rows = (
        conn.execute(
            text(
                """
            SELECT
                j.slug,
                s.kind,
                s.platform,
                s.refresh_hours,
                s.last_success_at,
                s.consecutive_failures,
                CASE
                    WHEN s.last_success_at IS NULL THEN NULL
                    ELSE round(extract(epoch FROM (now() - s.last_success_at)) / 3600.0, 1)
                END AS hours_since_success,
                CASE
                    WHEN s.last_success_at IS NULL THEN 'never'
                    WHEN now() - s.last_success_at <= make_interval(hours => s.refresh_hours) THEN 'fresh'
                    WHEN now() - s.last_success_at <= make_interval(hours => s.refresh_hours * 3) THEN 'stale'
                    ELSE 'broken'
                END AS status
            FROM source s
            JOIN jurisdiction j ON j.id = s.jurisdiction_id
            WHERE s.enabled
            ORDER BY
                CASE
                    WHEN s.last_success_at IS NULL THEN 0
                    WHEN now() - s.last_success_at > make_interval(hours => s.refresh_hours * 3) THEN 1
                    WHEN now() - s.last_success_at > make_interval(hours => s.refresh_hours) THEN 2
                    ELSE 3
                END,
                j.slug
            """
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]
