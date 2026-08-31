"""The FastAPI service.

One service, one process. Section 7.6 rejects microservices outright, and it is right: one person, one
service.

Two behaviours here are load bearing rather than boilerplate.

**Every response carries the disclaimer and the data date.** Section 15.1 requires this on every API
response rather than only in the terms of service, so it is added by middleware instead of by each
endpoint remembering.

**Startup fails loudly rather than degrading quietly.** If the ledger does not verify, the service
refuses to start, because serving an accuracy page from a broken chain would make a public claim on a
record that cannot be trusted.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import observability, ratelimit
from app.routers import public, score, tiles
from app.schemas import HealthResponse
from app.security import get_key_ring
from auspice import __version__
from auspice.config import Environment, get_settings
from auspice.db import dispose_engine, transaction
from auspice.errors import AuspiceError, LedgerTamperError, StageUnavailableError
from auspice.logging import get_logger

log = get_logger(__name__, _stage="api")

DISCLAIMER = "Probabilistic opinion, not legal advice. See /v1/public/methodology."

# One registry per process, created at import so it survives the lifespan and is importable by tests.
# Counters are in process and reset on restart, which is what a Prometheus scrape expects and is
# honest about what one worker knows. The deployment runs a single uvicorn worker because the rate
# limiter is in process, so there is no aggregation problem to solve yet.
METRICS = observability.Metrics()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    key_ring = get_key_ring()

    # Before anything that can fail, so a failure during startup is itself reported.
    tracking = observability.init_error_tracking()

    if key_ring.is_open and settings.env is not Environment.development:
        raise RuntimeError("AUSPICE_API_KEYS is empty outside development. The API is not public.")
    if key_ring.is_open:
        log.warning(
            "no API keys configured, so every request is treated as an enterprise principal. "
            "This is allowed in development only."
        )

    with transaction() as conn:
        from auspice import ledger

        # A broken chain means the published record cannot be trusted, so the service does not start.
        ledger.require_intact(conn)

        from auspice.score import load_serving_models

        models = load_serving_models(conn)

    app.state.models = models
    app.state.started_at = time.time()
    log.info(
        "api ready",
        serving=models.primary_kind,
        decisions=models.dataset.decided.height,
        environment=settings.env.value,
        error_tracking=tracking,
        metrics_endpoint=bool(settings.metrics_token),
    )
    for note in models.notes or []:
        log.warning("serving note", note=note)

    try:
        yield
    finally:
        dispose_engine()


settings = get_settings()

app = FastAPI(
    title="Auspice",
    version=__version__,
    summary="A rating bureau for the right to build.",
    description=(
        "Calibrated permission risk forecasts with a published accuracy record.\n\n"
        "Every response carries an interval and a data date. When the evidence is too thin the "
        "response abstains, and an abstention is a successful response rather than an error. The "
        "accuracy record and the jurisdiction profiles are public and need no key."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["X-API-Key", "Content-Type"],
)


@app.middleware("http")
async def rate_limit(request: Request, call_next: Any) -> Any:
    """Refuse a client that is asking faster than the endpoint allows.

    First in the chain, ahead of the header stamping below, so a refused request costs a dictionary lookup
    rather than a database round trip. The whole point is to spend nothing on traffic being refused.
    """
    retry_after = await ratelimit.enforce(request)
    if retry_after is not None:
        body, headers = ratelimit.refusal(request.url.path, retry_after)
        return JSONResponse(status_code=429, content=body, headers=headers)
    return await call_next(request)


@app.middleware("http")
async def add_standard_headers(request: Request, call_next: Any) -> Any:
    """Stamp every response with the version, the disclaimer, the data date and a request id.

    Section 8.9: never present a score without its interval and its data date. A header is not a
    substitute for the field inside the object, and it is a second place a consumer can read it from
    when they are looking at a raw response.

    The request id is bound to the structured logger here rather than in a separate middleware, so
    every log line emitted while handling this request carries it without any handler having to pass
    it along. It is cleared in a finally block, because contextvars outlive the request in an event
    loop worker and a leaked id would attach this request's identifier to the next one.
    """
    started = time.perf_counter()
    request_id = observability.new_request_id(request.headers.get(observability.REQUEST_ID_HEADER))
    request.state.request_id = request_id
    observability.bind_request(request_id, method=request.method, path=request.url.path)
    try:
        response = await call_next(request)
    finally:
        observability.clear_request()

    elapsed = time.perf_counter() - started
    response.headers[observability.REQUEST_ID_HEADER] = request_id
    response.headers["X-Auspice-Version"] = __version__
    response.headers["X-Auspice-Disclaimer"] = DISCLAIMER
    models = getattr(request.app.state, "models", None)
    if models is not None and models.trained_at is not None:
        response.headers["X-Auspice-Data-As-Of"] = models.trained_at.date().isoformat()
        response.headers["X-Auspice-Serving-Model"] = models.primary_kind
    response.headers["X-Auspice-Duration-Ms"] = f"{elapsed * 1000:.1f}"
    METRICS.observe(
        route=observability.route_template(request),
        status=response.status_code,
        seconds=elapsed,
    )
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception) -> JSONResponse:
    """The outermost handler. Every 500 gets logged with an identifier a customer can quote.

    Without this an unexpected exception produced a traceback on stderr, a 500 with no body a caller
    could act on, and nothing to join the two. Two simultaneous failures were indistinguishable.

    Keeping the message generic is deliberate. An identifier is what lets an operator find the
    traceback, and returning the exception text would leak internals to an unauthenticated caller.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    route = observability.route_template(request)
    METRICS.record_error(type(exc).__name__)
    observability.capture(exc, request_id=request_id, route=route)
    return JSONResponse(
        status_code=500,
        content={
            "detail": (
                "Something failed inside this service. The failure is recorded against the request "
                "identifier below. Quote it and we can find exactly what happened."
            ),
            "request_id": request_id,
        },
        headers={observability.REQUEST_ID_HEADER: request_id},
    )


@app.exception_handler(StageUnavailableError)
async def stage_unavailable(_request: Request, exc: StageUnavailableError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(LedgerTamperError)
async def ledger_tampered(_request: Request, exc: LedgerTamperError) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.exception_handler(AuspiceError)
async def domain_error(_request: Request, exc: AuspiceError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


app.include_router(score.router)
app.include_router(public.router)
app.include_router(tiles.router)


# Two things about the shape of this handler, both of them repairs, and both kept out of the docstring
# because FastAPI publishes a docstring as the endpoint description in /docs. A partner engineer reading
# this service by hand does not need three paragraphs about our own bugs.
#
# The connection is acquired inside the handler rather than through the `Db` dependency. A dependency that
# cannot connect raises before the handler body runs, so the one endpoint written to describe a degraded
# database answered 500 instead. A health check that cannot report the condition it exists to report is
# worse than no health check: a monitor reads 500 as "the service is broken" rather than "the database is
# down", and those call for different people to be woken up.
#
# Not `async def`. Everything below is synchronous, a database round trip and a full ledger verification.
# On the event loop that blocks every other request in the process. FastAPI runs a plain `def` in its
# threadpool. See the note in app/deps.py.
@app.get("/healthz", response_model=HealthResponse, tags=["operations"])
def healthz(request: Request) -> HealthResponse:
    """Liveness plus the two things that actually matter: is the ledger intact, and can we score."""
    from auspice import ledger

    detail: list[str] = []
    database = False
    chain_ok: bool | None = None

    try:
        with transaction() as conn:
            conn.execute(text("SELECT 1"))
            # Set only after the round trip succeeds. This flag was initialised to True and never
            # assigned in the failure path, so an unreachable database reported database=true and
            # status=ok. The bug was invisible because the next statement raised first and the 500 hid it.
            database = True

            try:
                # verify_head, not verify. The full walk reads every row and rehashes every payload, so its
                # cost grows with the ledger, and this endpoint is unauthenticated and deliberately exempt
                # from rate limiting. An O(entries) body here means the denial of service surface grows in
                # exact proportion to the one metric the specification says must never stall: the more
                # predictions published, the cheaper it becomes to hurt the service.
                #
                # The cheap probe catches a tail deletion and corruption of the most recent entry. It does
                # not catch tampering in the middle of the chain, and the report says so through its scope
                # field. The full walk still runs at startup through require_intact, before every publish,
                # and behind the rate limiter on the accuracy page.
                report = ledger.verify_head(conn)
                chain_ok = report.ok
                if not report.ok:
                    detail.append(f"ledger broken at sequence {report.broken_at}: {report.reason}")
            except Exception:
                # A reachable database whose ledger cannot be read is a different failure from an
                # unreachable one, and merging them would send the operator to the wrong place.
                log.exception("health check could not verify the ledger")
                detail.append("ledger verification failed")
    except Exception:
        # The driver's message names the user, host and port, and this endpoint is unauthenticated. That
        # is infrastructure disclosure for no benefit: a monitor needs to know the database is down, and
        # an operator reads the reason in the log where it belongs.
        log.exception("health check could not reach the database")
        detail.append("database unreachable")

    models = getattr(request.app.state, "models", None)
    decisions = models.dataset.decided.height if models else 0
    if models is None:
        detail.append("serving models not loaded")
    elif decisions == 0:
        detail.append("no decided applications with verified evidence, so every score will abstain")

    # `chain_ok is True` rather than `is not False`. Three states are possible and the distinction is the
    # whole reason this endpoint exists: True means the chain verified, False means it is broken, and None
    # means we could not find out. `is not False` counted "could not find out" as healthy, so a database
    # that answered while its ledger could not be read reported status ok with a detail line underneath
    # saying verification had failed. The previous version of this handler carried the same expression and
    # the state was unreachable, because the exception escaped as a 500 instead. Catching the exception
    # made it reachable, and the test written for it caught this on the first full run.
    healthy = database and models is not None and chain_ok is True
    return HealthResponse(
        status="ok" if healthy else "degraded",
        version=__version__,
        database=database,
        models_loaded=models is not None,
        serving_model=models.primary_kind if models else None,
        ledger_intact=chain_ok,
        decisions_held=decisions,
        detail=detail,
    )


# The metrics endpoint is registered only when a token exists. Not registered and answering 401,
# because an unauthenticated metrics endpoint publishes request volumes, error rates and model
# identity, this service already has three unauthenticated endpoints whose cost had to be bounded by
# hand, and a route that does not exist cannot be probed.
#
# Kept out of the OpenAPI document for the same reason, and because the text exposition format is not
# JSON and would be the only endpoint in the schema that is not.
if settings.metrics_token:

    @app.get("/metrics", include_in_schema=False, tags=["operations"])
    def metrics(request: Request) -> Response:
        """Prometheus text exposition. Requires the metrics token as a bearer credential."""
        supplied = request.headers.get("authorization", "")
        expected = f"Bearer {settings.metrics_token}"
        # Constant time, so the endpoint cannot be used as an oracle to recover the token.
        if not secrets.compare_digest(supplied, expected):
            return Response(status_code=404)

        extra: dict[str, float | int | None] = {}
        models = getattr(request.app.state, "models", None)
        if models is not None:
            extra["decisions_held"] = models.dataset.decided.height
        try:
            with transaction() as conn:
                from auspice.monitor import delivery_health

                health = delivery_health(conn)
                extra["alerts_pending"] = health["pending"]
                extra["alerts_abandoned"] = health["abandoned"]
                extra["alerts_oldest_pending_hours"] = health["oldest_pending_hours"]
        except Exception:
            # A scrape must not fail because the database is briefly unreachable. The process level
            # counters are still true and are the ones that reveal an outage.
            log.warning("metrics could not read alert delivery health")

        return Response(
            content=METRICS.render(extra=extra),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )
