"""Shared dependencies.

The serving models are fitted once at startup and held in application state. At this corpus size a fit
takes seconds and the whole training set fits in memory, so fitting on demand would waste seconds per
request for no benefit. When the corpus outgrows that, this is the seam where artefact loading goes, and
nothing above it changes.

## Why the route handlers are `def` and not `async def`

Every handler that takes a `Db` does blocking work: a synchronous SQLAlchemy round trip, and in the
scoring path polars frames, an XGBoost predict and a NumPyro posterior. `async def` puts that work on the
event loop, where it blocks every other request in the process for its whole duration. A plain `def` is
dispatched by FastAPI to its threadpool instead, so a slow request occupies a thread rather than the loop.

Every router was `async def` and none of them awaited anything. The effect compounded with the in-process
rate limiter, which caps the deployment at one uvicorn worker: one slow portfolio screen, which can carry
500 sites, stalled the health check as well as every tile the map asked for. Effective concurrency was
about one request.

What stays `async` is the code that is genuinely asynchronous: the lifespan, the two middlewares, and the
exception handlers. The middlewares await `call_next`, so they have to be.

If a handler is ever written that awaits something real, it becomes `async def` and the reasoning above
does not apply to it. The rule is not "never async", it is "not async while the body blocks".
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import Connection

from auspice.db import transaction
from auspice.score import ServingModels


def get_connection() -> Iterator[Connection]:
    """A connection inside a transaction, committed on a clean response.

    Read endpoints do not write, but the scoring path opens a savepoint to materialise a prospective
    application and roll it back, which needs a real transaction to sit inside.
    """
    with transaction() as conn:
        yield conn


def get_models(request: Request) -> ServingModels:
    models: ServingModels | None = getattr(request.app.state, "models", None)
    if models is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "The serving models are not loaded. This happens when the graph holds no decided "
                "applications with verified evidence. The service reports this rather than answering "
                "every query with the global prior, because a service that always answers looks like "
                "it is working."
            ),
        )
    return models


Db = Annotated[Connection, Depends(get_connection)]
Models = Annotated[ServingModels, Depends(get_models)]
