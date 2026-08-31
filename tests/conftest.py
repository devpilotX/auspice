"""Shared fixtures.

Database tests run against ``AUSPICE_TEST_DATABASE_URL`` and are skipped, not failed, when it is
absent. A developer without a local cluster should still be able to run the pure logic tests, and the
database tests are the ones CI exists to run.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import date
from typing import Any

import polars as pl
import pytest
from sqlalchemy import Connection, text

from auspice.config import get_settings


@pytest.fixture(autouse=True)
def _fresh_rate_limiter() -> Iterator[None]:
    """Give every test its own rate limit allowance.

    The limiter is one object in the process, which is the point of it in production and a problem in a test
    run: a test that floods a public endpoint to prove the limit works leaves the bucket empty, and the next
    test to touch the API gets a 429 that has nothing to do with what it is testing. That happened, and it
    presented as an unrelated tile test failing only when the whole suite ran.

    Cleared rather than disabled. Switching the limiter off in tests would mean the middleware is never
    exercised by anything except its own tests, and the thing worth knowing is that it sits in the real
    request path without breaking the real endpoints.
    """
    from app.ratelimit import limiter

    limiter.buckets.clear()
    limiter.last_sweep = 0.0
    yield
    limiter.buckets.clear()


def _test_database_available() -> bool:
    try:
        return get_settings().test_database_url is not None
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _test_database_available(),
    reason="AUSPICE_TEST_DATABASE_URL is not set. Run infra/scripts/bootstrap-postgres.ps1.",
)


@pytest.fixture(scope="session")
def migrated_test_database() -> Iterator[None]:
    """Bring the test database to head once per session."""
    if not _test_database_available():
        pytest.skip("no test database configured")

    from alembic import command
    from alembic.config import Config

    from auspice.config import REPO_ROOT

    config = Config(str(REPO_ROOT / "infra" / "alembic.ini"))
    os.environ["AUSPICE_ALEMBIC_TEST"] = "1"
    try:
        command.upgrade(config, "head")
        yield
    finally:
        os.environ.pop("AUSPICE_ALEMBIC_TEST", None)


@pytest.fixture
def db(migrated_test_database: None) -> Iterator[Connection]:
    """A connection inside a transaction that is always rolled back.

    Every database test therefore starts from the same state and leaves nothing behind, which matters
    because several of them insert applications and would otherwise change each other's base rates.
    """
    from auspice.db import get_engine

    engine = get_engine(test=True)
    connection = engine.connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()


@pytest.fixture
def clean_db(db: Connection) -> Connection:
    """A connection with every graph table emptied, for tests that count rows."""
    db.execute(
        text(
            """
            TRUNCATE ledger_entry, prediction, alert, change_event, watch, model_run,
                     feature_snapshot, precedent_link, jurisdiction_chain, vote, objection,
                     event, application, parcel, instrument, entity_alias, entity_cluster,
                     merge_audit, fact_evidence, extraction_run, transcript_segment,
                     document_chunk, document_page, document, dead_letter, fetch_attempt,
                     source, election, decision_maker, decision_body, jurisdiction
            RESTART IDENTITY CASCADE
            """
        )
    )
    return db


# ---------------------------------------------------------------------------
# API test clients, and the trap they exist to close
# ---------------------------------------------------------------------------
# `app.deps.get_connection` opens its own connection through `transaction()`, which uses the non test
# engine. Locally AUSPICE_DATABASE_URL points at `auspice` and AUSPICE_TEST_DATABASE_URL at
# `auspice_test`, so a TestClient request read a different database from the one the fixtures write to.
#
# That is not a theoretical problem. Measured on 2026-08-31: `auspice` held 12 jurisdictions with
# boundaries and 2 ledger entries, `auspice_test` held none of either. The tile tests asserted that a real
# tile comes back for northern Virginia and passed, against boundaries no test had created. The first
# version of the public endpoint tests published four ledger entries and the endpoint reported two.
#
# CI hides it, which is the worst property: the workflow points both variables at `auspice_test`, so the
# two agree there and diverge only on a developer's machine. Green locally, different meaning in CI.
#
# `api_client` is the fixture to use. `_refuse_untracked_api_connections` makes forgetting it loud.


@pytest.fixture(autouse=True)
def _refuse_untracked_api_connections(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Make forgetting `api_client` fail loudly instead of quietly reading the wrong database.

    Without this, a `TestClient(app)` request resolves `app.deps.get_connection`, which opens a connection
    to whatever `AUSPICE_DATABASE_URL` names. On a developer machine that is a different database from the
    one the fixtures write to, so the test asserts against data it did not create and passes for a reason
    unrelated to the code. In CI both variables name the same database, so the fault is invisible there.

    Replacing the factory means the failure arrives with an explanation at the moment it happens, rather
    than as a count that is mysteriously wrong. Tests that genuinely want an endpoint reading the database
    use `api_client`, which overrides the dependency and never reaches this.
    """
    try:
        from app import deps
    except ImportError:  # pragma: no cover - apps/api absent from the path
        yield
        return

    def _refuse(*_args: object, **_kwargs: object) -> Iterator[Connection]:
        raise RuntimeError(
            "An API endpoint opened its own database connection during a test. That connection goes to "
            "AUSPICE_DATABASE_URL, not to the test database, so it reads data the test did not create. "
            "Use the `api_client` fixture, which overrides app.deps.get_connection with the test "
            "transaction. See the note above it in tests/conftest.py."
        )

    monkeypatch.setattr(deps, "transaction", _refuse)
    yield


@pytest.fixture
def api_client(db: Connection) -> Iterator[Any]:
    """A FastAPI TestClient whose requests run inside the test transaction.

    Use this rather than constructing `TestClient(app)` directly. Anything the test writes is visible to
    the endpoint, and nothing survives the rollback.
    """
    from fastapi.testclient import TestClient

    from app.deps import get_connection
    from app.main import app

    # A generator function, not a lambda returning an iterator. FastAPI injects the yielded value for the
    # former and the iterator object itself for the latter, which fails with AttributeError on `execute`.
    def _use_the_test_connection() -> Iterator[Connection]:
        yield db

    app.dependency_overrides[get_connection] = _use_the_test_connection
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_connection, None)


@pytest.fixture
def synthetic_corpus():  # type: ignore[no-untyped-def]
    """A corpus with a known truth. Cached per session because generation is not free."""
    from tests.synthetic import generate

    return generate()


@pytest.fixture
def synthetic_dataset(synthetic_corpus):  # type: ignore[no-untyped-def]
    from auspice.models.dataset import dataset_from_frame

    return dataset_from_frame(synthetic_corpus.frame, synthetic_corpus.feature_columns)


@pytest.fixture
def synthetic_split(synthetic_dataset) -> tuple[pl.DataFrame, pl.DataFrame]:  # type: ignore[no-untyped-def]
    train, test = synthetic_dataset.temporal_split(date(2024, 1, 1))
    return train, test
