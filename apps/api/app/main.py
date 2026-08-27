"""The FastAPI service.

One service, one process. Section 7.6 rejects microservices outright, and it is right: one person, one
service.

Two behaviours here are load bearing rather than boilerplate.

**Every response carries the disclaimer and the data date.** Section 15.1 requires it on every API
response, not only in the terms of service, so it is added by middleware rather than by each endpoint
remembering.

**Startup fails loudly rather than degrading quietly.** If the ledger does not verify, the service
refuses to start, because serving an accuracy page from a broken chain would make a public claim on a
record that cannot be trusted.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.deps import Db
from app.routers import public, score
from app.schemas import HealthResponse
from app.security import get_key_ring
from auspice import __version__
from auspice.config import Environment, get_settings
from auspice.db import dispose_engine, transaction
from auspice.errors import AuspiceError, LedgerTamperError, StageUnavailableError
from auspice.logging import get_logger

log = get_logger(__name__, _stage="api")

DISCLAIMER = (
    "Probabilistic opinion, not legal advice. See /v1/public/methodology."
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    key_ring = get_key_ring()

    if key_ring.is_open and settings.env is not Environment.development:
        raise RuntimeError(
            "AUSPICE_API_KEYS is empty outside development. The API is not public."
        )
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
async def add_standard_headers(request: Request, call_next: Any) -> Any:
    """Stamp every response with the version, the disclaimer and the data date.

    Section 8.9: never present a score without its interval and its data date. A header is not a
    substitute for the field inside the object, and it is a second place a consumer can read it from
    when they are looking at a raw response.
    """
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Auspice-Version"] = __version__
    response.headers["X-Auspice-Disclaimer"] = DISCLAIMER
    models = getattr(request.app.state, "models", None)
    if models is not None and models.trained_at is not None:
        response.headers["X-Auspice-Data-As-Of"] = models.trained_at.date().isoformat()
        response.headers["X-Auspice-Serving-Model"] = models.primary_kind
    response.headers["X-Auspice-Duration-Ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
    return response


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


@app.get("/healthz", response_model=HealthResponse, tags=["operations"])
async def healthz(request: Request, conn: Db) -> HealthResponse:
    """Liveness plus the two things that actually matter: is the ledger intact, and can we score."""
    from auspice import ledger

    detail: list[str] = []
    database = True
    try:
        conn.execute(text("SELECT 1"))
    except Exception as exc:
        database = False
        detail.append(f"database unreachable: {exc}")

    chain_ok: bool | None = None
    if database:
        report = ledger.verify(conn)
        chain_ok = report.ok
        if not report.ok:
            detail.append(f"ledger broken at sequence {report.broken_at}: {report.reason}")

    models = getattr(request.app.state, "models", None)
    decisions = models.dataset.decided.height if models else 0
    if models is None:
        detail.append("serving models not loaded")
    elif decisions == 0:
        detail.append(
            "no decided applications with verified evidence, so every score will abstain"
        )

    healthy = database and models is not None and chain_ok is not False
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
