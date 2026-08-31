"""Observability: a request identifier, structured error capture, and metrics.

Audit finding P2-3 was "no error tracking, no uptime metrics, no automated or tested backups". This
module is the first two. Backups are `auspice ops backup` in the CLI, because they are not part of the
serving process.

## Why a request identifier comes before an error tracker

An unhandled exception previously produced a 500 with a traceback on stderr and nothing to join it to.
No identifier reached the client, so a customer reporting "it returned an error at about two o'clock"
could not be matched to a log line, and two simultaneous failures were indistinguishable in the log.

A third party error tracker does not fix that. It fixes triage once the identifier exists. So the
identifier is generated first, bound to the structured logger through `structlog.contextvars` so every
line emitted while handling the request carries it, returned in `X-Request-Id`, and included in the
body of every error response so it can be quoted.

The tracker is then optional and off by default. `AUSPICE_SENTRY_DSN` empty means no network calls
leave the process, which is the right default for a service that handles nothing but public records
and should not acquire a data processor without someone deciding to.

## What the metrics endpoint deliberately does not do

It is not registered at all unless `AUSPICE_METRICS_TOKEN` is set. Not registered and returning 401,
because an unauthenticated metrics endpoint publishes request volumes, error rates and model identity,
and this service already has three unauthenticated endpoints whose cost had to be bounded by hand. A
route that does not exist cannot be probed.

Counters are in process and reset on restart, which is what a Prometheus scrape expects of a counter
after a restart and is honest about what a single worker knows. The deployment runs one uvicorn worker
because the rate limiter is in process, so there is no aggregation problem to solve yet. When that
changes this becomes the seam where a shared store goes, and nothing above it changes.
"""

from __future__ import annotations

import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

import structlog

from auspice.config import get_settings
from auspice.logging import get_logger

log = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-Id"

# An inbound request id is trusted for correlation only, never for anything else, and it is bounded
# and filtered so a client cannot inject newlines into the log or unbounded strings into memory.
MAX_INBOUND_REQUEST_ID = 64
_ID_ALLOWED = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")


def new_request_id(inbound: str | None = None) -> str:
    """Reuse a caller's id when it is safe to, otherwise mint one.

    Reusing it lets a customer with their own tracing join their logs to ours. Sanitising it is not
    optional: an unfiltered header lands in a log line and in a response body.
    """
    if inbound:
        cleaned = "".join(c for c in inbound.strip() if c in _ID_ALLOWED)[:MAX_INBOUND_REQUEST_ID]
        if len(cleaned) >= 8:
            return cleaned
    return uuid.uuid4().hex


def bind_request(request_id: str, **fields: Any) -> None:
    """Bind request scoped fields so every log line in this request carries them."""
    structlog.contextvars.bind_contextvars(request_id=request_id, **fields)


def clear_request() -> None:
    structlog.contextvars.clear_contextvars()


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
@dataclass
class Metrics:
    """In process counters, rendered in the Prometheus text exposition format.

    A dependency free implementation rather than prometheus_client, because what is needed is four
    counters and a histogram of one thing, and the endpoint has to be conditionally registered, which
    is easier to get right without an instrumentator that registers itself.
    """

    started_at: float = field(default_factory=time.monotonic)
    requests: Counter[tuple[str, int]] = field(default_factory=Counter)
    errors: Counter[str] = field(default_factory=Counter)
    duration_sum: dict[str, float] = field(default_factory=dict)
    duration_count: Counter[str] = field(default_factory=Counter)
    rate_limited: int = 0
    _lock: Lock = field(default_factory=Lock, repr=False)

    def observe(self, *, route: str, status: int, seconds: float) -> None:
        with self._lock:
            self.requests[(route, status)] += 1
            self.duration_sum[route] = self.duration_sum.get(route, 0.0) + seconds
            self.duration_count[route] += 1
            if status == 429:
                self.rate_limited += 1

    def record_error(self, kind: str) -> None:
        with self._lock:
            self.errors[kind] += 1

    @property
    def uptime_seconds(self) -> float:
        return time.monotonic() - self.started_at

    def render(self, *, extra: dict[str, float | int | None] | None = None) -> str:
        """Prometheus text format. Escaping matters: a label value with a quote breaks a scrape."""
        with self._lock:
            requests = dict(self.requests)
            errors = dict(self.errors)
            duration_sum = dict(self.duration_sum)
            duration_count = dict(self.duration_count)
            rate_limited = self.rate_limited

        lines: list[str] = [
            "# HELP auspice_uptime_seconds Seconds since this process started serving.",
            "# TYPE auspice_uptime_seconds gauge",
            f"auspice_uptime_seconds {self.uptime_seconds:.3f}",
            "# HELP auspice_requests_total Requests completed, by route and status.",
            "# TYPE auspice_requests_total counter",
        ]
        for (route, status), count in sorted(requests.items()):
            lines.append(
                f'auspice_requests_total{{route="{_escape(route)}",status="{status}"}} {count}'
            )

        lines += [
            "# HELP auspice_request_duration_seconds_sum Total time spent per route.",
            "# TYPE auspice_request_duration_seconds_sum counter",
        ]
        for route, total in sorted(duration_sum.items()):
            lines.append(
                f'auspice_request_duration_seconds_sum{{route="{_escape(route)}"}} {total:.6f}'
            )

        lines += [
            "# HELP auspice_request_duration_seconds_count Requests timed per route.",
            "# TYPE auspice_request_duration_seconds_count counter",
        ]
        for route, count in sorted(duration_count.items()):
            lines.append(
                f'auspice_request_duration_seconds_count{{route="{_escape(route)}"}} {count}'
            )

        lines += [
            "# HELP auspice_unhandled_errors_total Exceptions that reached the outermost handler.",
            "# TYPE auspice_unhandled_errors_total counter",
        ]
        for kind, count in sorted(errors.items()):
            lines.append(f'auspice_unhandled_errors_total{{kind="{_escape(kind)}"}} {count}')

        lines += [
            "# HELP auspice_rate_limited_total Requests refused by the rate limiter.",
            "# TYPE auspice_rate_limited_total counter",
            f"auspice_rate_limited_total {rate_limited}",
        ]

        for name, value in sorted((extra or {}).items()):
            if value is None:
                # A missing gauge is omitted rather than reported as zero. Zero is a measurement.
                continue
            lines += [
                f"# TYPE auspice_{name} gauge",
                f"auspice_{name} {value}",
            ]

        return "\n".join(lines) + "\n"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "")


def route_template(request: Any) -> str:
    """The route pattern rather than the concrete path.

    `/v1/report/scr_ab12` and `/v1/report/scr_cd34` are one route. Using the path would make the
    label set unbounded, which is the classic way to take down a Prometheus server with a metric.
    """
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str) and template:
        return template
    return "unmatched"


# ---------------------------------------------------------------------------
# Error tracking
# ---------------------------------------------------------------------------
_sentry_ready = False


def init_error_tracking() -> bool:
    """Start the error tracker if one is configured. Returns whether it is active.

    Absent a DSN this does nothing and makes no network call, which is the correct default for a
    service that would otherwise acquire a data processor without anybody deciding to.
    """
    global _sentry_ready  # noqa: PLW0603
    settings = get_settings()
    if not settings.sentry_dsn:
        return False
    if _sentry_ready:
        return True
    try:
        import sentry_sdk
    except ImportError:
        # Configured but not installed. Say so rather than failing to start: the service is still
        # able to serve, and silent absence of error reporting is the thing being fixed here.
        log.warning(
            "error tracking is configured but sentry-sdk is not installed",
            hint="uv sync --extra api, or unset AUSPICE_SENTRY_DSN",
        )
        return False

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.env.value,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        # Public records only, but a query string can carry a coordinate pair a customer considers
        # confidential, so no request body or personal data is sent.
        send_default_pii=False,
    )
    _sentry_ready = True
    log.info("error tracking active", environment=settings.env.value)
    return True


def capture(exception: BaseException, *, request_id: str, route: str) -> None:
    """Record an unhandled exception: always to the log, and to the tracker when there is one."""
    log.error(
        "unhandled exception",
        request_id=request_id,
        route=route,
        error_type=type(exception).__name__,
        error=str(exception)[:500],
        exc_info=exception,
    )
    if not _sentry_ready:
        return
    import sentry_sdk

    with sentry_sdk.push_scope() as scope:
        scope.set_tag("request_id", request_id)
        scope.set_tag("route", route)
        sentry_sdk.capture_exception(exception)
