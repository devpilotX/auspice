"""Rate limiting.

Every unauthenticated endpoint on this API does real work. `/v1/public/accuracy` verifies the whole ledger,
`/v1/public/locate` runs a spatial join, and `/v1/tiles/jurisdictions/...` runs an `ST_AsMVT` over county
polygons. None of them was limited, so a single client in a loop could hold the database open until the
connection pool ran dry and every other request queued behind it.

## What this is and is not

A token bucket held in the process, keyed by API principal where there is one and by client address where
there is not. It stops a loop, a misconfigured client and a scraper.

It does not survive more than one worker, and that is stated here rather than discovered later: two uvicorn
workers means two buckets and twice the allowance. A deployment behind more than one worker needs the limit
in the reverse proxy or in a shared store, and `docs/OPERATIONS.md` says so. This is the floor, not the
ceiling, and a floor is worth having because the alternative was nothing.

It is also not a defence against a distributed source. Per-address limiting cannot be, and pretending
otherwise would be worse than the gap.

## Why the numbers are what they are

Tiles get the largest allowance because a map legitimately requests many in a burst: panning across the
lower forty eight at zoom 7 asks for tens of tiles in a second, and a limit that broke the map would be
removed within a week. Scoring gets the smallest because each request fits models and one is enough to
answer a question.

Burst is separated from sustained rate on purpose. A bucket with capacity equal to its refill rate refuses
the normal behaviour of a browser, which is to ask for everything it needs at once and then go quiet.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock

from fastapi import HTTPException, Request, status  # noqa: F401  (status used by callers)

from auspice.logging import get_logger

log = get_logger(__name__, _stage="api")


@dataclass(frozen=True, slots=True)
class Limit:
    """A sustained rate in requests per second, and how much of it may be spent at once."""

    per_second: float
    burst: int

    def __post_init__(self) -> None:
        if self.per_second <= 0 or self.burst < 1:
            raise ValueError("a limit needs a positive rate and a burst of at least one")


# Keyed by the path prefix the request falls under, longest match first.
LIMITS: tuple[tuple[str, Limit], ...] = (
    # A map pans in bursts. 40 at once covers a full screen of tiles at any zoom this serves.
    ("/v1/tiles/", Limit(per_second=20.0, burst=40)),
    # Scoring fits models. One request answers a question, and nobody needs ten a second.
    ("/v1/score", Limit(per_second=2.0, burst=5)),
    # A portfolio is up to 500 sites in one request, so the request itself is the batch.
    ("/v1/portfolio", Limit(per_second=0.5, burst=3)),
    # Public reads are cheap individually and the accuracy page verifies the ledger, so it is not free.
    ("/v1/public/", Limit(per_second=5.0, burst=20)),
)

DEFAULT_LIMIT = Limit(per_second=10.0, burst=20)

# Paths that are never limited. A health check that can be rate limited is a health check that reports an
# outage during a traffic spike, which is the opposite of useful.
EXEMPT: frozenset[str] = frozenset({"/healthz", "/docs", "/openapi.json"})


def limit_for(path: str) -> Limit:
    for prefix, limit in LIMITS:
        if path.startswith(prefix):
            return limit
    return DEFAULT_LIMIT


@dataclass(slots=True)
class _Bucket:
    tokens: float
    last: float


@dataclass(slots=True)
class RateLimiter:
    """A token bucket per key, with the buckets swept so the map cannot grow without bound.

    An unbounded dictionary keyed by client address is itself a denial of service: a client rotating
    addresses would exhaust memory. Idle buckets are dropped, which is safe because a dropped bucket is
    recreated full, and a client idle long enough to be swept has earned a full bucket anyway.
    """

    buckets: dict[str, _Bucket] = field(default_factory=dict)
    lock: Lock = field(default_factory=Lock)
    last_sweep: float = 0.0
    """When the last sweep ran, on whatever clock `check` is being given.

    Zero rather than `time.monotonic()`. Seeding it from the real clock mixed two clocks: a caller passing
    an injected `now` for a test would hand in a small number, `moment - last_sweep` would be negative, and
    the sweep would never run again. Starting at zero means the first call always sweeps, which is free on an
    empty dictionary, and every clock afterwards is the one the caller is using.
    """

    sweep_every_seconds: float = 60.0
    idle_seconds: float = 300.0

    def check(self, key: str, limit: Limit, *, now: float | None = None) -> float | None:
        """Spend a token. Returns None when allowed, or the seconds to wait when not."""
        moment = time.monotonic() if now is None else now

        with self.lock:
            self._sweep(moment)

            bucket = self.buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=float(limit.burst), last=moment)
                self.buckets[key] = bucket

            elapsed = max(0.0, moment - bucket.last)
            bucket.tokens = min(float(limit.burst), bucket.tokens + elapsed * limit.per_second)
            bucket.last = moment

            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return None

            # How long until one token exists. Reported so the client can obey rather than guess.
            return (1.0 - bucket.tokens) / limit.per_second

    def _sweep(self, moment: float) -> None:
        if moment - self.last_sweep < self.sweep_every_seconds:
            return
        self.last_sweep = moment
        stale = [
            key for key, bucket in self.buckets.items() if moment - bucket.last > self.idle_seconds
        ]
        for key in stale:
            del self.buckets[key]


def client_key(request: Request) -> str:
    """Who to charge for this request.

    A valid API key is charged to its principal, so one customer's traffic cannot exhaust another's
    allowance, and a firm behind one office address is not throttled as a single client.

    The key is resolved here rather than read from `request.state`, because this runs as middleware and
    middleware executes before the dependency that authenticates. Resolving it also matters for a second
    reason: bucketing on an unvalidated header would let anyone mint unlimited allowances by sending a
    different invented key each time. An invalid key falls through to the address, and the request will be
    refused by the endpoint anyway.

    A forwarded header is read only when the deployment says it is behind a proxy, because a client can set
    that header freely and trusting it by default hands anyone an unlimited allowance.
    """
    from app.security import get_key_ring

    presented = request.headers.get("x-api-key")
    if presented:
        key_ring = get_key_ring()
        # An open key ring is development only and resolves anything, so it must not be treated as a
        # principal here or every caller would share one bucket labelled "development".
        if not key_ring.is_open:
            principal = key_ring.resolve(presented)
            if principal is not None:
                return f"key:{principal.label}"

    from auspice.config import get_settings

    if get_settings().api_trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip()
        if first:
            return f"ip:{first}"

    host = request.client.host if request.client else "unknown"
    return f"ip:{host}"


limiter = RateLimiter()


async def enforce(request: Request) -> int | None:
    """Charge the request. Returns the Retry-After seconds when refused, None when allowed.

    Returns rather than raises, because this runs as middleware and a middleware that raises an
    HTTPException does not get the exception handler treatment a route does.
    """
    path = request.url.path
    if path in EXEMPT:
        return None

    limit = limit_for(path)
    wait = limiter.check(client_key(request), limit)
    if wait is None:
        return None

    retry_after = max(1, int(wait + 0.999))
    log.warning("rate limit exceeded", path=path, retry_after=retry_after)
    return retry_after


def refusal(path: str, retry_after: int) -> tuple[dict[str, str], dict[str, str]]:
    """The body and headers for a refusal, so the message and the header cannot disagree."""
    limit = limit_for(path)
    return (
        {
            "detail": (
                f"Too many requests. This endpoint allows {limit.per_second:g} per second with a burst "
                f"of {limit.burst}. Retry in {retry_after} second(s)."
            )
        },
        {"Retry-After": str(retry_after)},
    )
