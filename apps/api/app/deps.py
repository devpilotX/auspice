"""Shared dependencies.

The serving models are fitted once at startup and held in application state. At this corpus size a fit
takes seconds and the whole training set fits in memory, so fitting on demand would waste seconds per
request for no benefit. When the corpus outgrows that, this is the seam where artefact loading goes, and
nothing above it changes.
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
